import json
from pathlib import Path

from openpyxl import Workbook


ROOT = Path(__file__).resolve().parents[1]
MANUAL_DIR = ROOT / "sample_data" / "manual_testing"
HAPPY_PATH_DIR = MANUAL_DIR / "happy_path"
REVIEW_CASES_DIR = MANUAL_DIR / "review_cases"

HAPPY_EMPLOYEES = [
    {
        "employee_id": "E1001",
        "full_name": "Asha Rao",
        "email": "asha.rao@example.com",
        "phone": "+91 98765 11001",
        "date_of_birth": "1992-03-14",
        "joining_date": "2021-04-05",
        "department": "Engineering",
        "location": "Bengaluru",
        "employment_type": "PERMANENT",
        "manager_id": "E1003",
        "annual_salary": "1800000",
        "hike_percentage": "12",
        "currency": "INR",
        "pay_frequency": "ANNUAL",
        "bank_account_number": "111122223333",
        "tax_identifier": "PANASHA1001",
    },
    {
        "employee_id": "E1002",
        "full_name": "Rohan Mehta",
        "email": "rohan.mehta@example.com",
        "phone": "+91 98765 11002",
        "date_of_birth": "1989-11-22",
        "joining_date": "2020-01-15",
        "department": "Finance",
        "location": "Mumbai",
        "employment_type": "PERMANENT",
        "manager_id": "E1003",
        "annual_salary": "1650000",
        "hike_percentage": "9",
        "currency": "INR",
        "pay_frequency": "ANNUAL",
        "bank_account_number": "222233334444",
        "tax_identifier": "PANROHAN1002",
    },
    {
        "employee_id": "E1003",
        "full_name": "Meera Iyer",
        "email": "meera.iyer@example.com",
        "phone": "+91 98765 11003",
        "date_of_birth": "1984-07-09",
        "joining_date": "2018-08-20",
        "department": "Engineering",
        "location": "Bengaluru",
        "employment_type": "PERMANENT",
        "manager_id": "",
        "annual_salary": "2500000",
        "hike_percentage": "10",
        "currency": "INR",
        "pay_frequency": "ANNUAL",
        "bank_account_number": "333344445555",
        "tax_identifier": "PANMEERA1003",
    },
]

REVIEW_EMPLOYEES = [
    {
        "employee_id": "E2001",
        "full_name": "Anika Sen",
        "email": "anika.sen@example.com",
        "phone": "+91 98765 22001",
        "date_of_birth": "1991-08-11",
        "joining_date": "2021-04-05",
        "department": "Engineering",
        "location": "Bengaluru",
        "employment_type": "PERMANENT",
        "manager_id": "E2005",
        "annual_salary": "1800000",
        "hike_percentage": "11",
        "currency": "INR",
        "pay_frequency": "ANNUAL",
        "bank_account_number": "444455556666",
        "tax_identifier": "PANANIKA2001",
        "legacy_grade_code": "G7",
        "cafeteria_plan": "North",
    },
    {
        "employee_id": "E2002",
        "full_name": "Vikram Das",
        "email": "vikram.das@example.com",
        "phone": "+91 98765 22002",
        "date_of_birth": "1988-12-03",
        "joining_date": "04/05/2021",
        "department": "Finance",
        "location": "Mumbai",
        "employment_type": "PERMANENT",
        "manager_id": "E2005",
        "annual_salary": "1700000",
        "hike_percentage": "9",
        "currency": "INR",
        "pay_frequency": "ANNUAL",
        "bank_account_number": "555566667777",
        "tax_identifier": "PANVIKRAM2002",
        "legacy_grade_code": "G6",
        "cafeteria_plan": "West",
    },
    {
        "employee_id": "E2003",
        "full_name": "Priya Nair",
        "email": "priya.nair@example.com",
        "phone": "+91 98765 22003",
        "date_of_birth": "1994-06-19",
        "joining_date": "",
        "department": "People Ops",
        "location": "Kochi",
        "employment_type": "PERMANENT",
        "manager_id": "E2005",
        "annual_salary": "1600000",
        "hike_percentage": "10",
        "currency": "INR",
        "pay_frequency": "ANNUAL",
        "bank_account_number": "666677778888",
        "tax_identifier": "PANPRIYA2003",
        "legacy_grade_code": "G6",
        "cafeteria_plan": "South",
    },
    {
        "employee_id": "E2004",
        "full_name": "Rahul Shah",
        "email": "rahul.shah@example.com",
        "phone": "+91 98765 22004",
        "date_of_birth": "1990-02-27",
        "joining_date": "2020-09-14",
        "department": "Sales",
        "location": "Delhi",
        "employment_type": "PERMANENT",
        "manager_id": "E2005",
        "annual_salary": "9800000",
        "hike_percentage": "12",
        "currency": "INR",
        "pay_frequency": "ANNUAL",
        "bank_account_number": "777788889999",
        "tax_identifier": "PANRAHUL2004",
        "legacy_grade_code": "G8",
        "cafeteria_plan": "North",
    },
    {
        "employee_id": "E2005",
        "full_name": "Sara Khan",
        "email": "sara.khan@example.com",
        "phone": "+91 98765 22005",
        "date_of_birth": "1982-01-10",
        "joining_date": "2017-02-01",
        "department": "Engineering",
        "location": "Bengaluru",
        "employment_type": "PERMANENT",
        "manager_id": "",
        "annual_salary": "2200000",
        "hike_percentage": "60",
        "currency": "INR",
        "pay_frequency": "ANNUAL",
        "bank_account_number": "888899990000",
        "tax_identifier": "PANSARA2005",
        "legacy_grade_code": "G9",
        "cafeteria_plan": "HQ",
    },
]


