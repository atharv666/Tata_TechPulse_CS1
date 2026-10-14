"""Small dependency-free metrics registry; metric labels never contain document content."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from threading import Lock
from time import perf_counter


class MetricsRegistry:
    def __init__(self) -> None:
        self._counters: dict[str, int] = defaultdict(int)
        self._latencies: dict[str, list[float]] = defaultdict(list)
        self._lock = Lock()

    def increment(self, name: str, value: int = 1) -> None:
        with self._lock:
            self._counters[name] += value

    def observe_ms(self, name: str, value: float) -> None:
        with self._lock:
            self._latencies[name].append(value)

    @contextmanager
    def timed(self, name: str) -> Iterator[None]:
        start = perf_counter()
        try:
            yield
        finally:
            self.observe_ms(name, (perf_counter() - start) * 1000)

    def record_extraction(self, entities_count: int, relationships_count: int) -> None:
        self.increment("extraction_entities_total", entities_count)
        self.increment("extraction_relationships_total", relationships_count)

    def record_resolution_outcome(self, outcome_type: str) -> None:
        # e.g. "exact_match", "alias_match", "merged", "new_canonical"
        self.increment(f"resolution_outcome_{outcome_type}")

    def record_query_result(
        self, total_claims: int, cited_claims: int, insufficient_evidence: bool
    ) -> None:
        self.increment("queries_total", 1)
        if insufficient_evidence:
            self.increment("queries_insufficient_evidence_total", 1)
        self.increment("query_claims_total", total_claims)
        self.increment("query_claims_cited_total", cited_claims)

    def record_review_decision(self, decision: str) -> None:
        # e.g. "VERIFIED", "CORRECTED", "REJECTED"
        self.increment(f"review_decision_{decision.lower()}")

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            latency = {
                name: {
                    "count": len(values),
                    "average_ms": round(sum(values) / len(values), 3) if values else 0,
                    "max_ms": round(max(values), 3) if values else 0,
                }
                for name, values in self._latencies.items()
            }
            counters = dict(self._counters)

            # Compute derived quality indicators
            queries_total = counters.get("queries_total", 0)
            insufficient_total = counters.get("queries_insufficient_evidence_total", 0)
            insufficient_rate = (
                round(insufficient_total / queries_total, 4) if queries_total > 0 else 0.0
            )

            claims_total = counters.get("query_claims_total", 0)
            claims_cited = counters.get("query_claims_cited_total", 0)
            citation_coverage = round(claims_cited / claims_total, 4) if claims_total > 0 else 1.0

            verified = counters.get("review_decision_verified", 0)
            corrected = counters.get("review_decision_corrected", 0)
            rejected = counters.get("review_decision_rejected", 0)
            total_reviews = verified + corrected + rejected
            correction_rate = round(corrected / total_reviews, 4) if total_reviews > 0 else 0.0

            quality_metrics = {
                "insufficient_evidence_rate": insufficient_rate,
                "citation_coverage": citation_coverage,
                "review_correction_rate": correction_rate,
            }

            return {
                "counters": counters,
                "latencies": latency,
                "quality_metrics": quality_metrics,
            }

    def reset(self) -> None:
        with self._lock:
            self._counters.clear()
            self._latencies.clear()


metrics = MetricsRegistry()
