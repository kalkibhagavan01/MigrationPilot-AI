# Sample Data Scenarios

These files are intentionally small and scenario-driven for the MVP demo.

## Files

- `employees_master.csv`: core identity and employment data
- `employee_contacts.xlsx`: contact data and duplicate/contact cleanup scenarios
- `employee_payroll.csv`: compensation, sensitive data, source conflicts, and target retry scenario

## Scenarios Covered

1. Exact field mapping: straightforward fields such as employee identifiers.
2. Semantic field mapping: `Emp No`, `employee_code`, `worker_id`, `DOB`, `annual_ctc`.
3. Mixed date normalization: explicit date formats across master/payroll files.
4. Whitespace/email cleanup: extra spaces in names and uppercase emails.
5. Exact duplicate: duplicate contact row for `E006`.
6. Cross-file department conflict: `E004` is Engineering in master and Finance in payroll.
7. Ambiguous start-date mapping: `start_dt` and ambiguous date strings such as `04/05/2021`.
8. Missing required field: `E005` has no joining/start date.
9. Salary outlier: `E-FAIL-503` has intentionally extreme compensation.
10. Compensation-manager routing: salary, hike, pay frequency, and bank account fields.
11. Unmapped source field: `blood_group` in payroll.
12. Target API retry/rollback: `E-FAIL-503` is reserved for synthetic `503` retry behavior.

## Source Precedence

The Phase 0 config treats:

- `employees_master.csv` as authoritative for identity and core employment fields
- `employee_contacts.xlsx` as authoritative for email and phone
- `employee_payroll.csv` as authoritative for compensation/payroll fields
