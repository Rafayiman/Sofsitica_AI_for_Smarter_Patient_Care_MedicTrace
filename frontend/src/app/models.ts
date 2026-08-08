export interface GroupFlag {
  rule_id: string;
  count: number;
}

export type GroupSummary =
  | { kind: 'numeric'; min: number; max: number; mean: number }
  | { kind: 'text'; mode: string; mode_count: number };

export interface EventGroup {
  date: string;
  event_type: string;
  event_subtype: string;
  source_table: string;
  encounter_id: string | null;
  count: number;
  value: string | null;
  unit: string | null;
  summary: GroupSummary | null;
  first_timestamp: string;
  last_timestamp: string;
  flags: GroupFlag[];
}

export interface TimelineDay {
  date: string;
  groups: EventGroup[];
}

export interface TimelineResponse {
  patient_id: string;
  days: TimelineDay[];
}

export interface Flag {
  rule_id: string;
  description: string;
  severity: string | null;
}

export interface RawEvent {
  event_id: string;
  patient_id: string;
  encounter_id: string | null;
  event_type: string;
  event_subtype: string | null;
  value: string | null;
  value_numeric: number | null;
  unit: string | null;
  event_timestamp: string;
  source_table: string;
  source_row_id: string;
  flags: Flag[];
}

export interface GroupExpandResponse {
  patient_id: string;
  event_count: number;
  events: RawEvent[];
}

export interface Patient {
  patient_id: string;
  gender: string | null;
  anchor_age: string | null;
  encounter_ids: string[];
}

export interface PatientsResponse {
  patients: Patient[];
}

export interface Citation {
  table: string;
  field: string;
  event_id: string;
  timestamp: string | null;
  value: string | null;
  value_numeric: number | null;
  unit: string | null;
}

export interface AskResponse {
  status: 'answered' | 'not_found' | 'out_of_scope' | 'error';
  answer_summary: string;
  citations: Citation[];
  query: string | null;
}

export interface SeverityCount {
  severity: string | null;
  count: number;
}

export interface RuleSummary {
  rule_id: string;
  severity_counts: SeverityCount[];
}

export interface TableCoverage {
  source_table: string;
  rows: number;
  flagged_events: number;
}

export interface UnitVariation {
  event_subtype: string;
  unit_count: number;
  units: string[];
}

export interface QualitySummary {
  patient_id: string | null;
  total_events: number;
  total_flags: number;
  per_rule: RuleSummary[];
  per_table: TableCoverage[];
  unit_variation: UnitVariation[];
}

export interface EvalQuestion {
  qid: string;
  category: string;
  question: string;
  check: string;
  status: string;
  citations: number;
  latency_s: number;
  pass: boolean;
}

export interface EvalReport {
  patient_id: string;
  generated_at: string;
  passed: number;
  total: number;
  metrics: {
    fact: [number, number];
    order: [number, number];
    provenance: [number, number];
    abstention: [number, number];
  };
  questions: EvalQuestion[];
  latency: {
    all: { mean: number; p50: number; p95: number; max: number } | null;
    answered: { mean: number; p50: number; p95: number; max: number } | null;
  } | null;
}
