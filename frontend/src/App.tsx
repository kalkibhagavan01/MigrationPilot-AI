import {
  Bell,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Command,
  DatabaseZap,
  FileCode2,
  GitCompare,
  Info,
  LayoutDashboard,
  ListChecks,
  Loader2,
  Play,
  Search,
  Settings,
  ShieldCheck,
  TerminalSquare,
  UploadCloud,
  Workflow,
  XCircle
} from "lucide-react";
import { ChangeEvent, useEffect, useMemo, useState } from "react";

import {
  ApiError,
  buildEscalations,
  canonicalize,
  createMigration,
  generateMappings,
  getKillSwitch,
  getMigration,
  getOpsMetrics,
  getPushPreview,
  getRollbackPreview,
  getRunMetrics,
  listActivity,
  listAuditEvents,
  listEscalations,
  listRecords,
  pushMigration,
  retryFailedMigration,
  rollbackMigration,
  resolveEscalation,
  startMigration,
  updateKillSwitch
} from "./api/client";
import { useMigrationEvents } from "./hooks/useMigrationEvents";
import type {
  ActivityItem,
  AuditEvent,
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
  User
} from "./types";

type ThemePreference = "light" | "dark" | "system";
type WorkspaceTab = "overview" | "mappings" | "validation" | "review" | "push" | "audit" | "ops" | "logs";

const navItems = [
  { id: "overview", label: "Overview", icon: LayoutDashboard },
  { id: "source", label: "Source Analysis", icon: FileCode2 },
  { id: "plan", label: "Migration Plan", icon: Workflow },
  { id: "mappings", label: "Mappings", icon: GitCompare },
  { id: "validation", label: "Validation", icon: ListChecks },
  { id: "review", label: "AI Review", icon: ShieldCheck },
  { id: "push", label: "Push Results", icon: Play },
  { id: "audit", label: "Audit", icon: FileCode2 },
  { id: "ops", label: "Ops", icon: Settings },
  { id: "logs", label: "Logs", icon: TerminalSquare },
  { id: "settings", label: "Settings", icon: Settings }
] as const;

const DEMO_TOKEN = "demo-no-auth";
const DEMO_USER: User = {
  id: "demo-admin",
  username: "demo_admin",
  role: "SYSTEM_ADMIN"
};

