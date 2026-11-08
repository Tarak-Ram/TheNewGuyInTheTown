// TypeScript mirror of packages/schemas/py/nguit_schemas. Keep both in sync.

export interface HealthResponse {
  status: "ok";
  service: string;
}

export interface ReadyResponse {
  status: "ready" | "not_ready";
  service: string;
  database: "up" | "down" | "not_configured";
  calling_enabled: boolean;
}

export interface Needs {
  food: "veg" | "non_veg" | "any";
  commute_mode: "bike" | "car" | "public" | "any";
  pg_gender: "men" | "women" | "any";
}

export interface PlanCreate {
  office_address: string;
  office_lat: number;
  office_lng: number;
  budget_min: number;
  budget_max: number;
  arrival_date: string; // YYYY-MM-DD
  needs: Needs;
}

export interface PlanOut extends PlanCreate {
  id: string;
  status: string;
}

export interface UserOut {
  id: string;
  email: string;
  language: string;
}

export interface SessionResponse {
  access_token: string;
  user: UserOut;
}

export interface AreaOption {
  area_id: string;
  name: string;
  commute_minutes: number;
  rent_min: number;
  rent_max: number;
  rent_source: string;
  rent_updated_at: string;
  score: number;
  reason: string;
  budget_gap: number;
  confirmed_pgs: number;
  components?: Record<string, number> | null;
}

export interface RankResponse {
  plan_id: string;
  areas: AreaOption[];
  skipped_areas: string[];
  explanation_source: "model" | "template" | null;
  commute_basis: string;
  over_budget_all: boolean;
}

export interface PgOut {
  id: string;
  name: string;
  area_id: string;
  area_name: string;
}

export interface FieldCell {
  value: number | string | null;
  confirmed: boolean;
  display: string;
  transcript_offset: number | null;
  quote: string | null;
}

export interface ComparisonRow {
  pg_id: string;
  pg_name: string;
  area_name: string;
  call_id: string;
  call_status: string;
  provider: string;
  facts_checked: boolean;
  fields: Record<string, FieldCell>;
}

export interface ComparisonOut {
  plan_id: string;
  field_order: string[];
  rows: ComparisonRow[];
}

export interface AgreementCreated {
  id: string;
  upload_url: string;
  expires_in: number;
  max_bytes: number;
  allowed_types: string[];
}

export interface RiskOut {
  type: string;
  severity: "high" | "medium" | "low";
  page: number | null;
  quote: string;
  quote_translation: string | null;
  explanation: string;
  question_to_ask: string;
  source: "model" | "rules";
}

export interface ReportOut {
  id: string;
  status: string;
  message: string | null;
  disclaimer: string;
  filename: string | null;
  pages: number | null;
  text_source: string | null;
  language: string | null;
  injection_detected: boolean;
  warnings: string[];
  risk_counts: Record<string, number>;
  risks: RiskOut[];
  created_at: string | null;
}
