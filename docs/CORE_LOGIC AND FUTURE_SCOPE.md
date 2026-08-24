# Short Write-Up

## Approach

MigrationPilot AI is a supervised HR data migration agent. It ingests CSV/XLSX exports, profiles source columns, maps them to a target employee schema, cleans and merges rows, validates canonical records, pauses for human review only when needed, and pushes valid records to a mock target system with retry, rollback, and audit.

The main architecture decision was to separate workflow ownership from business logic:

```text
FastAPI handles API requests.
LangGraph owns orchestration, checkpointing, interrupt, and resume.
Deterministic services handle parsing, cleaning, validation, retry, rollback, and audit.
The LLM is limited to column-mapping suggestions when configured.
Humans handle ambiguity, not every small operation.
```

This gives the agent autonomy without letting it freely mutate sensitive HR data. Raw files and records are persisted, but operator-facing APIs mask salary, DOB, phone, bank, tax, and similar fields by default.

## How I Decided What The Agent Handles Alone

The rule I used was: **the agent can act alone only when the decision is schema-safe, deterministic, reversible/idempotent, or high-confidence with clear evidence.** Otherwise it must pause or stop safely.

For column mapping, the system first tries deterministic mapping:

- exact target field match, such as `email -> email`
- configured synonym, such as `emp_no -> employee_id`
- type-compatible values from the column profile

If deterministic mapping is not enough and an LLM provider is configured, the LLM can suggest a target field. The LLM does not directly approve the mapping. Its suggestion is scored with deterministic checks:

```text
final score = semantic score + name score + type score + value score
```

The mapping is auto-approved only when:

- the target field exists in the target schema
- the final score is at least the auto-mapping threshold
- the winning target field has a clear gap over the next alternative
- the source value type is compatible with the target field type

If any of those checks fail, the mapping becomes HITL. For example, `employee_name -> full_name` can be automatic, but `legacy_grade_code` should not silently map to compensation or department without a reviewer.

For record processing, the agent handles safe operations alone:

- normalizing dates, emails, casing, and numeric formats
- removing exact duplicate rows
- merging records by employee ID
- resolving source conflicts when the configured source-precedence policy says which file wins
- retrying transient target failures using idempotency keys

These are appropriate for autonomy because they are deterministic and auditable.

## When The Agent Escalates

The agent escalates when continuing would require guessing business intent. Examples:

- no safe target field can be selected
- two mapping candidates are too close in confidence
- target field type does not match source values
- required target data is missing
- dates or values are ambiguous
- duplicate employees contain conflicting data
- salary or hike values are outliers
- validation still fails after bounded automatic repair

When this happens, LangGraph interrupts and stores the workflow checkpoint. The UI shows a review card with the reason, evidence, affected field/employee, recommended action, and actions to approve, correct, reject, or send to HR. After the reviewer resolves the card, the backend records the human decision in audit and resumes the same graph thread. The frontend does not manually run the next stages.

If the system has no safe path forward, for example all records are rejected and no valid record can be pushed, the agent marks the run as blocked/stopped safely instead of pretending the migration completed.

## Target Push, Retry, Rollback, And Audit

The mock target integration simulates a real HR API. Each valid record is pushed with an idempotency key, and each record gets its own result:

- `SUCCEEDED`
- `FAILED_RETRYABLE`
- `FAILED_PERMANENT`
- `ROLLED_BACK`

Retry applies only to retryable failures. Rollback removes target records created by that migration. Push preview shows what will change before the push, and rollback preview shows what would be removed before rollback. Every mapping decision, review decision, push attempt, retry, and rollback writes an audit event so the operator can explain what changed and why.

## What I Would Build Next

First, I would make target schemas, validation rules, source precedence, mapping thresholds, and escalation policies configurable per customer instead of code-defined.

Second, I would add role-based unmasking for sensitive fields. The current product masks sensitive values by default; the next step is controlled unmask with reason capture and audit.

Third, I would expand the simulation layer so the agent can compare source and target before execution, show field-level diffs, estimate risk, and produce a migration readiness report before any target write.

Finally, I would scale the workflow for larger customer datasets with batch processing, background workers, chunk-level checkpoints, stronger observability, and partial rollback strategies.
