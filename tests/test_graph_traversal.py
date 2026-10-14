"""Graph traversal executed in PostgreSQL: bounds, direction, liveness, cycles, isolation."""

from __future__ import annotations

import pytest
from app.canonicalization.merge import apply_merge
from app.graph.traversal import GraphTraversal, TraversalSpec
from app.models.enums import ValidationState
from sqlalchemy.orm import Session

from tests.support.graph import GraphBuilder

pytestmark = pytest.mark.usefixtures("clean_database")


def chain(session: Session):  # type: ignore[no-untyped-def]
    """A --REQUIRES--> B --REQUIRES--> C --REQUIRES--> D, plus B --PROVIDES--> I."""
    graph = GraphBuilder(session)
    a, b, c, d = (graph.entity(name) for name in "ABCD")
    interface = graph.entity("I", "INTERFACE")
    edges = {
        "ab": graph.relationship(a, "REQUIRES", b),
        "bc": graph.relationship(b, "REQUIRES", c),
        "cd": graph.relationship(c, "REQUIRES", d),
        "bi": graph.relationship(b, "PROVIDES", interface),
    }
    return graph, {"A": a, "B": b, "C": c, "D": d, "I": interface}, edges


def traverse(session: Session, graph: GraphBuilder, spec: TraversalSpec):  # type: ignore[no-untyped-def]
    return GraphTraversal(session, graph.project_id).traverse(spec)


def test_depth_is_bounded_and_edges_carry_their_hop(db_session: Session) -> None:
    graph, e, _ = chain(db_session)
    one = traverse(db_session, graph, TraversalSpec.outgoing(e["A"].id, depth=1))
    assert [(x.depth, x.to_id) for x in one.edges] == [(1, e["B"].id)]
    three = traverse(db_session, graph, TraversalSpec.outgoing(e["A"].id, depth=3))
    assert {x.to_id: x.depth for x in three.edges} == {
        e["B"].id: 1,
        e["C"].id: 2,
        e["I"].id: 2,
        e["D"].id: 3,
    }
    assert not three.truncated


def test_direction_and_type_filters_decide_which_edges_are_walked(
    db_session: Session,
) -> None:
    graph, e, _ = chain(db_session)
    incoming = traverse(db_session, graph, TraversalSpec.incoming(e["C"].id, depth=2))
    assert {x.to_id for x in incoming.edges} == {
        e["B"].id,
        e["A"].id,
    }  # who depends on C
    both = traverse(db_session, graph, TraversalSpec.both(e["B"].id, depth=1))
    assert {x.to_id for x in both.edges} == {e["A"].id, e["C"].id, e["I"].id}
    only_provides = traverse(
        db_session, graph, TraversalSpec.both(e["B"].id, ["PROVIDES"], depth=1)
    )
    assert [x.relationship_type for x in only_provides.edges] == ["PROVIDES"]


def test_per_type_direction_rules_allow_asymmetric_walks(db_session: Session) -> None:
    graph, e, _ = chain(db_session)
    spec = TraversalSpec(
        e["B"].id,
        depth=2,
        follow_out=frozenset({"PROVIDES"}),  # forward only along PROVIDES
        follow_in=frozenset({"REQUIRES"}),  # backward only along REQUIRES
    )
    reached = {x.to_id for x in traverse(db_session, graph, spec).edges}
    assert reached == {e["I"].id, e["A"].id}  # not C: REQUIRES is not followed forward


def test_cycles_terminate_and_each_edge_appears_once(db_session: Session) -> None:
    graph = GraphBuilder(db_session)
    a, b, c = (graph.entity(name) for name in "ABC")
    graph.relationship(a, "USES", b)
    graph.relationship(b, "USES", c)
    graph.relationship(c, "USES", a)

    result = traverse(db_session, graph, TraversalSpec.outgoing(a.id, depth=3))

    assert len(result.edges) == 3  # including the edge that closes the cycle
    assert len({x.relationship_id for x in result.edges}) == 3
    assert set(result.node_depths) == {
        b.id,
        c.id,
    }  # the root is not reported as reached


def test_the_edge_limit_truncates_and_says_so(db_session: Session) -> None:
    graph = GraphBuilder(db_session)
    hub = graph.entity("Hub")
    for index in range(8):
        graph.relationship(hub, "USES", graph.entity(f"Leaf{index}"))

    result = traverse(db_session, graph, TraversalSpec.outgoing(hub.id, edge_limit=5))

    assert len(result.edges) == 5 and result.truncated


def test_invalid_bounds_are_rejected_before_any_query(db_session: Session) -> None:
    graph = GraphBuilder(db_session)
    hub = graph.entity("Hub")
    with pytest.raises(ValueError, match="depth"):
        traverse(db_session, graph, TraversalSpec.both(hub.id, depth=4))
    with pytest.raises(ValueError, match="edge limit"):
        traverse(db_session, graph, TraversalSpec.both(hub.id, edge_limit=0))


def test_rejected_superseded_and_merged_facts_are_invisible(
    db_session: Session,
) -> None:
    graph = GraphBuilder(db_session)
    root = graph.entity("Root")
    kept, rejected, replaced, dup, other = (
        graph.entity("Kept"),
        graph.entity("Rejected"),
        graph.entity("Replaced"),
        graph.entity("Dup"),
        graph.entity("Other"),
    )
    graph.relationship(root, "USES", kept)
    graph.relationship(root, "USES", rejected, state=ValidationState.REJECTED)
    old = graph.relationship(root, "USES", replaced)
    old.superseded_by_id = graph.relationship(root, "REQUIRES", replaced).id
    graph.relationship(root, "USES", dup)
    apply_merge(
        db_session, other, dup, decided_by="HUMAN", actor_id="r"
    )  # Dup merged into Other
    ghost = graph.entity("Ghost", state=ValidationState.REJECTED)
    graph.relationship(root, "USES", ghost)  # endpoint rejected

    result = traverse(db_session, graph, TraversalSpec.outgoing(root.id))

    kinds = {(x.relationship_type, x.to_id) for x in result.edges}
    assert ("USES", kept.id) in kinds and ("REQUIRES", replaced.id) in kinds
    assert ("USES", rejected.id) not in kinds and ("USES", replaced.id) not in kinds
    assert ("USES", ghost.id) not in kinds
    assert (
        "USES",
        other.id,
    ) in kinds  # the merged duplicate's edge now belongs to its survivor
    assert ("USES", dup.id) not in kinds
    shown = traverse(
        db_session,
        graph,
        TraversalSpec(root.id, 1, None, None, 200, include_rejected=True),
    )
    assert ("USES", rejected.id) in {
        (x.relationship_type, x.to_id) for x in shown.edges
    }


def test_traversal_never_crosses_project_boundaries(db_session: Session) -> None:
    one, two = GraphBuilder(db_session, "one"), GraphBuilder(db_session, "two")
    a, b = one.entity("A"), one.entity("B")
    one.relationship(a, "USES", b)
    c, d = two.entity("C"), two.entity("D")
    two.relationship(c, "USES", d)
    outside = GraphTraversal(db_session, two.project_id).traverse(
        TraversalSpec.both(a.id)
    )
    assert outside.edges == ()
