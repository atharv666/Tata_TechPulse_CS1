# Submission Diagrams

Mermaid source for the report and synopsis figures. The same diagrams are in `SYSTEM_ARCHITECTURE.mmd` and
`IMPLEMENTATION_WORKFLOW.mmd`; the rendered images are in `figures/`.

## 1. System Architecture (`figures/system_architecture.png`)

```mermaid
flowchart TB
    U["Engineer / Reviewer"] --> UI["React + TypeScript UI<br/>Documents | Ask | Graph | Impact<br/>Review | Findings | Comparison | Audit"]
    UI --> API["FastAPI service layer<br/>(project-scoped authorization)"]
    API <--> DB[("PostgreSQL 18 + pgvector<br/>system of record")]
    API -->|"enqueue jobs"| JQ["Job queue in PostgreSQL<br/>(SKIP LOCKED, leases, retries)"]
    JQ --> W["Worker process<br/>parse > embed > extract ><br/>resolve > build graph"]
    W --> DB
    W --> LLM["LLMProvider<br/>Groq gpt-oss-120b"]
    W --> EMB["EmbeddingProvider<br/>Gemini gemini-embedding-2 (768D)"]
    W -.-> OCR["OCRProvider (optional)<br/>Tesseract | Gemini vision"]
    API --> RET["Hybrid retrieval<br/>dense (HNSW) + lexical (tsvector) + RRF"]
    API --> TRAV["Bounded graph traversal<br/>recursive CTE, max depth 3"]
    RET --> EV["Evidence bundle<br/>chunks + graph facts + provenance"]
    TRAV --> EV
    EV --> SUF{"Evidence sufficient?<br/>(max 2 rounds)"}
    SUF -- "no" --> REF["Insufficient evidence"]
    SUF -- "yes" --> ANS["Grounded answer<br/>verified claims + citations + status"]
    ANS --> UI
    DB --- STORE["documents | sections | chunks | entities<br/>relationships | evidence | findings<br/>reviews | audit | jobs | comparisons"]
    UI --> HR["Human review<br/>Verify | Edit | Reject"]
    HR --> DB
```

## 2. Implementation Workflow (`figures/implementation_workflow.png`)

```mermaid
flowchart TD
    subgraph BUILD["1. Ingestion and knowledge construction (explicit, re-runnable build)"]
        A["Upload queue<br/>one document at a time"] --> B["Validate + SHA-256 + managed storage"]
        B --> C["DOCUMENT_INGESTION<br/>parse, section tree, structure-aware chunks (OCR if needed)"]
        C --> D["EMBEDDING<br/>breadcrumb + content > pgvector (768D)"]
        D --> E["GRAPH_EXTRACTION<br/>candidate entities + staged relationships (LLM, validated)"]
        E --> F["ENTITY_RESOLUTION<br/>blocking > guards > rules > LLM for ambiguous > Union-Find"]
        F --> G["GRAPH_BUILD<br/>bind relationships, validate, confidence, findings"]
    end
    G --> H["Candidate graph facts + provenance<br/>(all PENDING)"]
    H --> I["Human review: Verify / Edit / Reject<br/>original kept, audit history"]
    subgraph ASK["2. Query"]
        Q["Question"] --> P["Planner<br/>entity linking, intent, direction, depth"]
        P --> V["Dense + lexical retrieval<br/>(RRF, relevance gate)"]
        P --> T["Bounded graph traversal<br/>(PostgreSQL recursive CTE)"]
        V --> X["Evidence bundle"]
        T --> X
        X --> S{"Sufficient?"}
        S -- "no, rounds left" --> P
        S -- "no, limit reached" --> R["Insufficient evidence"]
        S -- "yes" --> L["LLM drafts claims"]
        L --> Z["Claim verification against cited text<br/>unsupported claims dropped"]
    end
    I --> T
    Z --> O["Grounded answer + citations + graph facts + limitations"]
    I --> M["3. Analysis<br/>Impact analysis | Findings | Revision comparison | Export"]
```

The figures were rendered from these sources with Mermaid 10.9.1 in headless Chrome.