export default function App() {
  const [theme, setTheme] = useState<ThemePreference>(() => {
    return (localStorage.getItem("theme") as ThemePreference | null) ?? "system";
  });
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [commandOpen, setCommandOpen] = useState(false);
  const [activeTab, setActiveTab] = useState<WorkspaceTab>("overview");
  const [token] = useState<string>(DEMO_TOKEN);
  const [user] = useState<User>(DEMO_USER);
  const [files, setFiles] = useState<File[]>([]);
  const [migration, setMigration] = useState<MigrationSummary | null>(null);
  const [uploadResult, setUploadResult] = useState<CreateMigrationResponse | null>(null);
  const [mappingResult, setMappingResult] = useState<GenerateMappingsResponse | null>(null);
  const [canonicalResult, setCanonicalResult] = useState<CanonicalizeResponse | null>(null);
  const [escalations, setEscalations] = useState<Escalation[]>([]);
  const [resolvedEscalations, setResolvedEscalations] = useState<Escalation[]>([]);
  const [reviewIndex, setReviewIndex] = useState(0);
  const [pushResult, setPushResult] = useState<PushMigrationResponse | null>(null);
  const [rollbackResult, setRollbackResult] = useState<RollbackMigrationResponse | null>(null);
  const [pushPreview, setPushPreview] = useState<PushPreviewResponse | null>(null);
  const [rollbackPreview, setRollbackPreview] = useState<RollbackPreviewResponse | null>(null);
  const [runMetrics, setRunMetrics] = useState<RunMetricsResponse | null>(null);
  const [auditEvents, setAuditEvents] = useState<AuditEvent[]>([]);
  const [records, setRecords] = useState<MigrationRecord[]>([]);
  const [activity, setActivity] = useState<ActivityItem[]>([]);
  const [opsMetrics, setOpsMetrics] = useState<OpsMetrics | null>(null);
  const [killSwitch, setKillSwitch] = useState<KillSwitchStatus | null>(null);
  const [logs, setLogs] = useState<string[]>(["12:00:00 INFO   Workspace initialized"]);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const events = useMigrationEvents(token, migration?.id ?? null);

  useEffect(() => {
    localStorage.removeItem("token");
    localStorage.removeItem("user");
    localStorage.setItem("theme", theme);
    const root = document.documentElement;
    const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
    root.dataset.theme = theme === "system" ? (prefersDark ? "dark" : "light") : theme;
  }, [theme]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setCommandOpen((open) => !open);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  const progress = useMemo(() => {
    if (!migration) {
      return 0;
    }
    if (migration.status === "BLOCKED" && runMetrics && runMetrics.open_reviews === 0) {
      return 100;
    }
    const statusWeights: Record<string, number> = {
      PROFILING: 22,
      MAPPING: 45,
      BLOCKED: 45,
      VALIDATING: 68,
      WAITING_FOR_REVIEW: 78,
      READY_TO_PUSH: 88,
      PUSHING: 92,
      PARTIALLY_COMPLETED: 96,
      ROLLED_BACK: 100,
      COMPLETED: 100
    };
    return statusWeights[migration.status] ?? 10;
  }, [migration, runMetrics]);

  async function runAction<T>(label: string, action: () => Promise<T>): Promise<T | null> {
    setBusy(label);
    setError(null);
    try {
      const result = await action();
      addLog(`INFO   ${label} completed`);
      return result;
    } catch (caught) {
      const message = caught instanceof ApiError
        ? friendlyError(caught)
        : caught instanceof Error
          ? caught.message
          : "Action failed";
      setError(message);
      addLog(`ERROR  ${label} failed: ${caught instanceof ApiError ? `${caught.code}: ${caught.message}` : message}`);
      return null;
    } finally {
      setBusy(null);
    }
  }

  function friendlyError(error: ApiError): string {
    const messages: Record<string, string> = {
      NETWORK_ERROR: "Could not reach the backend. Check that the API server is running.",
      NO_FILES: "Select at least one CSV or Excel file before starting.",
      UNSUPPORTED_FILE_TYPE: "Only CSV and XLSX files are supported for this demo.",
      INVALID_WORKBOOK: "One uploaded file could not be read. Please check the file format.",
      UNRESOLVED_BLOCKING_ESCALATIONS: "Resolve the open review items before pushing records.",
      RECORDS_NOT_VALID: "No validated records are ready to push yet.",
      MAPPING_TARGET_MISSING: "Choose a target field before approving this mapping.",
      INVALID_TARGET_FIELD: "Choose a target field from the target schema.",
      ESCALATION_ALREADY_RESOLVED: "This review item was already resolved.",
      KILL_SWITCH_ENABLED: "Migration actions are paused by the kill switch.",
    };
    return messages[error.code] ?? error.message;
  }

  function handleFiles(event: ChangeEvent<HTMLInputElement>) {
    setFiles(Array.from(event.target.files ?? []));
  }

  async function handleUpload() {
    if (!token || files.length === 0) {
      setError("Select at least one CSV or XLSX file.");
      return;
    }
    const result = await runAction("Upload and profile", () => createMigration(token, files));
    if (!result) {
      return;
    }
    setUploadResult(result);
    await refreshMigration(result.migration_id);
  }

  async function handleStartProcessing() {
    if (!token || files.length === 0) {
      setError("Select at least one CSV or XLSX file.");
      return;
    }

    const upload = await runAction("Upload and profile", () => createMigration(token, files));
    if (!upload) {
      return;
    }
    setUploadResult(upload);
    setResolvedEscalations([]);
    setReviewIndex(0);

    const started = await runAction("Start migration workflow", () =>
      startMigration(token, upload.migration_id)
    );
    if (!started) {
      return;
    }

    await refreshWorkspace(upload.migration_id);
    const reviewItems = await runAction("Load review queue", () =>
      listEscalations(token, upload.migration_id)
    );
    if (reviewItems) {
      setEscalations(reviewItems);
    }

    if ((started.open_reviews ?? reviewItems?.length ?? 0) > 0) {
      setActiveTab("review");
      return;
    }

    if (started.pushed > 0 || started.failed > 0) {
      setActiveTab("push");
    } else {
      setActiveTab("overview");
    }
  }

  async function refreshMigration(id = migration?.id ?? uploadResult?.migration_id) {
    if (!token || !id) {
      return null;
    }
    const result = await runAction("Refresh migration", () => getMigration(token, id));
    if (result) {
      setMigration(result);
    }
    return result;
  }

  async function refreshWorkspace(id: string) {
    if (!token) {
      return null;
    }
    const refreshedMigration = await refreshMigration(id);
    const [mappings, loadedRecords, loadedActivity, audit, preview, rollbackPlan, metrics] = await Promise.all([
      runAction("Load mappings", () => generateMappings(token, id)),
      runAction("Load records", () => listRecords(token, id)),
      runAction("Load activity", () => listActivity(token, id)),
      runAction("Load audit timeline", () => listAuditEvents(token, id)),
      runAction("Load push preview", () => getPushPreview(token, id)),
      runAction("Load rollback preview", () => getRollbackPreview(token, id)),
      runAction("Load run metrics", () => getRunMetrics(token, id)),
    ]);
    if (mappings) {
      setMappingResult(mappings);
    }
    if (loadedRecords) {
      setRecords(loadedRecords);
      setCanonicalResult({
        migration_id: id,
        records_created: loadedRecords.length,
        valid_records: loadedRecords.filter((record) => record.validation_status === "VALID").length,
        invalid_records: loadedRecords.filter((record) => record.validation_status === "INVALID").length,
        review_records: loadedRecords.filter((record) => record.validation_status === "NEEDS_REVIEW").length,
        records: loadedRecords,
      });
    }
    if (loadedActivity) {
      setActivity(loadedActivity);
    }
    if (audit) {
      setAuditEvents(audit);
    }
    if (preview) {
      setPushPreview(preview);
    }
    if (rollbackPlan) {
      setRollbackPreview(rollbackPlan);
    }
    if (metrics) {
      setRunMetrics(metrics);
    }
    return refreshedMigration;
  }

  async function handleMappings() {
    if (!token || !migration) {
      return;
    }
    const result = await runAction("Generate mappings", () => generateMappings(token, migration.id));
    if (result) {
      setMappingResult(result);
      await refreshMigration(migration.id);
      setActiveTab("mappings");
    }
  }

  async function handleCanonicalize() {
    if (!token || !migration) {
      return;
    }
    const result = await runAction("Canonicalize and validate", () => canonicalize(token, migration.id));
    if (result) {
      setCanonicalResult(result);
      await refreshMigration(migration.id);
      setActiveTab("validation");
    }
  }

  async function handleBuildEscalations() {
    if (!token || !migration) {
      return;
    }
    await runAction("Build review queue", () => buildEscalations(token, migration.id));
    const result = await runAction("Load review queue", () => listEscalations(token, migration.id));
    if (result) {
      setEscalations(result);
      setReviewIndex(0);
      await refreshMigration(migration.id);
      setActiveTab("review");
    }
  }

  async function handleResolve(
    escalationId: string,
    action: "APPROVE" | "CORRECT" | "REJECT" | "SEND_TO_HR",
    resolution: Record<string, unknown> = { action }
  ) {
    if (!token || !migration) {
      return;
    }
    const resolved = await runAction("Resolve escalation", () =>
      resolveEscalation(token, escalationId, action, resolution)
    );
    if (!resolved) {
      return;
    }
    setResolvedEscalations((items) => [
      ...items.filter((item) => item.id !== resolved.id),
      resolved,
    ]);
    const next = await runAction("Reload review queue", () => listEscalations(token, migration.id));
    if (next) {
      setEscalations(next);
      const resolvedCountAfter = resolvedEscalations.some((item) => item.id === resolved.id)
        ? resolvedEscalations.length
        : resolvedEscalations.length + 1;
      setReviewIndex(next.length > 0 ? resolvedCountAfter : Math.max(resolvedCountAfter - 1, 0));
      if (next.length === 0 && action !== "SEND_TO_HR") {
        const refreshed = await refreshWorkspace(migration.id);
        setActiveTab(
          refreshed && ["COMPLETED", "PARTIALLY_COMPLETED", "PUSHING"].includes(refreshed.status)
            ? "push"
            : "validation"
        );
      } else {
        await refreshWorkspace(migration.id);
        setActiveTab("review");
      }
    }
  }

  async function handlePush() {
    if (!token || !migration) {
      return;
    }
    const result = await runAction("Push to mock target", () => pushMigration(token, migration.id));
    if (result) {
      setPushResult(result);
      setRollbackResult(null);
      await refreshWorkspace(migration.id);
      setActiveTab("push");
    }
  }

  async function handleRetryFailed() {
    if (!token || !migration) {
      return;
    }
    const result = await runAction("Retry failed records", () =>
      retryFailedMigration(token, migration.id)
    );
    if (result) {
      setPushResult(result);
      await refreshWorkspace(migration.id);
      setActiveTab("push");
    }
  }

  async function handleRollback() {
    if (!token || !migration) {
      return;
    }
    const result = await runAction("Rollback mock target", () => rollbackMigration(token, migration.id));
    if (result) {
      setRollbackResult(result);
      await refreshWorkspace(migration.id);
      setActiveTab("push");
    }
  }

  async function handleLoadAudit() {
    if (!token || !migration) {
      return;
    }
    const result = await runAction("Load audit timeline", () => listAuditEvents(token, migration.id));
    if (result) {
      setAuditEvents(result);
      setActiveTab("audit");
    }
  }

  async function handleLoadOps() {
    if (!token) {
      return;
    }
    const [metrics, status] = await Promise.all([
      runAction("Load ops metrics", () => getOpsMetrics(token)),
      runAction("Load kill switch", () => getKillSwitch(token)),
    ]);
    if (metrics) {
      setOpsMetrics(metrics);
    }
    if (status) {
      setKillSwitch(status);
    }
    setActiveTab("ops");
  }

  async function handleToggleKillSwitch(enabled: boolean) {
    if (!token) {
      return;
    }
    const reason = enabled ? "Activated from local ops panel" : null;
    const status = await runAction("Update kill switch", () =>
      updateKillSwitch(token, enabled, reason)
    );
    if (status) {
      setKillSwitch(status);
      await handleLoadOps();
    }
  }

  function addLog(line: string) {
    const timestamp = new Date().toLocaleTimeString("en-US", { hour12: false });
    setLogs((current) => [`${timestamp} ${line}`, ...current].slice(0, 18));
  }

  return (
    <main className="workspace">
      <TopBar
        user={user}
        theme={theme}
        setTheme={setTheme}
        openCommand={() => setCommandOpen(true)}
      />
      <aside className={`sidebar ${sidebarCollapsed ? "collapsed" : ""}`}>
        <button
          className="icon-button collapse"
          aria-label="Toggle sidebar"
          onClick={() => setSidebarCollapsed((value) => !value)}
        >
          {sidebarCollapsed ? <ChevronRight size={16} /> : <ChevronLeft size={16} />}
        </button>
        {navItems.map((item) => {
          const Icon = item.icon;
          const isActive = item.id === activeTab;
          return (
            <button
              key={item.id}
              className={`nav-item ${isActive ? "active" : ""}`}
              title={item.label}
              onClick={() => {
                if (["overview", "mappings", "validation", "review", "push", "audit", "ops", "logs"].includes(item.id)) {
                  setActiveTab(item.id as WorkspaceTab);
                }
              }}
            >
              <Icon size={16} />
              <span>{item.label}</span>
            </button>
          );
        })}
      </aside>
      <section className="main-pane">
        <ContextHeader
          migration={migration}
          progress={progress}
          busy={busy}
          onRollback={handleRollback}
          onAudit={handleLoadAudit}
          onOps={handleLoadOps}
        />
        <div className="content-grid">
          <section className="primary-surface">
            <UploadStrip
              files={files}
              busy={busy}
              onFiles={handleFiles}
              onStart={handleStartProcessing}
              uploadResult={uploadResult}
            />
            <Tabs activeTab={activeTab} setActiveTab={setActiveTab} />
            {activeTab === "overview" && (
              <Overview
                migration={migration}
                uploadResult={uploadResult}
                mappingResult={mappingResult}
                canonicalResult={canonicalResult}
                records={records}
                events={events}
                runMetrics={runMetrics}
                pushPreview={pushPreview}
              />
            )}
            {activeTab === "mappings" && <MappingTable mappingResult={mappingResult} />}
            {activeTab === "validation" && <ValidationTable result={canonicalResult} />}
            {activeTab === "review" && (
              <ReviewQueue
                escalations={[...resolvedEscalations, ...escalations.filter((item) => !resolvedEscalations.some((resolved) => resolved.id === item.id))]}
                migration={migration}
                records={records}
                reviewIndex={reviewIndex}
                setReviewIndex={setReviewIndex}
                onResolve={handleResolve}
                onContinue={handlePush}
              />
            )}
            {activeTab === "push" && (
              <PushResults
                pushResult={pushResult}
                rollbackResult={rollbackResult}
                records={records}
                migration={migration}
                pushPreview={pushPreview}
                rollbackPreview={rollbackPreview}
                onRetryFailed={handleRetryFailed}
              />
            )}
            {activeTab === "audit" && <AuditTimeline events={auditEvents} />}
            {activeTab === "ops" && (
              <OpsPanel
                metrics={opsMetrics}
                killSwitch={killSwitch}
                isAdmin={user.role === "SYSTEM_ADMIN"}
                onToggleKillSwitch={handleToggleKillSwitch}
              />
            )}
            {activeTab === "logs" && <LogViewer logs={logs} />}
          </section>
          <aside className="detail-panel">
            <AgentActivity migration={migration} busy={busy} activity={activity} />
            {error && <div className="error-card">{error}</div>}
          </aside>
        </div>
      </section>
      {commandOpen && (
        <CommandPalette
          close={() => setCommandOpen(false)}
          setTheme={setTheme}
          setSidebarCollapsed={setSidebarCollapsed}
          setActiveTab={setActiveTab}
        />
      )}
    </main>
  );
}

function TopBar({
  user,
  theme,
  setTheme,
  openCommand
}: {
  user: User;
  theme: ThemePreference;
  setTheme: (theme: ThemePreference) => void;
  openCommand: () => void;
}) {
  return (
    <header className="topbar">
      <div className="product-chip">
        <DatabaseZap size={18} />
        <span>MigrationPilot AI</span>
      </div>
      <span className="env-pill">local</span>
      <button className="search-box" onClick={openCommand}>
        <Search size={15} />
        Search or run command
        <kbd>⌘K</kbd>
      </button>
      <button className="icon-button" aria-label="Notifications">
        <Bell size={16} />
      </button>
      <select
        className="theme-select"
        value={theme}
        aria-label="Theme"
        onChange={(event) => setTheme(event.target.value as ThemePreference)}
      >
        <option value="light">☀ Light</option>
        <option value="dark">☾ Dark</option>
        <option value="system">◐ System</option>
      </select>
      <div className="user-menu">
        <span>{user.username}</span>
        <code>{user.role}</code>
      </div>
    </header>
  );
}

function ContextHeader({
  migration,
  progress,
  busy,
  onRollback,
  onAudit,
  onOps
}: {
  migration: MigrationSummary | null;
  progress: number;
  busy: string | null;
  onRollback: () => void;
  onAudit: () => void;
  onOps: () => void;
}) {
  return (
    <header className="context-header">
      <div>
        <div className="breadcrumbs">Workspace / HR Employee Migration</div>
        <h1>Employee data migration run</h1>
        <div className="meta-row">
          <code>{migration?.id ?? "no migration selected"}</code>
          <StatusBadge status={progressStatusLabel(migration, progress, busy)} />
          {busy && (
            <span className="agent-presence">
              <Workflow size={13} />
              Agent running
            </span>
          )}
          <span className="progress-summary">
            {progress}% complete
          </span>
        </div>
      </div>
      <div className="header-actions">
        <button className="secondary-button" onClick={onRollback} disabled={!migration || busy !== null}>
          <XCircle size={15} />
          Rollback
        </button>
        <button className="secondary-button" onClick={onAudit} disabled={!migration || busy !== null}>
          <FileCode2 size={15} />
          Audit
        </button>
        <button className="secondary-button" onClick={onOps} disabled={busy !== null}>
          <Settings size={15} />
          Ops
        </button>
      </div>
      <div className="progress-track">
        <div style={{ width: `${progress}%` }} />
      </div>
    </header>
  );
}

function UploadStrip({
  files,
  busy,
  onFiles,
  onStart,
  uploadResult
}: {
  files: File[];
  busy: string | null;
  onFiles: (event: ChangeEvent<HTMLInputElement>) => void;
  onStart: () => void;
  uploadResult: CreateMigrationResponse | null;
}) {
  return (
    <div className="upload-strip">
      <label className="file-input">
        <UploadCloud size={16} />
        Select CSV/XLSX exports
        <input type="file" multiple accept=".csv,.xlsx" onChange={onFiles} />
      </label>
      <div className="selected-files">
        {files.length === 0 ? (
          <span>No files selected</span>
        ) : (
          files.map((file) => (
            <span className="selected-file" key={file.name} title={file.name}>
              {file.name}
            </span>
          ))
        )}
      </div>
      <button className="primary-button upload-start-button" onClick={onStart} disabled={files.length === 0 || busy !== null}>
        {busy ? <Loader2 size={15} className="spin" /> : <Play size={15} />}
        Start processing
      </button>
      {uploadResult && <StatusBadge status={`${uploadResult.files.length} files profiled`} />}
    </div>
  );
}

function Tabs({
  activeTab,
  setActiveTab
}: {
  activeTab: WorkspaceTab;
  setActiveTab: (tab: WorkspaceTab) => void;
}) {
  const tabs: Array<{ id: WorkspaceTab; hint: string }> = [
    { id: "overview", hint: "High-level status, counts, and what the operator should do next." },
    { id: "mappings", hint: "How source columns were matched to target employee fields." },
    { id: "validation", hint: "Canonical employee records and whether they can be pushed." },
    { id: "review", hint: "Human decisions needed before the agent can continue." },
    { id: "push", hint: "Target push results, retry status, and rollback output." },
    { id: "audit", hint: "Readable trail of what changed, who acted, and why." },
    { id: "ops", hint: "Operational controls such as kill switch and system counts." },
    { id: "logs", hint: "Local action log from this UI session." },
  ];
  return (
    <nav className="tabs" aria-label="Migration workspace tabs">
      {tabs.map((tab) => (
        <button
          key={tab.id}
          className={activeTab === tab.id ? "active" : ""}
          onClick={() => setActiveTab(tab.id)}
        >
          <span>{tab.id}</span>
          <span className="tab-info" title={tab.hint} aria-label={`${tab.id} tab help`}>
            <Info size={12} />
          </span>
        </button>
      ))}
    </nav>
  );
}

function Overview({
  migration,
  uploadResult,
  mappingResult,
  canonicalResult,
  records,
  events,
  runMetrics,
  pushPreview
}: {
  migration: MigrationSummary | null;
  uploadResult: CreateMigrationResponse | null;
  mappingResult: GenerateMappingsResponse | null;
  canonicalResult: CanonicalizeResponse | null;
  records: MigrationRecord[];
  events: Array<{ type: string; payload: Record<string, unknown> }>;
  runMetrics: RunMetricsResponse | null;
  pushPreview: PushPreviewResponse | null;
}) {
  const openIssues = canonicalResult?.review_records ?? 0;
  const validRecords = canonicalResult?.valid_records ?? 0;
  const mappingReviews =
    mappingResult?.mappings.filter((mapping) => mapping.decision === "NEEDS_REVIEW").length ?? 0;
  const importantIssue = topIssue(runMetrics?.issue_counts);
  const coverage = columnCoverage(migration, uploadResult, mappingResult);
  return (
    <div className="overview-grid">
      <Metric
        label="Readiness"
        value={`${runMetrics?.readiness_score ?? 0}%`}
        hint="How ready this migration is for target push after validation, reviews, and push blockers."
      />
      <Metric
        label="Agent Score"
        value={`${runMetrics?.agent_score ?? 0}%`}
        hint="Deterministic score from mapping confidence, validation success, autonomy, and push success."
      />
      <Metric
        label="Files"
        value={migration?.progress.files ?? uploadResult?.files.length ?? 0}
        hint="Source CSV or Excel files uploaded for this migration."
      />
      <Metric
        label="Profiles"
        value={migration?.progress.profiles ?? uploadResult?.profiles_created ?? 0}
        hint="Columns analyzed by the system before mapping."
      />
      <Metric
        label="Mappings"
        value={mappingResult?.mappings.length ?? 0}
        hint="Source columns connected to target employee fields."
      />
      <Metric
        label="Records"
        value={records.length || canonicalResult?.records_created || 0}
        hint="Employee rows converted into the target shape."
      />
      <Metric
        label="Valid Records"
        value={runMetrics?.valid_records ?? validRecords}
        hint="Records that passed target validation and can be pushed."
      />
      <Metric
        label="Ready To Push"
        value={runMetrics?.ready_to_push ?? pushPreview?.ready_count ?? 0}
        hint="Validated records that can be sent to the mock target now."
      />
      <Metric
        label="Open Reviews"
        value={runMetrics?.open_reviews ?? mappingReviews + openIssues}
        hint="Human decisions blocking the agent from continuing."
      />
      <Metric
        label="Time Taken"
        value={formatSeconds(runMetrics?.elapsed_seconds)}
        hint="Elapsed time from migration creation to now, or to completion for finished runs."
      />
      <Metric
        label="LLM Tokens"
        value={runMetrics?.llm.total_tokens ?? "unknown"}
        hint="Token usage reported by the LLM provider. Unknown means the provider did not return usage."
      />
      <div className="panel wide overview-summary">
        <div className="panel-title">
          <Info size={16} />
          What this run means
        </div>
        <div className="summary-explain-grid">
          <SummaryItem label="Current stage" value={statusLabel(migration?.status)} />
          <SummaryItem label="Next action" value={nextActionText(migration, openIssues, mappingReviews, validRecords)} />
          <SummaryItem label="Needs review" value={`${runMetrics?.open_reviews ?? mappingReviews + openIssues} item${(runMetrics?.open_reviews ?? mappingReviews + openIssues) === 1 ? "" : "s"}`} />
          <SummaryItem label="Push preview" value={`${pushPreview?.ready_count ?? 0} ready / ${pushPreview?.blocked_count ?? 0} blocked`} />
          <SummaryItem label="LLM usage" value={runMetrics?.llm.used ? `${runMetrics.llm.provider ?? "LLM"} mapping` : "Not used"} />
          <SummaryItem label="Sensitive data" value={runMetrics?.sensitive_fields_masked.length ? `${runMetrics.sensitive_fields_masked.length} fields masked` : "No sensitive fields found"} />
          <SummaryItem label="Top issue" value={importantIssue} />
        </div>
      </div>
      <div className={`panel wide coverage-panel ${coverage.missingDecisions > 0 ? "has-warning" : ""}`}>
        <div className="panel-title">
          <GitCompare size={16} />
          Column coverage
          <button
            className="info-button"
            type="button"
            title="This checks whether every source column received a mapping decision. It helps catch columns that were silently skipped."
            aria-label="Column coverage help"
          >
            <Info size={13} />
          </button>
        </div>
        <div className="coverage-equation">
          <strong>{coverage.sourceColumns} source columns</strong>
          <span>=</span>
          <StatusBadge status={`${coverage.autoMapped} auto-mapped`} />
          <span>+</span>
          <StatusBadge status={`${coverage.reviewNeeded} review`} />
          <span>+</span>
          <StatusBadge status={`${coverage.unmapped} unmapped`} />
          <span>+</span>
          <StatusBadge status={`${coverage.rejected} rejected`} />
        </div>
        {coverage.missingDecisions > 0 ? (
          <p className="error-line">
            {coverage.missingDecisions} source column{coverage.missingDecisions === 1 ? "" : "s"} do not have a mapping decision yet.
          </p>
        ) : (
          <p className="muted-text">Every profiled source column has a visible mapping decision.</p>
        )}
      </div>
      <div className="panel wide overview-summary">
        <div className="panel-title">
          <Workflow size={16} />
          Agent run details
        </div>
        <div className="summary-explain-grid">
          <SummaryItem label="Auto mappings" value={`${runMetrics?.autonomous_mappings ?? 0}`} />
          <SummaryItem label="Mapping reviews" value={`${runMetrics?.review_mappings ?? 0}`} />
          <SummaryItem label="Blocked records" value={`${runMetrics?.blocked_from_push ?? 0}`} />
          <SummaryItem label="Push success" value={runMetrics?.push_success_rate === null || runMetrics?.push_success_rate === undefined ? "Not run" : `${runMetrics.push_success_rate}%`} />
          <SummaryItem label="Masked fields" value={runMetrics?.sensitive_fields_masked.map(humanize).join(", ") || "None"} />
          <SummaryItem label="LLM model" value={runMetrics?.llm.model ?? "Not used"} />
        </div>
      </div>
      <div className="panel wide">
        <h2>Agent activity</h2>
        <ul className="activity-list">
          <Activity done={Boolean(uploadResult)} label="Parsed source exports" />
          <Activity done={Boolean(uploadResult)} label="Profiled source columns" />
          <Activity done={Boolean(mappingResult)} label="Generated mapping candidates" />
          <Activity done={Boolean(canonicalResult)} label="Validated canonical records" />
          <Activity done={events.length > 0} label="Received migration event stream" active={events.length > 0} />
        </ul>
      </div>
    </div>
  );
}

function MappingTable({ mappingResult }: { mappingResult: GenerateMappingsResponse | null }) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <InfoHeader label="Source Column" hint="Column name from the uploaded source file." />
            <InfoHeader label="Target Field" hint="Employee target field selected by the agent or reviewer." />
            <InfoHeader label="Status" hint="Whether the mapping was auto-approved, reviewed, corrected, or rejected." />
            <InfoHeader label="Confidence" hint="Weighted mapping score from semantic, name, type, and value checks." />
            <InfoHeader label="Type" hint="How well the source values match the expected target field type." />
            <InfoHeader label="Reason" hint="Short explanation from deterministic rules or the configured LLM mapping provider." />
          </tr>
        </thead>
        <tbody>
          {(mappingResult?.mappings ?? []).map((mapping) => (
            <tr key={mapping.id}>
              <td><code>{mapping.source_column}</code></td>
              <td><code>{mapping.target_field ?? "unmapped"}</code></td>
              <td><StatusBadge status={mapping.decision} /></td>
              <td>{Math.round(mapping.final_score * 100)}%</td>
              <td>{Math.round(mapping.type_score * 100)}%</td>
              <td>{mapping.reasoning}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {!mappingResult && <EmptyState label="No mappings generated yet" />}
    </div>
  );
}

function ValidationTable({ result }: { result: CanonicalizeResponse | null }) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <InfoHeader label="Employee ID" hint="Employee identifier after source rows are merged." />
            <InfoHeader label="Status" hint="VALID records can be pushed; NEEDS_REVIEW or INVALID records need attention." />
            <InfoHeader label="Issues" hint="Validation, conflict, duplicate, or outlier findings for this record." />
            <InfoHeader label="Record ID" hint="Internal canonical record id for tracing audit and target pushes." />
          </tr>
        </thead>
        <tbody>
          {(result?.records ?? []).map((record) => (
            <tr key={record.id}>
              <td><code>{record.employee_id ?? "missing"}</code></td>
              <td><StatusBadge status={record.validation_status} /></td>
              <td>{record.issues.map((issue) => String(issue.type ?? "issue")).join(", ") || "none"}</td>
              <td><code>{record.id}</code></td>
            </tr>
          ))}
        </tbody>
      </table>
      {!result && <EmptyState label="No canonical records yet" />}
    </div>
  );
}

