"""Unit and integration tests for Phase 19 demo data, graph build, and benchmark execution."""

from scripts.benchmark import run_benchmark
from scripts.build_graph import run_graph_build
from scripts.seed_demo_data import seed_demo_data


def test_seed_demo_data_execution() -> None:
    res = seed_demo_data()
    assert res["documents"] >= 1
    assert res["entities"] >= 10
    assert res["relationships"] >= 5


def test_build_graph_execution() -> None:
    seed_demo_data()
    details = run_graph_build()
    assert isinstance(details, dict)


def test_benchmark_execution_metrics() -> None:
    summary = run_benchmark()
    assert summary["total_questions"] == 9
    assert summary["passed_questions"] == 9
    assert summary["precision"] == 1.0
    assert summary["citation_coverage"] == 1.0
    assert summary["average_latency_ms"] >= 0
