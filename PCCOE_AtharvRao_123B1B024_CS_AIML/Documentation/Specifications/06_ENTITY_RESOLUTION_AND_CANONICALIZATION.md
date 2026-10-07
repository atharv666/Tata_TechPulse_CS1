# 06 — Entity Resolution and Canonicalization Specification

## 1. Purpose

This module converts raw entity mentions extracted independently from document chunks into canonical entities representing the same real-world architectural object.

The system must handle:

- spelling variation
- capitalization variation
- abbreviations
- punctuation variation
- naming conventions
- aliases
- duplicated mentions across chunks
- duplicated mentions across documents
- ambiguous similar names

The goal is to prevent the knowledge graph from being fragmented by duplicate nodes while avoiding incorrect merges.

---

# 2. Core Principle

LLM extraction happens independently for individual chunks.

Therefore, the same architectural object may be extracted multiple times.

Example:

```text
BrakeController
Brake Controller
brake_controller
Brake-Ctrl