# MigrationPilot AI

Policy-aware AI HR data migration agent.

## Tech Stack

The MVP is intentionally small and local-demo friendly:

- Backend: FastAPI, SQLAlchemy, Pydantic v2
- Frontend: React, TypeScript, Vite
- Workflow: LangGraph with SQLite checkpointing
- Database: SQLite
- Data processing: Pandas, OpenPyXL
- Matching: RapidFuzz, deterministic synonyms, optional NVIDIA-hosted `openai/gpt-oss-20b`
- Testing: Pytest, TypeScript build

## Current Implementation

Completed foundations:

- backend package skeleton
- frontend Vite shell
- target employee schema
- shared enums and policy/source-precedence config
- scenario-driven sample datasets
- initial documentation
- SQLite bootstrap
- demo user seeding
- lightweight JWT auth/RBAC
- minimal append-only audit service
- migration upload API
- CSV/XLSX ingestion and column profiling
- initial LangGraph workflow skeleton
- deterministic/LLM-boundary mapping engine
- confidence scoring and Decision Engine
- mapping persistence and audit events
- canonical record generation
- deterministic cleanup, reconciliation, validation, conflict precedence, and outlier detection
- policy-aware escalations, backend masking, role-aware review, and atomic resolution
- developer-tool frontend workspace with light/dark/system theme, command palette, dense tables, review cards, logs, and SSE status hook
- mock target integration with idempotent push attempts, retry semantics, rollback support, and push-result UI
- audit timeline API/UI, ops metrics, admin kill switch, and kill-switch enforcement before new starts and target pushes
- LangGraph-owned migration workflow that maps, validates, creates review work, interrupts/resumes, and pushes when clear
- reloadable records/activity APIs and retry-failed API
- persistent SQLite checkpointing for LangGraph workflow continuity

## Architecture

MigrationPilot AI is a small single-repo prototype:

```text
React UI
  -> FastAPI APIs
  -> SQLite models for migrations, mappings, records, escalations, audit, and target attempts
  -> LangGraph migration workflow keyed by migration_id/thread_id
  -> deterministic services + LLM-assisted mapping
  -> mock target API with retry, idempotency, and rollback
```

Heavy uploaded data is stored in SQLite/file storage. LangGraph state stays lightweight and stores IDs, stage, status, pending escalation references, and target result references.

The UI starts the backend workflow with:

```text
POST /api/v1/migrations/{migration_id}/start
```

The backend then decides whether to continue automatically, wait for review, or push to the mock target. Review resolution calls the backend, and the UI asks the backend workflow to continue instead of manually bypassing the agent flow.

Review resolution is the resume trigger:

```text
POST /api/v1/escalations/{escalation_id}/resolve
  -> apply human decision
  -> Command(resume={...})
  -> same migration_id/thread_id continues from the checkpoint
```

## Autonomy Boundary

The system uses a central autonomy policy with three outcomes:

- `AUTO`: safe to continue without human review.
- `HITL`: pause for a human because the system found ambiguity or unresolved validation risk.
- `STOP`: configuration/system problem that should not continue automatically.

AI helps with semantic work: fuzzy source-to-target field mapping, candidate reasoning, alternatives, and human-readable explanations. Deterministic Python handles parsing, cleanup, reconciliation, validation, retry, idempotency, rollback, audit logging, and workflow state.

HITL exists only for genuine uncertainty: mapping ambiguity, inherently ambiguous dates, source conflicts, duplicate conflicts, repeated validation failure, unsupported transformations, low-confidence transformations, or system failures. Confidence alone is not the rule; the policy also considers candidate separation, schema/type fit, value ambiguity, and business constraints.

## Delta Beyond AI

This is not just an LLM wrapper. The engineering layer provides source lineage, deterministic cleanup, schema validation, conflict detection, policy-based escalation, backend masking, durable audit events, idempotent target pushes, retry behavior for transient failures, rollback, and operator-friendly review.

## Local Commands

### Setup

Create/activate the Python environment and install dependencies if needed:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e backend
```

Install frontend dependencies:

```bash
cd frontend
npm install
```

Copy environment defaults if needed:

```bash
cp .env.example .env
```

Authentication is disabled for the local demo by default.

### Run Backend

```bash
cd backend
../.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### Run Frontend

```bash
cd frontend
npm run dev
```

Open the Vite URL printed by the frontend, usually:

```text
http://127.0.0.1:5173
```

### Verification

```bash
cd backend
../.venv/bin/python -m pytest

cd ../frontend
npm run build
```

Generate manual Excel fixtures:

```bash
.venv/bin/python scripts/generate_manual_fixtures.py
```

## Submission Notes

- Source code: this repository contains backend, frontend, docs, sample data, and scripts.
- Short write-up: see docs/CORE_LOGIC AND FUTURE_SCOPE



Useful manual test folders:

- sample_data/testdata

The production workflow uses LangGraph for orchestration. Upload/profile remains outside the graph because files and column profiles are persisted before workflow start.
