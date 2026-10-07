# API Contracts

## 1. Purpose

This document defines the backend API contract for the AUTOSAR Architecture Intelligence Assistant.

The API should be implemented with FastAPI.

All request and response payloads must use typed Pydantic models.

The API layer must not contain core graph, ingestion, retrieval, or LLM business logic.

Use:

```text
API Router
    |
    v
Service Layer
    |
    v
Repository / Provider Layer