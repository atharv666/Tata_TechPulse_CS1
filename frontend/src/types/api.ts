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

export interface Entity {
  id: Id;
  canonical_name: string;
  entity_type: string;
  confidence: number;
  extraction_type: string;
  validation_state: string;
  trust_state: string;
  aliases?: string[];
  evidence_excerpt?: string;
}

export interface Relationship {
  id: Id;
  source_entity_id: Id;
  target_entity_id: Id;
  relationship_type: string;
  confidence: number;
  extraction_type: string;
  validation_state: string;
  trust_state: string;
  evidence_excerpt?: string;
}

export interface Citation {
  citation_id: string;
  document_name: string;
  section_heading: string;
  page_start: number | null;
  page_end: number | null;
  excerpt: string;
  document_version_id: Id;
}

export interface Claim {
  text: string;
  citation_ids: string[];
  extraction_type: string;
}

export interface GraphPath {
  entity_ids: Id[];
  relationship_ids: Id[];
}

export interface Answer {
  status: string;
  summary: string;
  claims: Claim[];
  citations: Citation[];
  conflicts: string[];
  insufficient_evidence: boolean;
  confidence?: number;
  graph_paths?: GraphPath[];
  limitations?: string[];
}

export interface ImpactResult {
  kind: string;
  affected_entity_id: Id | null;
  affected_entity_name: string | null;
  affected_entity_type: string | null;
  confidence: number | null;
  extraction_type: string | null;
  validation_state: string | null;
  path: GraphPath;
  source_evidence: unknown[];
  message: string | null;
}

export interface ImpactAnalysis {
  root_entity_id: Id;
  results: ImpactResult[];
  truncated: boolean;
}

export interface ProvenanceSource {
  document_name: string;
  section_heading: string;
  page_start: number | null;
  excerpt: string;
}

export interface ReviewItem {
  fact_kind: "ENTITY" | "RELATIONSHIP";
  fact_id: Id;
  label: string;
  confidence: number;
  extraction_type: string;
  validation_state: string;
  provenance: ProvenanceSource[];
}

export interface AuditEvent {
  id: Id;
  action: string;
  actor_id: string;
  resource_type: string;
  resource_id: Id;
  project_id: Id;
  details: Record<string, unknown>;
  created_at: string;
}

export interface ComparisonFinding {
  id: Id;
  comparison_id: Id;
  entity_id: Id | null;
  finding_type: string;
  summary: string;
  details: Record<string, unknown>;
}

export interface ApiError {
  code: string;
  message: string;
  request_id?: string;
}
