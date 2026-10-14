import type { Citation, FactStatus } from "../types/api";

/**
 * The API serialises decimal values (confidence, similarity, groundedness) as JSON *strings*
 * ("0.900"), although the types say number. Every numeric use goes through this.
 */
export function toNumber(value: unknown): number | null {
  if (value === null || value === undefined || value === "") return null;
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

/** "Confidence 0.94 · EXPLICIT · PENDING": a number never travels without its context. */
export function statusText(fact: FactStatus): string {
  if (fact.status_text) return fact.status_text;
  const confidence = toNumber(fact.confidence);
  const shown = confidence === null ? "unknown" : confidence.toFixed(2);
  return `Confidence ${shown} · ${fact.extraction_type} · ${fact.validation_state}`;
}

export function percent(value: unknown): string {
  const parsed = toNumber(value);
  return parsed === null ? "—" : `${Math.round(parsed * 100)}%`;
}

export function citationLabel(citation: Citation): string {
  const where = citation.section_path || citation.section_heading;
  const page = citation.page_start !== null ? ` · p. ${citation.page_start}` : "";
  const status = citation.document_status ? ` · ${citation.document_status}` : " · status not declared";
  return `${citation.document_name} · ${where}${page}${status}`;
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "—";
  if (seconds < 1) return "<1 s";
  if (seconds < 90) return `${Math.round(seconds)} s`;
  return `${Math.round(seconds / 60)} min`;
}

export function humanize(value: string): string {
  return value
    .toLowerCase()
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

export function groupBy<T>(items: T[], key: (item: T) => string): Record<string, T[]> {
  const groups: Record<string, T[]> = {};
  for (const item of items) {
    (groups[key(item)] ??= []).push(item);
  }
  return groups;
}

export const ENTITY_TYPES = [
  "COMPONENT",
  "SOFTWARE_COMPONENT",
  "INTERFACE",
  "PORT",
  "SIGNAL",
  "DATA_ELEMENT",
  "RUNNABLE",
  "FUNCTION",
  "ECU",
  "COMMUNICATION_CHANNEL",
  "DATA_TYPE",
  "REQUIREMENT",
  "FUNCTIONAL_FLOW",
  "TEST_CASE",
] as const;

export const RELATIONSHIP_TYPES = [
  "USES",
  "REQUIRES",
  "PROVIDES",
  "CONSUMES",
  "PRODUCES",
  "CARRIES",
  "DEPENDS_ON",
  "CONNECTS_TO",
  "PART_OF",
  "IMPLEMENTED_BY",
  "PRECEDES",
  "TRIGGERS",
  "SENDS_TO",
  "VERIFIED_BY",
] as const;