def main() -> None:
    write_fixture_pack(HAPPY_PATH_DIR, HAPPY_EMPLOYEES)
    write_expected_target(HAPPY_PATH_DIR, HAPPY_EMPLOYEES)
    write_happy_readme()

    write_fixture_pack(
        REVIEW_CASES_DIR,
        REVIEW_EMPLOYEES,
        duplicate_employee_id=True,
        include_unmapped_columns=True,
    )
    write_review_expectations()
    write_review_readme()


def write_fixture_pack(
    output_dir: Path,
    employees: list[dict[str, str]],
    *,
    duplicate_employee_id: bool = False,
    include_unmapped_columns: bool = False,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    master_rows = list(employees)
    if duplicate_employee_id:
        duplicate = dict(employees[3])
        duplicate["department"] = "Revenue Operations"
        duplicate["location"] = "Gurugram"
        master_rows.append(duplicate)

    master_columns = [
        "employee_id",
        "full_name",
        "date_of_birth",
        "joining_date",
        "department",
        "location",
        "employment_type",
        "manager_id",
    ]
    if include_unmapped_columns:
        master_columns.extend(["legacy_grade_code", "cafeteria_plan"])

    write_workbook(
        output_dir,
        "employees_master.xlsx",
        "employees_master",
        master_columns,
        master_rows,
    )
    write_workbook(
        output_dir,
        "employee_contacts.xlsx",
        "employee_contacts",
        ["employee_id", "email", "phone"],
        employees,
    )
    write_workbook(
        output_dir,
        "employee_payroll.xlsx",
        "employee_payroll",
        [
            "employee_id",
            "annual_salary",
            "hike_percentage",
            "currency",
            "pay_frequency",
            "bank_account_number",
            "tax_identifier",
        ],
        employees,
    )


def write_expected_target(output_dir: Path, employees: list[dict[str, str]]) -> None:
    expected = []
    for employee in employees:
        target = dict(employee)
        target.pop("legacy_grade_code", None)
        target.pop("cafeteria_plan", None)
        if target["manager_id"] == "":
            target["manager_id"] = None
        expected.append(target)

    (output_dir / "expected_target.json").write_text(
        json.dumps(expected, indent=2) + "\n",
        encoding="utf-8",
    )


def write_review_expectations() -> None:
    expectations = {
        "mapping_review_columns": ["legacy_grade_code", "cafeteria_plan"],
        "data_review_cases": [
            {
                "employee_id": "E2002",
                "field": "joining_date",
                "issue": "Ambiguous date: 04/05/2021 can mean 4 May or 5 April.",
            },
            {
                "employee_id": "E2003",
                "field": "joining_date",
                "issue": "Missing required joining date.",
            },
            {
                "employee_id": "E2004",
                "field": "department/location",
                "issue": "Same employee ID appears twice with conflicting master data.",
            },
            {
                "employee_id": "E2004",
                "field": "annual_salary",
                "issue": "Salary is much higher than the rest of the uploaded employees.",
            },
            {
                "employee_id": "E2005",
                "field": "hike_percentage",
                "issue": "Hike percentage is much higher than the rest of the uploaded employees.",
            },
        ],
    }
    (REVIEW_CASES_DIR / "expected_review_cases.json").write_text(
        json.dumps(expectations, indent=2) + "\n",
        encoding="utf-8",
    )


def write_happy_readme() -> None:
    (HAPPY_PATH_DIR / "README.md").write_text(
        "# Happy Path Manual Test Data\n\n"
        "Upload these three Excel files together in the UI:\n\n"
        "- `employees_master.xlsx`\n"
        "- `employee_contacts.xlsx`\n"
        "- `employee_payroll.xlsx`\n\n"
        "Expected target records are in `expected_target.json`.\n",
        encoding="utf-8",
    )


def write_review_readme() -> None:
    (REVIEW_CASES_DIR / "README.md").write_text(
        "# Review Cases Manual Test Data\n\n"
        "Upload these three Excel files together in the UI:\n\n"
        "- `employees_master.xlsx`\n"
        "- `employee_contacts.xlsx`\n"
        "- `employee_payroll.xlsx`\n\n"
        "This pack intentionally creates:\n\n"
        "- 2 mapping review columns: `legacy_grade_code`, `cafeteria_plan`\n"
        "- 1 ambiguous date: employee `E2002`\n"
        "- 1 empty required value: employee `E2003` missing `joining_date`\n"
        "- 1 duplicate employee ID conflict: employee `E2004`\n"
        "- 1 salary outlier: employee `E2004`\n"
        "- 1 hike outlier: employee `E2005`\n\n"
        "A machine-readable checklist is in `expected_review_cases.json`.\n",
        encoding="utf-8",
    )


def write_workbook(
    output_dir: Path,
    file_name: str,
    sheet_name: str,
    columns: list[str],
    rows: list[dict[str, str]],
) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = sheet_name
    sheet.append(columns)
    for row in rows:
        sheet.append([row[column] for column in columns])
    workbook.save(output_dir / file_name)


if __name__ == "__main__":
    main()
