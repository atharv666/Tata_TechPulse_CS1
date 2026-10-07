# 04 — Document Model and Context-Aware Chunking Specification

## 1. Purpose

Define the canonical internal representation of an engineering document and the context-aware chunking strategy used for embedding, semantic retrieval, and LLM-based graph extraction.

The primary objective is to preserve engineering meaning and document context while keeping individual model inputs within configured context limits.

---

# 2. Core Principle

Do NOT flatten a document into arbitrary fixed-size token windows.

The system must preserve the original document hierarchy.

Preferred structure:

```text
Document
 └── Section
      └── Subsection
           └── Subsection