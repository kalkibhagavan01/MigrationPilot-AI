export type UserRole =
  | "IMPLEMENTATION_CONSULTANT"
  | "SENIOR_IMPLEMENTATION_CONSULTANT"
  | "HR_DATA_STEWARD"
  | "COMPENSATION_MANAGER"
  | "PAYROLL_MANAGER"
  | "SYSTEM_ADMIN";

export type MigrationStatus =
  | "CREATED"
  | "UPLOADING"
  | "PROFILING"
  | "MAPPING"
  | "CLEANING"
  | "RECONCILING"
  | "VALIDATING"
  | "WAITING_FOR_REVIEW"
  | "READY_TO_PUSH"
  | "PUSHING"
  | "COMPLETED"
  | "FAILED"
  | "BLOCKED"
  | "CANCELLED"
  | "ROLLED_BACK"
  | "PARTIALLY_COMPLETED";

export type MappingDecision =
  | "PROPOSED"
  | "AUTO_APPROVED"
  | "NEEDS_REVIEW"
  | "MANUALLY_APPROVED"
  | "MANUALLY_CORRECTED"
  | "REJECTED"
  | "BLOCKED";

export type ValidationStatus = "VALID" | "INVALID" | "NEEDS_REVIEW";
export type EscalationStatus = "OPEN" | "RESOLVED" | "REJECTED";

export interface User {
  id: string;
  username: string;
  role: UserRole;
}

export interface TokenResponse {
  access_token: string;
  token_type: "bearer";
  expires_in: number;
  user: User;
}

export interface MigrationSummary {
  id: string;
  status: MigrationStatus;
  current_node: string | null;
  target_schema_version: string;
  progress: {
    files: number;
    records: number;
    profiles: number;
  };
}

export interface CreateMigrationResponse {
  migration_id: string;
  status: MigrationStatus;
  profiles_created: number;
  files: Array<{
    id: string;
    name: string;
    size_bytes: number;
    row_count: number | null;
  }>;
}

export interface StartMigrationResponse {
  migration_id: string;
  status: MigrationStatus;
  current_node: string | null;
  mappings: number;
  records: number;
  open_reviews: number;
  pushed: number;
  failed: number;
}

export interface MappingItem {
  id: string;
  source_column: string;
  target_field: string | null;
  semantic_score: number;
  name_score: number;
  type_score: number;
  value_score: number;
  final_score: number;
  decision: MappingDecision;
  reasoning: string | null;
}

export interface GenerateMappingsResponse {
  migration_id: string;
  mappings: MappingItem[];
}

export interface CanonicalRecord {
  id: string;
  employee_id: string | null;
  validation_status: ValidationStatus;
  issues: Array<Record<string, unknown>>;
}

export interface MigrationRecord extends CanonicalRecord {
  data: Record<string, unknown>;
  push_status: string | null;
  target_record_id: string | null;
}

export interface CanonicalizeResponse {
  migration_id: string;
  records_created: number;
  valid_records: number;
  invalid_records: number;
  review_records: number;
  records: CanonicalRecord[];
}

export interface Escalation {
  id: string;
  migration_id: string;
  record_id: string | null;
  issue_type: string;
  severity: "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
  classification: string;
  required_role: UserRole;
  status: EscalationStatus;
  context: Record<string, unknown>;
  recommended_action: Record<string, unknown> | null;
}

export interface BuildEscalationsResponse {
  migration_id: string;
  created: number;
  open_blocking: number;
}

export interface PushResultItem {
  record_id: string;
  employee_id: string | null;
  status: string;
  target_record_id: string | null;
  attempts: number;
  http_status: number | null;
  error_code: string | null;
}

export interface PushMigrationResponse {
  migration_id: string;
  pushed: number;
  failed: number;
  results: PushResultItem[];
}

export interface RollbackMigrationResponse {
  migration_id: string;
  rolled_back: number;
  results: Array<{
    push_id: string;
    target_record_id: string | null;
    status: string;
  }>;
}

export interface PushPreviewRecord {
  record_id: string;
  employee_id: string | null;
  status: string;
  action: string;
  reason: string;
  data: Record<string, unknown>;
}

export interface PushPreviewResponse {
  migration_id: string;
  ready_count: number;
  blocked_count: number;
  records: PushPreviewRecord[];
}

export interface RollbackPreviewRecord {
  push_id: string;
  target_record_id: string;
  employee_id: string | null;
  action: string;
  data: Record<string, unknown>;
}

export interface RollbackPreviewResponse {
  migration_id: string;
  removable_count: number;
  records: RollbackPreviewRecord[];
}

export interface RunMetricsResponse {
  migration_id: string;
  readiness_score: number;
  agent_score: number;
  elapsed_seconds: number | null;
  stage_durations: Array<{ stage: string; seconds: number | null }>;
  total_records: number;
  canonical_records: number;
  valid_records: number;
  invalid_records: number;
  review_records: number;
  open_reviews: number;
  ready_to_push: number;
  blocked_from_push: number;
  pushed_records: number;
  failed_pushes: number;
  push_success_rate: number | null;
  autonomous_mappings: number;
  review_mappings: number;
  issue_counts: Record<string, number>;
  sensitive_fields_masked: string[];
  llm: {
    used: boolean;
    provider: string | null;
    model: string | null;
    prompt_tokens: number | null;
    completion_tokens: number | null;
    total_tokens: number | null;
  };
}

export interface AuditEvent {
  id: string;
  migration_id: string;
  actor_type: string;
  actor_id: string | null;
  event_type: string;
  entity_type: string;
  entity_id: string | null;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  reason: string | null;
  metadata: Record<string, unknown> | null;
  created_at: string;
}

export interface ActivityItem {
  id: string;
  time: string;
  message: string;
  event_type: string;
  details: Record<string, unknown> | null;
}

export interface OpsMetrics {
  migrations: number;
  audit_events: number;
  open_escalations: number;
  pushed_records: number;
  failed_pushes: number;
  kill_switch_enabled: boolean;
}

export interface KillSwitchStatus {
  enabled: boolean;
  reason: string | null;
}
