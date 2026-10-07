# Recorded Synthetic Benchmark Result

**Recorded on:** 7 October 2026  
**Command:** `PYTHONPATH=E:\TATA\backend;E:\TATA python scripts\benchmark.py`  
**Fixture set:** synthetic BrakeController evaluation harness

## Result

| Measure | Recorded value | Interpretation |
| --- | ---: | --- |
| Evaluation cases | 9 | Entity, relationship, dependency, impact, summary, interface, revision, alias, and insufficient-evidence cases |
| Passed cases | 9 / 9 | **100.0% synthetic harness pass rate** |
| Citation coverage | 100.0% | Every constructed fixture case supplied citation evidence to the evidence-sufficiency check |
| Average deterministic check latency | 0.04 ms | In-process fixture timing only; excludes database, network, model, and browser latency |
| Maximum deterministic check latency | 0.16 ms | In-process fixture timing only |
| Focused automated tests | 28 passed | Grounded answers, human review, graph build, impact analysis, revision comparison, and evaluation fixtures |

## What this result supports

The result demonstrates that the submitted deterministic logic accepts the intended synthetic evaluation fixtures, validates citation sufficiency, resolves the included alias case, and returns insufficient evidence when no evidence is supplied.

## What this result does not support

It does not measure live provider quality, document-parser OCR quality, retrieval relevance against a large corpus, or factual correctness on unseen AUTOSAR HLDs. The benchmark constructs some evidence in memory, so it must not be described as an end-to-end live-LLM accuracy score.

For the presentation, use this exact wording:

> “The synthetic regression harness passed 9 of 9 defined checks with 100% constructed-fixture citation coverage. We do not treat this as a claim of 100% live model accuracy; end-to-end results are demonstrated with source citations and human review.”

## Screenshot evidence still required

Capture E1–E5 from the running application and place them under `Screenshots/`. Record the filename, exact question, displayed citations, provider/model configuration, and manual pass/fail judgement in `EVALUATION_LOG.md`.