function ReviewQueue({
  escalations,
  migration,
  records,
  reviewIndex,
  setReviewIndex,
  onResolve,
  onContinue
}: {
  escalations: Escalation[];
  migration: MigrationSummary | null;
  records: MigrationRecord[];
  reviewIndex: number;
  setReviewIndex: (index: number) => void;
  onResolve: (
    id: string,
    action: "APPROVE" | "CORRECT" | "REJECT" | "SEND_TO_HR",
    resolution?: Record<string, unknown>
  ) => void;
  onContinue: () => void;
}) {
  if (escalations.length === 0) {
    const validRecords = records.filter((record) => record.validation_status === "VALID").length;
    const settled = Boolean(
      migration && ["COMPLETED", "PARTIALLY_COMPLETED", "ROLLED_BACK"].includes(migration.status)
    );
    const blocked = migration?.status === "BLOCKED" || validRecords === 0;
    return (
      <div className="empty-state">
        <p>
          {settled
            ? "No review needed. Target push has already settled."
            : blocked
              ? "No review is open, but no valid records are ready for target push."
              : "No review needed. Valid records can be pushed."}
        </p>
        {!settled && !blocked && (
          <button className="primary-button" onClick={onContinue}>
            <Play size={15} />
            Continue to push
          </button>
        )}
      </div>
    );
  }
  const activeIndex = Math.min(reviewIndex, escalations.length - 1);
  const activeEscalation = escalations[activeIndex];
  const openCount = escalations.filter((item) => item.status === "OPEN").length;
  const validRecords = records.filter((record) => record.validation_status === "VALID").length;
  return (
    <div className="review-workspace">
      <div className="agent-presence-bar">
        <Workflow size={15} />
        <span>Agent paused here for human decision. Resolve the card to let the workflow continue.</span>
      </div>
      <div className="agent-live-strip">
        <SummaryItem label="Agent state" value={statusLabel(migration?.status)} />
        <SummaryItem label="Doing now" value={agentDoingText(migration, openCount)} />
        <SummaryItem label="Escalation queue" value={`${openCount} open / ${escalations.length} total`} />
        <SummaryItem label="Valid records" value={`${validRecords}`} />
      </div>
      <div className="review-card-toolbar">
        <div>
          <span className="muted-text">Review card</span>
          <strong>{activeIndex + 1} of {escalations.length}</strong>
          <StatusBadge status={`${openCount} open`} />
        </div>
        <div className="review-nav-actions">
          <button
            className="secondary-button review-action-button"
            disabled={activeIndex === 0}
            onClick={() => setReviewIndex(activeIndex - 1)}
          >
            <ChevronLeft size={15} />
            Previous
          </button>
          <button
            className="secondary-button review-action-button"
            disabled={activeIndex >= escalations.length - 1}
            onClick={() => setReviewIndex(activeIndex + 1)}
          >
            Next
            <ChevronRight size={15} />
          </button>
        </div>
      </div>
      <ReviewCard key={activeEscalation.id} escalation={activeEscalation} onResolve={onResolve} />
    </div>
  );
}

