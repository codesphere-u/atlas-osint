export type Classification = "confirmed" | "possible" | "unverified" | "rejected";
export type Level = "high" | "medium" | "low" | "very_low";

export interface User {
  id: string;
  email: string;
  role: "admin" | "analyst" | "viewer" | "auditor";
  is_active: boolean;
  created_at: string;
  last_login_at?: string | null;
}

export interface Investigation {
  id: string;
  title: string;
  subject_type: string;
  subject: string;
  subject_kind: string;
  status: "draft" | "queued" | "running" | "completed" | "failed";
  purpose: string;
  legal_basis: string;
  authorization_reference: string | null;
  consent_obtained: boolean;
  consent_reference: string | null;
  authorized_domains: string[];
  options: Record<string, unknown>;
  created_by: string;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  retention_until: string;
  error: string | null;
  progress: { done?: number; total?: number; sources?: Record<string, string> };
  finding_count: number;
  confirmed_count: number;
}

export interface CoverageRun {
  source: string;
  display_name: string;
  category: string | null;
  reliability: string | null;
  license: string | null;
  identifier: string;
  reason: string;
  status: string;
  message: string | null;
  findings: number;
  duration_ms: number;
}

export interface Coverage {
  by_source?: Record<string, string>;
  runs?: CoverageRun[];
  status_counts?: Record<string, number>;
  sources_consulted?: number;
  sources_answered?: number;
  sources_disabled?: string[];
  coverage_ratio?: number;
  classification_counts?: Record<string, number>;
  suppressed_items?: number;
  policy?: { attributes_removed?: Record<string, number>; redactions?: Record<string, number> };
}

export interface InvestigationDetail extends Investigation {
  coverage: Coverage;
  module_summary: Record<string, unknown>;
  entity_count: number;
  relationship_count: number;
  contradiction_count: number;
}

export interface ConfidenceReason {
  rule: string;
  delta: number;
  explanation: string;
}

export interface LinkedIdentifier {
  identifier: { type: string; value: string };
  relation: string;
  evidence_kind: string;
}

export interface Finding {
  id: string;
  module: string;
  source_name: string;
  source_display_name: string;
  source_url: string;
  source_category: string;
  reliability: string;
  finding_type: string;
  title: string;
  description: string;
  match_type: "exact" | "similar" | "related" | "inferred";
  evidence_kind: "direct" | "inference";
  attributes: Record<string, unknown>;
  linked: LinkedIdentifier[];
  entity_kind: string | null;
  evidence: { excerpt: string | null; metadata: Record<string, unknown>; content_hash: string | null };
  collected_at: string;
  published_at: string | null;
  confidence: { score: number; level: Level; reasons: ConfidenceReason[] } | null;
  verification_status: string;
  citation: string | null;
  flags: string[];
  classification: Classification;
}

export interface GraphNode {
  id: string;
  label: string;
  kind: string;
  is_subject: boolean;
  confidence: number;
  finding_ids: string[];
  identifiers: string[];
  attributes: Record<string, unknown>;
}

export interface GraphEdge {
  id: string;
  source_entity_id: string;
  target_entity_id: string;
  type: string;
  evidence_kind: "direct" | "inference";
  finding_ids: string[];
  confidence: number;
  rationale: string;
}

export interface Graph {
  nodes: GraphNode[];
  edges: GraphEdge[];
  name_collisions: { name: string; entity_ids: string[]; explanation: string }[];
  contradictions: { attribute: string; explanation: string; values: Record<string, string[]> }[];
}

export interface TimelineEvent {
  date: string;
  label: string;
  finding_id: string;
  source: string;
  date_kind: string;
  category: string;
}

export interface Statement {
  statement: string;
  category: "confirmed" | "possible" | "unknown";
  finding_ids: string[];
}

export interface Analysis {
  provider: string;
  model: string | null;
  generated_at: string;
  ai_generated: boolean;
  summary: string;
  confirmed_facts: Statement[];
  possible_matches: Statement[];
  unknowns: string[];
  inconsistencies: Statement[];
  relationships: Statement[];
  timeline: TimelineEvent[];
  confidence_explanations: { finding_id: string; title: string; score: number; level: string; reasons: string[] }[];
  insufficient_evidence: string[];
  injection_flags: Record<string, string[]>;
  validation_notes: string[];
  disclaimer: string;
}

export interface Source {
  name: string;
  display_name: string;
  description: string;
  category: string;
  input_types: string[];
  access_method: string;
  homepage: string;
  auth: { required: boolean; kind: string; settings_fields: string[]; optional: boolean; how_to_obtain: string | null };
  rate_limit: { requests: number; per_seconds: number; notes: string | null };
  legal: {
    terms_url: string | null;
    license: string | null;
    restrictions: string;
    contains_personal_data: boolean;
    requires_subject_consent: boolean;
    active_probe: boolean;
  };
  fields: string[];
  freshness: string;
  reliability: string;
  enabled: boolean;
  min_role: string;
  configured: boolean;
  configuration_message: string;
  health: Record<string, number>;
}

export interface Meta {
  version: string;
  identifier_types: string[];
  subject_kinds: string[];
  legal_bases: string[];
  require_consent_for_individuals: boolean;
  default_retention_days: number;
  max_retention_days: number;
  ai_provider: string;
  modules: { name: string; title: string; input_types: string[]; guardrails: string[] }[];
  methodology: string[];
}

export interface Note {
  id: string;
  finding_id: string | null;
  author: string;
  body: string;
  created_at: string;
}
