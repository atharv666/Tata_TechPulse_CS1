import type { ComparisonFinding, Finding } from "../types/api";
import { groupBy } from "./format";

const SEVERITY_RANK: Record<string, number> = { HIGH: 0, MEDIUM: 1, LOW: 2, INFO: 3 };

export const severityRank = (severity: string): number => SEVERITY_RANK[severity] ?? 9;

export function sortFindings<T extends { severity: string }>(items: T[]): T[] {
  return [...items].sort((a, b) => severityRank(a.severity) - severityRank(b.severity));
}

/** Open potential inconsistencies first, by severity; dismissed ones last. */
export function orderGraphFindings(items: Finding[]): Finding[] {
  const order: Record<string, number> = { OPEN: 0, DISMISSED: 1, RESOLVED: 2 };
  return [...items].sort(
    (a, b) => (order[a.status] ?? 9) - (order[b.status] ?? 9) || severityRank(a.severity) - severityRank(b.severity),
  );
}

export interface ChangeGroup {
  scope: string;
  items: ComparisonFinding[];
}

const SCOPE_ORDER = ["DOCUMENT", "SECTION", "ENTITY", "RELATIONSHIP"];

/** Comparison findings grouped by what changed (document, section, entity, relationship). */
export function groupChanges(findings: ComparisonFinding[]): ChangeGroup[] {
  const groups = groupBy(findings, (finding) => finding.details.scope);
  return SCOPE_ORDER.filter((scope) => groups[scope]?.length).map((scope) => ({
    scope,
    items: sortFindings(groups[scope].map((item) => ({ ...item, severity: item.details.severity }))) as ComparisonFinding[],
  }));
}

/** The wording rule: detection is a prompt for a human, never a verdict. */
export function isPotentialWording(summary: string): boolean {
  return summary.startsWith("Potential inconsistency detected:");
}