function ReviewCard({
  escalation,
  onResolve
}: {
  escalation: Escalation;
  onResolve: (
    id: string,
    action: "APPROVE" | "CORRECT" | "REJECT" | "SEND_TO_HR",
    resolution?: Record<string, unknown>
  ) => void;
}) {
  const recordData = escalation.context.record_data;
  const employeeId = typeof escalation.context.employee_id === "string"
    ? escalation.context.employee_id
    : "unknown";
  const field = typeof escalation.context.editable_field === "string"
    ? escalation.context.editable_field
    : typeof escalation.context.field === "string"
      ? escalation.context.field
      : "record";
  const currentValue = escalation.context.current_value
    ?? escalation.context.value
    ?? escalation.context.incoming
    ?? (typeof recordData === "object" && recordData !== null && field in recordData
      ? (recordData as Record<string, unknown>)[field]
      : "");
  const summary = typeof escalation.context.summary === "string"
    ? escalation.context.summary
    : `${field} needs review`;
  const reason = typeof escalation.context.reason === "string"
    ? escalation.context.reason
    : "The system found something that should be checked before this employee is migrated.";
  const recommendedAction = typeof escalation.context.recommended_action_text === "string"
    ? escalation.context.recommended_action_text
    : "Approve the value if it is correct, or enter a corrected value.";
  const evidence = Array.isArray(escalation.context.evidence)
    ? escalation.context.evidence
    : [];
  const isOpen = escalation.status === "OPEN";
  const [correctedValue, setCorrectedValue] = useState(String(currentValue ?? ""));
  const [comment, setComment] = useState("");

  return (
    <article className="approval-card">
      <div className="approval-header">
        <div>
          <h2>{summary}</h2>
          <p>Employee {employeeId}</p>
        </div>
        <div className="review-status-stack">
          <StatusBadge status={escalation.severity} />
          <StatusBadge status={escalation.status} />
        </div>
      </div>
      <div className="review-info-grid">
        <div className="review-context-column">
          <section className="review-explanation">
            <h3>Reason for review</h3>
            <p>{reason}</p>
          </section>
          {evidence.length > 0 && (
            <section className="review-evidence">
              <h3>Evidence found</h3>
              <dl>
                {evidence.map((item, index) => {
                  const entry = item as Record<string, unknown>;
                  return (
                    <div key={`${String(entry.label)}-${index}`}>
                      <dt>{String(entry.label ?? "Evidence")}</dt>
                      <dd>{String(entry.value ?? "")}</dd>
                    </div>
                  );
                })}
              </dl>
            </section>
          )}
        </div>
        <div className="review-action-column">
          <section className="review-explanation">
            <h3>What to do</h3>
            <p>{recommendedAction}</p>
          </section>
          <div className="review-fields">
            <label>
              Current value
              <input value={String(currentValue ?? "")} readOnly />
            </label>
            <label>
              Correct value
              <input value={correctedValue} onChange={(event) => setCorrectedValue(event.target.value)} />
            </label>
            <label>
              Comment
              <textarea value={comment} onChange={(event) => setComment(event.target.value)} />
            </label>
          </div>
        </div>
      </div>
      <div className="approval-actions">
        <button className="secondary-button review-action-button" disabled={!isOpen} onClick={() => onResolve(escalation.id, "REJECT", { field, comment })}>
          <XCircle size={15} />
          Reject record
        </button>
        <button
          className="secondary-button review-action-button"
          disabled={!isOpen}
          onClick={() => onResolve(escalation.id, "CORRECT", { field, corrected_value: correctedValue, comment })}
        >
          <FileCode2 size={15} />
          Save corrected value
        </button>
        <button
          className="secondary-button review-action-button"
          disabled={!isOpen}
          onClick={() => onResolve(escalation.id, "SEND_TO_HR", { field, current_value: currentValue, comment })}
        >
          <ShieldCheck size={15} />
          Ask HR for info
        </button>
        <button className="primary-button review-action-button" disabled={!isOpen} onClick={() => onResolve(escalation.id, "APPROVE", { field, comment })}>
          <CheckCircle2 size={15} />
          Approve as correct
        </button>
      </div>
    </article>
  );
}

