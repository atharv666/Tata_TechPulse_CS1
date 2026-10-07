import type { Entity, Relationship } from "../types/api";

type Fact = Pick<Entity | Relationship, "validation_state" | "extraction_type" | "confidence">;

export function statusTone(fact: Fact): "green" | "blue" | "orange" | "red" {
  if (fact.validation_state === "REJECTED") return "red";
  if (fact.validation_state === "HUMAN_VERIFIED") return "green";
  if (fact.extraction_type === "INFERRED" || fact.confidence < 0.7) return "orange";
  return "blue";
}

export function StatusBadge({ fact }: { fact: Fact }) {
  return <span className={`status status-${statusTone(fact)}`}>{fact.validation_state} · {fact.extraction_type} · {Math.round(fact.confidence * 100)}%</span>;
}
