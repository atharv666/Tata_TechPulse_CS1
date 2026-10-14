import type { Entity, FactStatus, Relationship } from "../types/api";
import { toNumber } from "./format";

export type Tone = "green" | "blue" | "orange" | "red";

/**
 * Visual state of a fact. Colour is never the only signal: ``toneLabel`` is shown as text next to it.
 *   green  = human verified / corrected
 *   blue   = explicitly extracted, pending validation
 *   orange = inferred or lower confidence
 *   red    = rejected
 */
export function tone(fact: Pick<FactStatus, "validation_state" | "extraction_type" | "confidence">): Tone {
  if (fact.validation_state === "REJECTED") return "red";
  if (fact.validation_state === "HUMAN_VERIFIED" || fact.validation_state === "HUMAN_CORRECTED") return "green";
  if (fact.extraction_type === "INFERRED" || (toNumber(fact.confidence) ?? 0) < 0.7) return "orange";
  return "blue";
}

const LABELS: Record<Tone, string> = {
  green: "Human verified",
  blue: "Explicit, pending review",
  orange: "Inferred / lower confidence",
  red: "Rejected",
};

export const toneLabel = (value: Tone): string => LABELS[value];

export const TONE_HEX: Record<Tone, string> = { green: "#2e9b5f", blue: "#2f6fcf", orange: "#d9822b", red: "#c8423b" };

export interface EntityFilter {
  query: string;
  type: string;
  state: string;
}

export function filterEntities(entities: Entity[], filter: EntityFilter): Entity[] {
  const query = filter.query.trim().toLowerCase();
  return entities.filter(
    (entity) =>
      (!filter.type || entity.entity_type === filter.type) &&
      (!filter.state || entity.validation_state === filter.state) &&
      (!query || `${entity.canonical_name} ${entity.entity_type}`.toLowerCase().includes(query)),
  );
}

/** Keep only relationships whose two ends are both on screen. */
export function visibleRelationships(relationships: Relationship[], entities: Entity[]): Relationship[] {
  const ids = new Set(entities.map((entity) => entity.id));
  return relationships.filter((edge) => ids.has(edge.source_entity_id) && ids.has(edge.target_entity_id));
}

export function countByTone(facts: Array<Pick<FactStatus, "validation_state" | "extraction_type" | "confidence">>): Record<Tone, number> {
  const counts: Record<Tone, number> = { green: 0, blue: 0, orange: 0, red: 0 };
  for (const fact of facts) counts[tone(fact)] += 1;
  return counts;
}
