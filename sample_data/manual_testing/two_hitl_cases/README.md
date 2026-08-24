# Two HITL Cases Manual Test Data

Upload these three Excel files together in the UI:

- `employees_master.xlsx`
- `employee_contacts.xlsx`
- `employee_payroll.xlsx`

This pack is intentionally small and should create exactly two human review cards:

- `E5001`: data cleaning issue. `annual_salary` is `not disclosed`, which the cleaner cannot safely convert to a number.
- `E5002`: same-target source conflict. `email` and `mail_id` both map to target `email`, but the values are different.

Expected result after start:

- workflow status: `WAITING_FOR_REVIEW`
- canonical records: `5`
- open reviews: `2`
- pushed records: `0`
