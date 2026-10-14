
---

# `11_GRAPH_TRAVERSAL_AND_IMPACT_ANALYSIS.md`

```md
# Graph Traversal and Impact Analysis

## 1. Purpose

This document defines graph traversal over the PostgreSQL relational knowledge graph.

The graph is represented using relational adjacency-list tables.

The purpose of traversal is to answer architecture questions such as:

- What depends on this component?
- What does this interface provide?
- Which components consume this signal?
- What could be affected by changing this interface?
- Which architectural entities are connected through a specific relationship path?

---

# 2. Graph Representation

The graph consists primarily of:

```text
entities
relationships
entity_evidence
relationship_evidence