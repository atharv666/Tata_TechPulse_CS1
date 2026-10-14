export type Id = string;

export interface PageResponse<T> {
  items: T[];
  offset: number;
  limit: number;
  total: number;
}

export interface Project {
  id: Id;
  name: string;
  description: string | null;
  created_at?: string;
}

export interface Document {
  id: Id;
  name: string;
  media_type: string;
  created_by: string;
  created_at?: string;
}

export interface DocumentVersion {
  id: Id;
  document_id: Id;
  version_number: number;
  checksum: string;
  source_label: string | null;
  created_at?: string;
}

export interface Job {
  id: Id;
  job_type: string;
  state: string;
  details: Record<string, unknown>;
  created_at?: string;
  updated_at?: string;
}

/** What every graph fact carries: a confidence is never shown without its context. */
export interface FactStatus {
  confidence: number;
  extraction_type: string;
  validation_state: string;
  status_text?: string;
}

export interface Entity extends FactStatus {
  id: Id;
  canonical_name: string;
  entity_type: string;
  trust_state: string;
  raw_confidence?: number | null;
  merged_into_id?: Id | null;
  superseded_by_id?: Id | null;
}

export interface Relationship extends FactStatus {
  id: Id;
  source_entity_id: Id;
  target_entity_id: Id;
  relationship_type: string;
  trust_state: string;
  superseded_by_id?: Id | null;
}

export interface Provenance {
  chunk_id: Id;
  document_id: Id;
  document_version_id: Id;
  document_name: string;
  section_heading: string;
  page_start: number | null;
  page_end: number | null;
  source_classification: string;
  excerpt: string;
}

export interface HistoryItem {
  state: string;
  actor_id: string;
  reason: string | null;
  created_at: string | null;
}

export interface Finding {
  id: Id;
  finding_type: string;
  severity: string;
  status: string;
  summary: string;
  details: Record<string, unknown>;
  entity_id: Id | null;
  relationship_id: Id | null;
  confidence: number | null;
  detected_by: string;
  dismissed_by: string | null;
  dismissed_reason: string | null;
  created_at: string | null;
}

export interface EntityDetail extends Entity {
  aliases: Array<{ alias: string; source: string }>;
  merged_entities: Array<{
    merge_id: Id;
    entity_id: Id;
    name: string;
    decided_by: string;
    similarity: number | null;
    reason: string | null;
  }>;
  evidence: Provenance[];
  history: HistoryItem[];
  relationship_count: number;
  findings: Finding[];
}

export interface RelationshipDetail extends Relationship {
  source: { id: Id; name: string; entity_type: string };
  target: { id: Id; name: string; entity_type: string };
  evidence: Provenance[];
  history: HistoryItem[];
  findings: Finding[];
}

export interface MergeRecord {
  id: Id;
  canonical_entity_id: Id;
  canonical_name: string;
  merged_entity_id: Id;
  merged_name: string;
  decided_by: string;
  rule: string | null;
  similarity: number | null;
  reason: string | null;
  llm_model: string | null;
  blocking_keys: string[];
  created_at: string | null;
  undone_at: string | null;
  undone_by: string | null;
}

export interface Citation {
  citation_id: string;
  document_name: string;
  section_heading: string;
  section_path?: string;
  page_start: number | null;
  page_end: number | null;
  excerpt: string;
  document_version_id: Id;
  role?: string;
  document_status?: string | null;
}

export interface Claim {
  text: string;
  citation_ids: string[];
  extraction_type: string;
  support?: number | null;
}

export interface GraphFactEvidence {
  fact_id: string;
  source_entity: string;
  relationship_type: string;
  target_entity: string;
  confidence: number;
  extraction_type: string;
  validation_state: string;
  citation_ids: string[];
}

export interface GraphPath {
  entity_ids: Id[];
  entity_names?: string[];
  relationship_ids: Id[];
  relationship_types?: string[];
}

export interface Answer {
  status: string;
  mode?: string;
  summary: string;
  claims: Claim[];
  citations: Citation[];
  conflicts: string[];
  insufficient_evidence: boolean;
  confidence?: number | null;
  confidence_basis?: string;
  graph_facts?: GraphFactEvidence[];
  graph_paths?: GraphPath[];
  related_findings?: Array<{ id: string; finding_type: string; severity: string; summary: string }>;
  limitations?: string[];
  dropped_claims?: number;
}

export interface ImpactResult {
  kind: string;
  affected_entity_id: Id | null;
  affected_entity_name: string | null;
  affected_entity_type: string | null;
  hops: number;
  via: string[];
  confidence: number | null;
  extraction_type: string | null;
  validation_state: string | null;
  path: { entity_ids: Id[]; relationship_ids: Id[] };
  source_evidence: Array<{ fact: GraphFactEvidence; citations: Citation[] }>;
  message: string | null;
}

export interface ImpactAnalysis {
  root_entity_id: Id;
  root_entity_name: string;
  results: ImpactResult[];
  truncated: boolean;
  summary: Record<string, number>;
  affected_tests: string[];
  notes: string[];
}

export interface ReviewItem extends FactStatus {
  fact_kind: "ENTITY" | "RELATIONSHIP";
  fact_id: Id;
  label: string;
  provenance: Provenance[];
}

export interface AuditEvent {
  action: string;
  actor_id: string;
  resource_type: string;
  resource_id: Id;
  details: Record<string, unknown>;
  created_at: string | null;
}

export interface ComparisonSummary {
  id: Id;
  base_version_id: Id;
  target_version_id: Id;
  state: string;
  requested_by: string;
  created_at?: string | null;
}

export interface ComparisonDetail extends ComparisonSummary {
  finding_count: number;
  summary: Record<string, number>;
}

export interface RevisionFindingDetails {
  scope: "DOCUMENT" | "SECTION" | "ENTITY" | "RELATIONSHIP";
  classification: string;
  severity: string;
  confidence: number;
  summary: string;
  changes: Record<string, unknown>;
  old_evidence: { citations: Citation[] };
  new_evidence: { citations: Citation[] };
  review_status: string;
  impacts: ImpactResult[];
}

export interface ComparisonFinding {
  id: Id;
  comparison_id: Id;
  entity_id: Id | null;
  finding_type: string;
  confidence: number;
  summary: string;
  details: RevisionFindingDetails;
}

export interface ApiError {
  code: string;
  message: string;
  request_id?: string;
}