function PushResults({
  pushResult,
  rollbackResult,
  records,
  migration,
  pushPreview,
  rollbackPreview,
  onRetryFailed
}: {
  pushResult: PushMigrationResponse | null;
  rollbackResult: RollbackMigrationResponse | null;
  records: MigrationRecord[];
  migration: MigrationSummary | null;
  pushPreview: PushPreviewResponse | null;
  rollbackPreview: RollbackPreviewResponse | null;
  onRetryFailed: () => void;
}) {
  const [showRollbackPreview, setShowRollbackPreview] = useState(false);
  const inferredResults = records
    .filter((record) => record.push_status)
    .map((record) => ({
      record_id: record.id,
      employee_id: record.employee_id,
      status: record.push_status ?? "PENDING",
      target_record_id: record.target_record_id,
      attempts: null,
      http_status: null,
      error_code: null,
    }));
  const resultRows = pushResult?.results ?? inferredResults;
  const pushed = pushResult?.pushed ?? resultRows.filter((result) => result.status === "SUCCEEDED").length;
  const failed = pushResult?.failed ?? resultRows.filter((result) => result.status?.startsWith("FAILED")).length;
  const previewRows = pushPreview?.records ?? [];
  const rollbackRows = rollbackPreview?.records ?? [];
  const hasTargetActivity = resultRows.length > 0 || Boolean(rollbackResult) || previewRows.length > 0 || rollbackRows.length > 0;

  if (!hasTargetActivity) {
    return <EmptyState label="No target push preview is available yet" />;
  }

  return (
    <div className="push-results">
      {previewRows.length > 0 && (
        <section className="panel">
          <div className="panel-title">
            <DatabaseZap size={16} />
            What will change in target
          </div>
          <div className="summary-row">
            <Metric label="Ready" value={pushPreview?.ready_count ?? 0} />
            <Metric label="Blocked" value={pushPreview?.blocked_count ?? 0} />
            {migration && <Metric label="Run state" value={statusLabel(migration.status)} />}
          </div>
          <div className="preview-card-grid">
            {previewRows.map((item) => (
              <article className="preview-card" key={item.record_id}>
                <div className="preview-card-header">
                  <strong>{item.employee_id ?? "Missing employee ID"}</strong>
                  <StatusBadge status={item.status} />
                </div>
                <SummaryItem label="Target action" value={item.action} />
                <SummaryItem label="Reason" value={item.reason} />
                <div className="preview-fields">
                  {previewDataEntries(item.data, item.reason).map(([label, value]) => (
                    <SummaryItem key={label} label={label} value={value} />
                  ))}
                </div>
              </article>
            ))}
          </div>
        </section>
      )}
      {resultRows.length > 0 && (
        <div className="table-wrap">
          <div className="summary-row">
            <Metric label="Pushed" value={pushed} />
            <Metric label="Failed" value={failed} />
            {migration && <Metric label="Records" value={resultRows.length} />}
            {failed > 0 && (
              <button className="secondary-button" onClick={onRetryFailed}>
                <Play size={15} />
                Retry failed records
              </button>
            )}
          </div>
          <table>
            <thead>
              <tr>
                <th>Employee ID</th>
                <th>Status</th>
                <th>Attempts</th>
                <th>HTTP</th>
                <th>Target ID</th>
                <th>Error</th>
              </tr>
            </thead>
            <tbody>
              {resultRows.map((result) => (
                <tr key={result.record_id}>
                  <td><code>{result.employee_id ?? "missing"}</code></td>
                  <td><StatusBadge status={result.status} /></td>
                  <td>{result.attempts ?? "n/a"}</td>
                  <td>{result.http_status ?? "n/a"}</td>
                  <td><code>{result.target_record_id ?? "not created"}</code></td>
                  <td>{result.error_code ?? "none"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {rollbackRows.length > 0 && !showRollbackPreview && !rollbackResult && (
        <section className="panel">
          <div className="panel-title">
            <ShieldCheck size={16} />
            Rollback preview
          </div>
          <p className="muted-text">
            Preview which target records would be removed before running rollback.
          </p>
          <button className="secondary-button" onClick={() => setShowRollbackPreview(true)}>
            <Search size={15} />
            Show rollback preview
          </button>
        </section>
      )}
      {rollbackRows.length > 0 && showRollbackPreview && (
        <section className="panel">
          <div className="panel-title">
            <ShieldCheck size={16} />
            Rollback preview
          </div>
          <div className="summary-row">
            <Metric label="Will Remove" value={rollbackPreview?.removable_count ?? 0} />
            <button className="secondary-button" onClick={() => setShowRollbackPreview(false)}>
              Hide preview
            </button>
          </div>
          <div className="preview-card-grid">
            {rollbackRows.map((item) => (
              <article className="preview-card" key={item.push_id}>
                <div className="preview-card-header">
                  <strong>{item.employee_id ?? "Missing employee ID"}</strong>
                  <StatusBadge status="Will be removed" />
                </div>
                <SummaryItem label="Target action" value={item.action} />
                <SummaryItem label="Target ID" value={item.target_record_id} />
                <div className="preview-fields">
                  {previewDataEntries(item.data).map(([label, value]) => (
                    <SummaryItem key={label} label={label} value={value} />
                  ))}
                </div>
              </article>
            ))}
          </div>
        </section>
      )}
      {rollbackResult && (
        <div className="table-wrap">
          <div className="summary-row">
            <Metric label="Rolled Back" value={rollbackResult.rolled_back} />
          </div>
          <table>
            <thead>
              <tr>
                <th>Push ID</th>
                <th>Target ID</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {rollbackResult.results.map((result) => (
                <tr key={result.push_id}>
                  <td><code>{result.push_id}</code></td>
                  <td><code>{result.target_record_id ?? "not created"}</code></td>
                  <td><StatusBadge status={result.status} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function AuditTimeline({ events }: { events: AuditEvent[] }) {
  if (events.length === 0) {
    return <EmptyState label="No audit events loaded for this migration" />;
  }

  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Time</th>
            <th>Actor</th>
            <th>Event</th>
            <th>Entity</th>
            <th>Reason</th>
            <th>Metadata</th>
          </tr>
        </thead>
        <tbody>
          {events.map((event) => (
            <tr key={event.id}>
              <td>{new Date(event.created_at).toLocaleTimeString()}</td>
              <td><StatusBadge status={event.actor_type} /></td>
              <td>{eventLabel(event.event_type)}</td>
              <td><code>{event.entity_type}:{event.entity_id ?? "n/a"}</code></td>
              <td>{event.reason ?? "none"}</td>
              <td><MetadataSummary metadata={event.metadata} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function OpsPanel({
  metrics,
  killSwitch,
  isAdmin,
  onToggleKillSwitch
}: {
  metrics: OpsMetrics | null;
  killSwitch: KillSwitchStatus | null;
  isAdmin: boolean;
  onToggleKillSwitch: (enabled: boolean) => void;
}) {
  return (
    <div className="ops-panel">
      <div className="overview-grid">
        <Metric label="Migrations" value={metrics?.migrations ?? 0} />
        <Metric label="Audit Events" value={metrics?.audit_events ?? 0} />
        <Metric label="Open Reviews" value={metrics?.open_escalations ?? 0} />
        <Metric label="Pushed" value={metrics?.pushed_records ?? 0} />
        <Metric label="Failed Pushes" value={metrics?.failed_pushes ?? 0} />
      </div>
      <section className="panel">
        <div className="panel-title">
          <ShieldCheck size={16} />
          Kill switch
        </div>
        <div className="kill-switch-row">
          <StatusBadge status={killSwitch?.enabled ? "ACTIVE" : "OPEN"} />
          <span>
            {killSwitch?.enabled
              ? `Pipeline is paused: ${killSwitch.reason ?? "manual ops hold"}`
              : "Pipeline actions are allowed. Enable this only to pause starts and target pushes during an incident."}
          </span>
          <button
            className={killSwitch?.enabled ? "secondary-button" : "primary-button"}
            disabled={!isAdmin}
            onClick={() => onToggleKillSwitch(!killSwitch?.enabled)}
          >
            {killSwitch?.enabled ? "Disable" : "Enable"}
          </button>
        </div>
      </section>
    </div>
  );
}

function LogViewer({ logs }: { logs: string[] }) {
  return (
    <div className="log-viewer">
      {logs.map((line) => (
        <code key={line}>{line}</code>
      ))}
    </div>
  );
}

function AgentActivity({
  migration,
  busy,
  activity
}: {
  migration: MigrationSummary | null;
  busy: string | null;
  activity: ActivityItem[];
}) {
  const reviewResolved = activity.some((item) => item.message === "Review item resolved");
  const waitingForReview = migration?.status === "WAITING_FOR_REVIEW";
  const reachedValidation = Boolean(
    migration && [
      "VALIDATING",
      "READY_TO_PUSH",
      "PUSHING",
      "COMPLETED",
      "PARTIALLY_COMPLETED",
      "ROLLED_BACK",
      "BLOCKED"
    ].includes(migration.status)
  );
  const humanReviewLabel = waitingForReview
    ? "Human review required"
    : reviewResolved
      ? "Human review completed"
      : "Human review not needed";
  const humanReviewDone = reviewResolved || (!waitingForReview && reachedValidation);
  return (
    <section className="panel">
      <h2>Run state</h2>
      <ul className="activity-list compact">
        {activity.slice(-4).map((item) => (
          <Activity key={item.id} done label={item.message} />
        ))}
        <Activity done={Boolean(migration)} label="Migration created" />
        <Activity done={Boolean(migration && ["MAPPING", "VALIDATING", "WAITING_FOR_REVIEW", "READY_TO_PUSH", "PUSHING", "COMPLETED", "PARTIALLY_COMPLETED", "ROLLED_BACK", "BLOCKED"].includes(migration.status))} label="Mappings evaluated" />
        <Activity done={Boolean(migration && ["VALIDATING", "WAITING_FOR_REVIEW", "READY_TO_PUSH", "PUSHING", "COMPLETED", "PARTIALLY_COMPLETED", "ROLLED_BACK", "BLOCKED"].includes(migration.status))} label="Records validated" />
        <Activity done={humanReviewDone} label={humanReviewLabel} active={waitingForReview} />
        <Activity done={Boolean(migration && ["COMPLETED", "PARTIALLY_COMPLETED", "ROLLED_BACK"].includes(migration.status))} label="Target push settled" active={migration?.status === "PUSHING"} />
        {busy && <Activity done={false} label={busy} active />}
      </ul>
    </section>
  );
}

function CommandPalette({
  close,
  setTheme,
  setSidebarCollapsed,
  setActiveTab
}: {
  close: () => void;
  setTheme: (theme: ThemePreference) => void;
  setSidebarCollapsed: (updater: (value: boolean) => boolean) => void;
  setActiveTab: (tab: WorkspaceTab) => void;
}) {
  const commands = [
    { label: "View mappings", action: () => setActiveTab("mappings") },
    { label: "View validation", action: () => setActiveTab("validation") },
    { label: "View review queue", action: () => setActiveTab("review") },
    { label: "View push results", action: () => setActiveTab("push") },
    { label: "View audit timeline", action: () => setActiveTab("audit") },
    { label: "View ops panel", action: () => setActiveTab("ops") },
    { label: "Open logs", action: () => setActiveTab("logs") },
    { label: "Toggle sidebar", action: () => setSidebarCollapsed((value) => !value) },
    { label: "Switch dark theme", action: () => setTheme("dark") },
    { label: "Switch light theme", action: () => setTheme("light") }
  ];
  return (
    <div className="command-backdrop" onClick={close}>
      <div className="command-palette" onClick={(event) => event.stopPropagation()}>
        <div className="command-input">
          <Command size={16} />
          <span>Command palette</span>
        </div>
        {commands.map((command) => (
          <button
            key={command.label}
            onClick={() => {
              command.action();
              close();
            }}
          >
            {command.label}
          </button>
        ))}
      </div>
    </div>
  );
}

function MetadataSummary({ metadata }: { metadata: Record<string, unknown> | null }) {
  const items = metadataEntries(metadata);
  if (items.length === 0) {
    return <span className="muted-text">No details</span>;
  }
  return (
    <dl className="metadata-list">
      {items.map(([label, value]) => (
        <div key={label}>
          <dt>{label}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}

function InfoHeader({ label, hint }: { label: string; hint: string }) {
  return (
    <th>
      <span className="table-header-help">
        {label}
        <button className="info-button" type="button" title={hint} aria-label={`${label} help`}>
          <Info size={13} />
        </button>
      </span>
    </th>
  );
}

function Metric({ label, value, hint }: { label: string; value: number | string; hint?: string }) {
  return (
    <div className="metric-card">
      <span>
        {label}
        {hint && (
          <button className="info-button" type="button" title={hint} aria-label={`${label} help`}>
            <Info size={13} />
          </button>
        )}
      </span>
      <strong>{value}</strong>
    </div>
  );
}

function SummaryItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="summary-item">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function Activity({ done, label, active = false }: { done: boolean; label: string; active?: boolean }) {
  return (
    <li className={active ? "active" : ""}>
      {done ? <CheckCircle2 size={15} /> : active ? <Loader2 size={15} className="spin" /> : <span className="dot" />}
      <span>{label}</span>
    </li>
  );
}

function StatusBadge({ status }: { status: string }) {
  const normalized = status.toLowerCase().replace(/_/g, "-").replace(/\s/g, "-");
  return <span className={`status-badge ${normalized}`}>{status}</span>;
}

function EmptyState({ label }: { label: string }) {
  return <div className="empty-state">{label}</div>;
}

function statusLabel(status: MigrationSummary["status"] | undefined): string {
  if (!status) {
    return "Not started";
  }
  const labels: Record<string, string> = {
    PROFILING: "Reading uploaded files",
    MAPPING: "Matching columns",
    VALIDATING: "Checking employee records",
    WAITING_FOR_REVIEW: "Waiting for review",
    PUSHING: "Pushing valid records",
    COMPLETED: "Completed",
    PARTIALLY_COMPLETED: "Partially completed",
    BLOCKED: "Blocked",
    ROLLED_BACK: "Rolled back"
  };
  return labels[status] ?? humanize(status);
}

function progressStatusLabel(
  migration: MigrationSummary | null,
  progress: number,
  busy: string | null
): string {
  if (busy) {
    return "PROCESSING";
  }
  if (migration?.status === "BLOCKED" && progress === 100) {
    return "STOPPED SAFELY";
  }
  return migration?.status ?? "IDLE";
}

function nextActionText(
  migration: MigrationSummary | null,
  reviewRecords: number,
  mappingReviews: number,
  validRecords: number
): string {
  if (!migration) {
    return "Upload files to begin.";
  }
  if (migration.status === "WAITING_FOR_REVIEW") {
    return `Resolve ${mappingReviews + reviewRecords || 1} review item before the agent continues.`;
  }
  if (migration.status === "BLOCKED") {
    return "Fix the blocked data or upload a corrected source file.";
  }
  if (migration.status === "COMPLETED") {
    return "No action needed. Valid records reached the target.";
  }
  if (migration.status === "PARTIALLY_COMPLETED") {
    return "Check failed target rows and retry if they are retryable.";
  }
  if (validRecords > 0) {
    return "Valid records are ready for the target step.";
  }
  return "Let the workflow finish mapping and validation.";
}

function agentDoingText(migration: MigrationSummary | null, openReviews: number): string {
  if (!migration) {
    return "Waiting for files.";
  }
  if (openReviews > 0 || migration.status === "WAITING_FOR_REVIEW") {
    return "Paused for human decision.";
  }
  if (migration.status === "MAPPING") {
    return "Evaluating column matches.";
  }
  if (migration.status === "VALIDATING") {
    return "Checking record quality.";
  }
  if (migration.status === "PUSHING") {
    return "Writing valid records to target.";
  }
  if (migration.status === "COMPLETED") {
    return "Run finished successfully.";
  }
  if (migration.status === "BLOCKED") {
    return "Stopped safely.";
  }
  return "Monitoring run state.";
}

function eventLabel(eventType: string): string {
  const labels: Record<string, string> = {
    FILE_INGESTED: "Loaded source file",
    FILE_PROFILED: "Profiled source file",
    WORKFLOW_STARTED: "Started workflow",
    MAPPING_AUTO_APPROVED: "Auto-approved mapping",
    MAPPING_ESCALATED: "Requested mapping review",
    VALUE_TRANSFORM_ISSUE: "Found value issue",
    VALIDATION_REPAIR_ATTEMPTED: "Tried automatic repair",
    CONFLICT_RESOLVED_BY_PRECEDENCE: "Resolved conflict by source priority",
    EXACT_DUPLICATE_REMOVED: "Removed duplicate row",
    REVIEW_RESOLVED: "Resolved review",
    REVIEW_SENT_TO_HR: "Sent review to HR",
    TARGET_PUSH_ATTEMPT: "Tried target push",
    RECORD_PUSHED: "Pushed record",
    RECORD_PUSH_FAILED: "Record push failed",
    ROLLBACK_EXECUTED: "Rolled back target record"
  };
  return labels[eventType] ?? humanize(eventType);
}

function metadataEntries(metadata: Record<string, unknown> | null): Array<[string, string]> {
  if (!metadata) {
    return [];
  }
  return Object.entries(metadata)
    .filter(([, value]) => value !== null && value !== undefined && value !== "")
    .slice(0, 5)
    .map(([key, value]) => [humanize(key), formatMetadataValue(value)]);
}

function previewDataEntries(data: Record<string, unknown>, reason = ""): Array<[string, string]> {
  const issueField = issueFieldFromReason(reason);
  const sensitiveIssue = issueField ? isSensitiveField(issueField) : false;
  const preferred = [
    issueField,
    "full_name",
    "email",
    "department",
    "joining_date",
    "location",
    "employment_type",
    "manager_id",
  ].filter(Boolean) as string[];
  const orderedKeys = [
    ...preferred,
    ...Object.keys(data).filter((key) => !preferred.includes(key)),
  ];
  const seen = new Set<string>();
  const entries: Array<[string, string]> = [];
  for (const key of orderedKeys) {
    if (seen.has(key) || key === "employee_id") {
      continue;
    }
    seen.add(key);
    const value = data[key];
    if (value === null || value === undefined || value === "") {
      continue;
    }
    if (isSensitiveField(key) && key !== issueField && !sensitiveIssue) {
      continue;
    }
    entries.push([humanize(key), formatMetadataValue(value)]);
    if (entries.length >= 4) {
      break;
    }
  }
  return entries;
}

function formatSeconds(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) {
    return "n/a";
  }
  if (seconds < 60) {
    return `${Math.round(seconds)}s`;
  }
  const minutes = Math.floor(seconds / 60);
  const remaining = Math.round(seconds % 60);
  return `${minutes}m ${remaining}s`;
}

function issueFieldFromReason(reason: string): string | null {
  const match = reason.match(/^([a-zA-Z0-9_]+) has an unresolved/i);
  return match?.[1] ?? null;
}

function isSensitiveField(field: string): boolean {
  const normalized = field.toLowerCase();
  return ["salary", "hike", "dob", "date_of_birth", "phone", "mobile", "bank", "account", "tax", "ssn", "pan", "aadhaar"].some(
    (part) => normalized.includes(part)
  );
}

function topIssue(issueCounts: Record<string, number> | undefined): string {
  const entries = Object.entries(issueCounts ?? {});
  if (entries.length === 0) {
    return "None";
  }
  const [issue, count] = entries.sort((left, right) => right[1] - left[1])[0];
  return `${count} ${humanize(issue)}`;
}

function columnCoverage(
  migration: MigrationSummary | null,
  uploadResult: CreateMigrationResponse | null,
  mappingResult: GenerateMappingsResponse | null
) {
  const mappings = mappingResult?.mappings ?? [];
  const sourceColumns = migration?.progress.profiles ?? uploadResult?.profiles_created ?? mappings.length;
  const autoMapped = mappings.filter((mapping) => mapping.decision === "AUTO_APPROVED").length;
  const reviewNeeded = mappings.filter((mapping) => mapping.decision === "NEEDS_REVIEW").length;
  const rejected = mappings.filter((mapping) => mapping.decision === "REJECTED").length;
  const unmapped = mappings.filter(
    (mapping) => !mapping.target_field && mapping.decision !== "NEEDS_REVIEW" && mapping.decision !== "REJECTED"
  ).length;
  const decided = mappings.length;
  return {
    sourceColumns,
    autoMapped,
    reviewNeeded,
    rejected,
    unmapped,
    missingDecisions: Math.max(0, sourceColumns - decided),
  };
}

function formatMetadataValue(value: unknown): string {
  if (Array.isArray(value)) {
    return `${value.length} item${value.length === 1 ? "" : "s"}`;
  }
  if (typeof value === "object" && value !== null) {
    const entries = Object.entries(value as Record<string, unknown>)
      .filter(([, nested]) => nested !== null && nested !== undefined && nested !== "")
      .slice(0, 3)
      .map(([key, nested]) => `${humanize(key)}: ${String(nested)}`);
    return entries.join(", ") || "Details captured";
  }
  return String(value);
}

function humanize(value: string): string {
  return value
    .replace(/[_-]/g, " ")
    .toLowerCase()
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function JsonViewer({ value }: { value: Record<string, unknown> }) {
  return <pre className="json-viewer">{JSON.stringify(value, null, 2)}</pre>;
}
