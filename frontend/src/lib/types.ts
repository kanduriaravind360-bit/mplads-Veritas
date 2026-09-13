/** Response shapes of the Sentinel API, as the backend returns them. */

export type Role = "MINISTRY" | "STATE" | "DISTRICT" | "MP";
export type Band = "Low" | "Medium" | "High" | "Critical";
export type AlertType = "high_risk_work" | "duplicate_group" | "split_work_group";

export interface User {
  id: number;
  email: string;
  name: string;
  role: Role;
  state: string | null;
  ida: string | null;
  mp_code: string | null;
  scope_label: string | null;
}

export interface Page<T> {
  total: number;
  limit: number;
  offset: number;
  items: T[];
}

export interface WorkSummary {
  work_id: string;
  source: string;
  state: string;
  district: string;
  ida: string;
  constituency: string | null;
  mp_name: string | null;
  chamber: string | null;
  work_type: string;
  work_status: string | null;
  work_description: string | null;
  vendor_name: string | null;
  sanction_date: string | null;
  completion_date: string | null;
  sanction_amount: number;
  total_fund_disbursed: number | null;
  risk_score: number;
  band: Band;
  is_open: boolean;
  delay_risk: number;
  severe_floor_applied: boolean;
  top_reason_en: string | null;
  top_reason_hi: string | null;
}

export type Signals = Record<"rule" | "supervised" | "unsupervised" | "cost" | "duplicate" | "delay", number>;

export interface WorkDetail extends WorkSummary {
  recommended_date: string | null;
  latest_expenditure_date: string | null;
  num_payments: number | null;
  latest_payment_status: string | null;
  days_to_sanction: number | null;
  days_since_sanction: number | null;
  duration_days: number | null;
  base_risk_score: number;
  severe_rule_count: number;
  signals: Signals;
  cost: {
    channel: string | null;
    ratio: number | null;
    expected_amount: number | null;
    state_peer_label: string | null;
    state_peer_median: number | null;
    state_cost_ratio: number | null;
    state_channel_in_score: boolean;
  };
  dup_score: number;
  split_score: number;
  rule_score: number;
  reasons_en: string[];
  reasons_hi: string[];
  rules: Record<string, boolean>;
  severe_rules: Record<string, boolean>;
  attributions: Record<string, [string, number][]>;
  context: Record<string, number | string | boolean | null>;
  scored_at: string | null;
  alerts: AlertSummary[];
  similar_works: {
    pair_id: number;
    work_id: string;
    work_description: string | null;
    sanction_amount: number;
    sanction_date: string | null;
    pair_score: number;
    decision: string | null;
  }[];
  audit: AuditEvent[];
  data_completeness: { field: string; label: string; present: boolean; applicable: boolean }[];
}

export interface Percentiles {
  n: number;
  p10: number;
  p25: number;
  median: number;
  p75: number;
  p90: number;
}

export interface Peers {
  work_id: string;
  work_type: string;
  state: string;
  amount: number;
  expected_amount: number | null;
  state_peers: Percentiles | null;
  national_peers: Percentiles | null;
  ratio_to_state_median: number | null;
  note: string;
}

export interface AlertSummary {
  alert_id: string;
  alert_type: AlertType;
  severity: Band;
  risk_score: number;
  amount: number;
  n_works: number;
  state: string;
  district: string;
  ida: string;
  constituency: string | null;
  work_type: string | null;
  status: string;
  level: string;
  assignee: string | null;
  raised_at: string;
  updated_at: string;
  escalated_at: string | null;
  source: string;
  is_active: boolean;
  top_reason_en: string | null;
  top_reason_hi: string | null;
}

export interface AuditEvent {
  seq: number;
  ts: string;
  actor: string;
  action: string;
  entity_type: string;
  entity_id: string;
  payload: Record<string, unknown>;
  hash: string;
  prev_hash: string;
}

