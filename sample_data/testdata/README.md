# Acceptance Criteria 3 Demo Data

This pack is built to demonstrate the assignment's third acceptance criterion:

> Defensible escalation boundary: escalate only when the agent is genuinely unsure.

Use these three files together:

- `employees_master.xlsx`
- `employee_contacts.xlsx`
- `employee_payroll.xlsx`

## Expected Flow

1. Upload all three files.
2. Click **Start processing**.
3. The workflow should stop at a **mapping review** before records are canonicalized.
4. Resolve the mapping review:
   - Source column: `contact_value`
   - Correct target field: `email`
5. The workflow should resume automatically.
6. The workflow should then stop at a **data review** for one employee.
7. Resolve the data review:
   - Employee: `E6103`
   - Field: `annual_salary`
   - Problem value: `not disclosed`
   - Correct it to a numeric value such as `1050000`
8. After the data review is resolved, the graph resumes and pushes the valid records to the mock target.

## Why These Two Cases Matter

### Case 1: Mapping Ambiguity

`contact_value` contains email-like values, but the column name itself is generic. The agent should not silently decide whether this is `email`, `phone`, or another contact field. It should ask a human once at the column-mapping level.

This is not per employee. It is one review for the source column.

### Case 2: Data Cleaning Failure

`E6103` has `annual_salary = not disclosed`.

The field mapping is clear, but the value cannot be safely cleaned into a number. The agent should not guess a salary. It should ask a human to correct, approve, reject, or send the case to HR.

This is per employee record because the bad value belongs to one employee.
