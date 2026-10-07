# 5–10 Minute Demonstration Script

## 0:00–0:45 — Problem and guardrails

Introduce the AUTOSAR Architecture Intelligence Assistant. Explain that it creates evidence-linked candidate knowledge from HLDs, preserves provenance, and requires human validation rather than treating model output as automatically trusted.

## 0:45–2:15 — Input and ingestion

Show `Input_Data/BrakeController_HLD_v1.md`. Upload it through Documents. Show the persisted ingestion job, document version, sections/chunks, and the worker progression. Mention safe handling: file validation, content hashing, managed storage, and project isolation.

## 2:15–3:30 — RAG and graph pipeline

Explain the sequence: chunk embeddings in pgvector, structured candidate extraction, canonicalization/validation, explicit graph build, and provenance evidence. Show the graph and inspect one node/edge with its document evidence, confidence, extraction type, and validation state.

## 3:30–5:00 — Ask Architecture

Ask a prepared question such as: “Which component uses WheelSpeedInterface?” Show the natural-language response, claims, citations, source excerpts, and limitations. State that insufficient evidence is returned when the system cannot support a claim.

## 5:00–6:15 — Impact and review

Run an impact question for an interface change. Show direct/indirect paths. Verify, correct, or reject one pending fact; show that the original candidate and audit history remain preserved.

## 6:15–7:15 — Revision comparison and evaluation

Optionally upload the included v2 synthetic HLD from the code snapshot, run comparison, and show findings. Display the completed evaluation log and automated test output.

## 7:15–8:00 — Configuration and limitations

State the selected providers, declared hosted-API dependency, and provider abstraction. Explain that Ollama/local providers are supported by configuration but not used in the demo due to hardware constraints. Summarize limitations without overstating measured accuracy.

## Recording checklist

- Do not display `.env`, API keys, passwords, or confidential documents.
- Use synthetic data only unless written approval exists.
- Ensure citations and provenance are visible in at least one answer.
- Record a fallback video only from the submitted source/configuration version.
