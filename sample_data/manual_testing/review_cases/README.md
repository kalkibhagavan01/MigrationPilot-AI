# Review Cases Manual Test Data

Upload these three Excel files together in the UI:

- `employees_master.xlsx`
- `employee_contacts.xlsx`
- `employee_payroll.xlsx`

This pack intentionally creates:

- 3 data review conflicts where two source columns map to the same target field but contain different values
- no date ambiguity cases
- no missing required-field cases
- no random/unrelated source columns

Conflict scenarios:

- `E4001`: `department` and `dept_name` both map to target `department`, but disagree.
- `E4002`: `email` and `mail_id` both map to target `email`, but disagree.
- `E4003`: `annual_salary` and `annual_ctc` both map to target `annual_salary`, but disagree.

A machine-readable checklist is in `expected_review_cases.json`.