export interface AlertDetail extends AlertSummary {
  reasons_en: string[];
  reasons_hi: string[];
  evidence: Record<string, unknown>;
  work_ids: string[];
  works: WorkSummary[];
  work: WorkDetail | null;
  allowed_transitions: string[];
  comments: { id: number; author: string; body: string; created_at: string }[];
  feedback: { verdict: string; note: string | null; work_id: string | null; is_seed: boolean; created_at: string }[];
  audit: AuditEvent[];
  suggested_action: string | null;
}

export interface AlertsSummary {
  by_severity: Partial<Record<Band, number>>;
  by_status: Record<string, number>;
  by_type: Partial<Record<AlertType, number>>;
  by_level: Record<string, number>;
  amount_by_severity: Partial<Record<Band, number>>;
}

export interface GroupRow {
  key: string;
  state: string;
  works: number;
  sanctioned: number;
  disbursed: number;
  money_at_risk: number;
  high_or_critical: number;
  high_or_critical_share: number;
  mean_risk: number;
  mean_delay_risk: number | null;
  completion_rate: number;
  utilisation: number;
  low_volume: boolean;
}

export interface Kpis {
  works: number;
  sanctioned: number;
  disbursed: number;
  completed: number;
  completion_rate: number;
  utilisation: number;
  high_or_critical: number;
  money_at_risk: number;
  money_at_risk_share: number;
  mps: number;
  districts: number;
  mean_risk: number;
}

export interface BandRow {
  band: Band;
  works: number;
  amount: number;
}

export interface MonthRow {
  month: string;
  works: number;
  amount: number;
  is_march: boolean;
}

export interface Overview {
  scope: string;
  role: Role;
  kpis: Kpis;
  fund_flow: { stage: string; amount: number; estimate: boolean; note?: string }[];
  bands: BandRow[];
  alerts: { by_severity: Partial<Record<Band, number>>; by_status: Record<string, number> };
  top_districts: GroupRow[];
  top_vendors: GroupRow[];
  what_changed: {
    data_cutoff: string;
    window: string;
    works_sanctioned: number;
    amount_sanctioned: number;
    works_completed: number;
    new_high_or_critical: number;
    last_scoring_run: {
      kind: string;
      finished_at: string | null;
      alerts_new: number;
      alerts_retired: number;
      message: string;
    } | null;
    note: string;
  };
  framing: string;
}

export interface ModelsSummary {
  per_detector: {
    detector: string;
    fired: number;
    queue_size: number;
    recall_at_top_1pct: number;
    recall_at_top_5pct: number;
    recall_at_top_10pct: number;
    precision_at_top_5pct: number;
  }[];
  global_rank_recall: Record<string, Record<string, number>>;
  before_after: Record<string, { before_step2b: number; after_step2b: number; change: number; target: number; target_met: boolean }>;
  delay_model: {
    train: { roc_auc: number; pr_auc: number };
    holdout: { n_labelled: number; delay_rate: number; roc_auc: number; pr_auc: number };
  };
  proxy_model: { pr_auc_oof: number; roc_auc_oof: number; caveat: string | null };
  holdout_bands: Record<"train" | "holdout", { counts: Record<Band, number>; shares: Record<Band, number>; n: number }>;
  holdout_size: { works: number; constituencies: number };
  severe_floor: { works_lifted: number; works_changing_band: number; bands_before_floor: Record<Band, number> };
  cost_state_channel: Record<string, unknown>;
  band_cutoffs: Record<"critical" | "high" | "medium", number>;
  weights: Record<string, number>;
  weak_spot: string;
  caveats: string[];
  explanations: Record<string, string>;
  thresholds: { high_delay_risk: number };
}

export interface SearchResult {
  works: Pick<WorkSummary, "work_id" | "work_description" | "district" | "state" | "band" | "risk_score" | "sanction_amount">[];
  alerts: Pick<AlertSummary, "alert_id" | "alert_type" | "severity" | "district" | "amount" | "status">[];
  districts: { district: string; state: string; works: number }[];
}

export interface GeoDistrictRow extends GroupRow {
  district: string;
  map_key: string;
  value: number | null;
}
