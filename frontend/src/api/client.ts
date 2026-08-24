import type {
  AuditEvent,
  ActivityItem,
  BuildEscalationsResponse,
  CanonicalizeResponse,
  CreateMigrationResponse,
  Escalation,
  GenerateMappingsResponse,
  KillSwitchStatus,
  MigrationRecord,
  MigrationSummary,
  OpsMetrics,
  PushPreviewResponse,
  PushMigrationResponse,
  RollbackPreviewResponse,
  RollbackMigrationResponse,
  RunMetricsResponse,
  StartMigrationResponse,
  TokenResponse
} from "../types";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000/api/v1";

export class ApiError extends Error {
  code: string;

  constructor(code: string, message: string) {
    super(message);
    this.code = code;
  }
}

export async function login(username: string, password: string): Promise<TokenResponse> {
  return request<TokenResponse>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
    headers: { "Content-Type": "application/json" }
  });
}

export async function createMigration(
  token: string,
  files: File[]
): Promise<CreateMigrationResponse> {
  const form = new FormData();
  files.forEach((file) => form.append("files", file));
  form.append("target_schema_version", "employee-v1");
  return request<CreateMigrationResponse>("/migrations", {
    method: "POST",
    token,
    body: form
  });
}

export async function getMigration(token: string, id: string): Promise<MigrationSummary> {
  return request<MigrationSummary>(`/migrations/${id}`, { token });
}

export async function startMigration(
  token: string,
  id: string
): Promise<StartMigrationResponse> {
  return request<StartMigrationResponse>(`/migrations/${id}/start`, {
    method: "POST",
    token
  });
}

export async function generateMappings(
  token: string,
  id: string
): Promise<GenerateMappingsResponse> {
  return request<GenerateMappingsResponse>(`/migrations/${id}/mappings`, {
    method: "POST",
    token
  });
}

export async function canonicalize(
  token: string,
  id: string
): Promise<CanonicalizeResponse> {
  return request<CanonicalizeResponse>(`/migrations/${id}/canonicalize`, {
    method: "POST",
    token
  });
}

export async function buildEscalations(
  token: string,
  id: string
): Promise<BuildEscalationsResponse> {
  return request<BuildEscalationsResponse>(`/migrations/${id}/escalations/build`, {
    method: "POST",
    token
  });
}

export async function listEscalations(token: string, id: string): Promise<Escalation[]> {
  return request<Escalation[]>(`/migrations/${id}/escalations`, { token });
}

export async function resolveEscalation(
  token: string,
  escalationId: string,
  action: "APPROVE" | "CORRECT" | "REJECT" | "SEND_TO_HR",
  resolution: Record<string, unknown> = { action },
  comment = "Resolved from UI"
): Promise<Escalation> {
  return request<Escalation>(`/escalations/${escalationId}/resolve`, {
    method: "POST",
    token,
    body: JSON.stringify({ action, resolution, comment }),
    headers: { "Content-Type": "application/json" }
  });
}

export async function pushMigration(token: string, id: string): Promise<PushMigrationResponse> {
  return request<PushMigrationResponse>(`/migrations/${id}/push`, {
    method: "POST",
    token
  });
}

export async function retryFailedMigration(
  token: string,
  id: string
): Promise<PushMigrationResponse> {
  return request<PushMigrationResponse>(`/migrations/${id}/retry-failed`, {
    method: "POST",
    token
  });
}

export async function rollbackMigration(
  token: string,
  id: string
): Promise<RollbackMigrationResponse> {
  return request<RollbackMigrationResponse>(`/migrations/${id}/rollback`, {
    method: "POST",
    token
  });
}

export async function getPushPreview(token: string, id: string): Promise<PushPreviewResponse> {
  return request<PushPreviewResponse>(`/migrations/${id}/push-preview`, { token });
}

export async function getRollbackPreview(token: string, id: string): Promise<RollbackPreviewResponse> {
  return request<RollbackPreviewResponse>(`/migrations/${id}/rollback-preview`, { token });
}

export async function getRunMetrics(token: string, id: string): Promise<RunMetricsResponse> {
  return request<RunMetricsResponse>(`/migrations/${id}/run-metrics`, { token });
}

export async function listAuditEvents(token: string, id: string): Promise<AuditEvent[]> {
  return request<AuditEvent[]>(`/migrations/${id}/audit-events`, { token });
}

export async function listRecords(token: string, id: string): Promise<MigrationRecord[]> {
  return request<MigrationRecord[]>(`/migrations/${id}/records`, { token });
}

export async function listActivity(token: string, id: string): Promise<ActivityItem[]> {
  return request<ActivityItem[]>(`/migrations/${id}/activity`, { token });
}

export async function getOpsMetrics(token: string): Promise<OpsMetrics> {
  return request<OpsMetrics>("/ops/metrics", { token });
}

export async function getKillSwitch(token: string): Promise<KillSwitchStatus> {
  return request<KillSwitchStatus>("/ops/kill-switch", { token });
}

export async function updateKillSwitch(
  token: string,
  enabled: boolean,
  reason: string | null
): Promise<KillSwitchStatus> {
  return request<KillSwitchStatus>("/ops/kill-switch", {
    method: "PUT",
    token,
    body: JSON.stringify({ enabled, reason }),
    headers: { "Content-Type": "application/json" }
  });
}

export function eventUrl(id: string): string {
  return `${API_BASE}/migrations/${id}/events`;
}

async function request<T>(
  path: string,
  options: RequestInit & { token?: string } = {}
): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.token && options.token !== "demo-no-auth") {
    headers.set("Authorization", `Bearer ${options.token}`);
  }
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, { ...options, headers });
  } catch (caught) {
    const message = caught instanceof Error ? caught.message : "Network request failed";
    throw new ApiError("NETWORK_ERROR", message);
  }
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as
      | { error?: { code?: string; message?: string } }
      | null;
    throw new ApiError(
      payload?.error?.code ?? "REQUEST_FAILED",
      payload?.error?.message ?? "Request failed"
    );
  }
  return response.json() as Promise<T>;
}
