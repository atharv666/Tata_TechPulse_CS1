# 05 — AUTOSAR Knowledge Model Specification

## 1. Purpose

Define the domain-specific entity and relationship vocabulary used by the AUTOSAR Architecture Intelligence Assistant.

The knowledge graph must represent architectural concepts in a controlled, auditable manner.

This document defines the initial MVP taxonomy.

The taxonomy may evolve as real HLD samples are analyzed.

---

# 2. Core Principle

The graph represents architectural knowledge extracted from source documents.

A graph node represents an identifiable architectural entity.

A graph edge represents a directed, semantically typed relationship between entities.

Example:

```text
BrakeController
      |
   REQUIRES
      |
      v
WheelSpeedInterface