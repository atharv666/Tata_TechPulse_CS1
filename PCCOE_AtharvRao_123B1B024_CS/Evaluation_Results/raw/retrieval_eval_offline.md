# RAG evaluation: ABS subsystem HLD (synthetic) (offline providers)

Questions: 23 (19 answerable, 4 unanswerable), top-k = 8

| Metric | Value |
| --- | ---: |
| Recall@k (expected section retrieved) | 94.7% |
| MRR | 0.8947 |
| Context recall (incl. parent/neighbour context) | 94.7% |
| Evidence terms present in context | 94.7% |
| Answer terms present in answer (needs a real LLM) | 79.0% |
| Citation validity | 100.0% |
| Refusal accuracy on unanswerable questions | 100.0% |
| False refusals on answerable questions | 5.3% |
| Dropped (unsupported) claim rate | 0.0% |
| Latency mean / p95 (ms) | 216.0 / 501.3 |

| Id | Category | Rank | Refused | Context | Evidence terms | Citations valid |
| --- | --- | ---: | :---: | :---: | :---: | :---: |
| abs-01 | component | 1 | no | yes | yes | yes |
| abs-02 | component | 1 | no | yes | yes | yes |
| abs-03 | component | 1 | no | yes | yes | yes |
| abs-04 | alias | 1 | no | yes | yes | yes |
| abs-05 | alias | 1 | no | yes | yes | yes |
| abs-06 | interface | 1 | no | yes | yes | yes |
| abs-07 | interface | 2 | no | yes | yes | yes |
| abs-08 | dependency | 1 | no | yes | yes | yes |
| abs-09 | dependency | 1 | no | yes | yes | yes |
| abs-10 | dependency | 1 | no | yes | yes | yes |
| abs-11 | port | 2 | no | yes | yes | yes |
| abs-12 | identifier | 1 | no | yes | yes | yes |
| abs-13 | timing | 1 | no | yes | yes | yes |
| abs-14 | timing | 1 | no | yes | yes | yes |
| abs-15 | timing | 1 | no | yes | yes | yes |
| abs-16 | diagnostics | 1 | no | yes | yes | yes |
| abs-17 | diagnostics | 1 | no | yes | yes | yes |
| abs-18 | diagnostics | 1 | no | yes | yes | yes |
| abs-19 | hierarchy | - | yes | no | no | yes |
| abs-20 | unanswerable | - | yes | no | yes | yes |
| abs-21 | unanswerable | - | yes | no | yes | yes |
| abs-22 | unanswerable | - | yes | no | yes | yes |
| abs-23 | unanswerable | - | yes | no | yes | yes |
