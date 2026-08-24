from decimal import Decimal

from app.core.enums import DataClassification, UserRole

AUTO_MAPPING_MIN_SCORE = Decimal("0.85")
AUTO_MAPPING_MIN_GAP = Decimal("0.10")
AUTO_MAPPING_MIN_TYPE_SCORE = Decimal("0.80")

MAX_GRAPH_TRANSITIONS = 50
MAX_NODE_VISITS = 3
MAX_VALIDATION_REPAIR_ATTEMPTS = 2
MAX_TARGET_PUSH_ATTEMPTS = 3
MAX_STRUCTURED_LLM_ATTEMPTS = 2

MAX_FILES_PER_MIGRATION = 5
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024
MAX_COMBINED_ROWS = 10_000
SUPPORTED_SOURCE_EXTENSIONS = frozenset({".csv", ".xlsx"})

TARGET_FIELD_TYPES: dict[str, str] = {
    "employee_id": "string",
    "full_name": "string",
    "email": "email",
    "phone": "phone",
    "date_of_birth": "date",
    "joining_date": "date",
    "department": "string",
    "location": "string",
    "employment_type": "string",
    "manager_id": "string",
    "annual_salary": "number",
    "hike_percentage": "number",
    "currency": "string",
    "pay_frequency": "string",
    "bank_account_number": "string",
    "tax_identifier": "string",
}

TARGET_FIELD_DESCRIPTIONS: dict[str, str] = {
    "employee_id": "Unique employee identifier.",
    "full_name": "Employee full legal or display name.",
    "email": "Employee email address.",
    "phone": "Employee phone or mobile number.",
    "date_of_birth": "Employee date of birth.",
    "joining_date": "Employee joining or start date.",
    "department": "Employee department.",
    "location": "Employee work location.",
    "employment_type": "Employment type such as permanent, contract, intern, or temporary.",
    "manager_id": "Employee identifier of the manager.",
    "annual_salary": "Annual salary or compensation amount.",
    "hike_percentage": "Salary hike percentage.",
    "currency": "Three-letter compensation currency code.",
    "pay_frequency": "Salary pay frequency.",
    "bank_account_number": "Payroll bank account number.",
    "tax_identifier": "Tax or statutory identifier.",
}

SOURCE_FIELD_SYNONYMS: dict[str, str] = {
    "emp_no": "employee_id",
    "employee_code": "employee_id",
    "worker_id": "employee_id",
    "employee_name": "full_name",
    "full_name": "full_name",
    "dob": "date_of_birth",
    "doj": "joining_date",
    "start_date": "joining_date",
    "mail_id": "email",
    "mobile_number": "phone",
    "dept": "department",
    "dept_name": "department",
    "annual_ctc": "annual_salary",
    "hike": "hike_percentage",
    "bank_account": "bank_account_number",
}

RETRYABLE_TARGET_STATUSES = frozenset({408, 429, 500, 502, 503, 504})
PERMANENT_TARGET_STATUSES = frozenset({400, 409, 422})

SOURCE_PRECEDENCE: dict[str, list[str]] = {
    "employee_id": ["employees_master.csv", "employee_contacts.xlsx", "employee_payroll.csv"],
    "full_name": ["employees_master.csv", "employee_contacts.xlsx"],
    "email": ["employee_contacts.xlsx"],
    "phone": ["employee_contacts.xlsx"],
    "date_of_birth": ["employees_master.csv"],
    "joining_date": ["employees_master.csv", "employee_payroll.csv"],
    "department": ["employees_master.csv", "employee_payroll.csv"],
    "employment_type": ["employees_master.csv"],
    "manager_id": ["employees_master.csv"],
    "annual_salary": ["employee_payroll.csv"],
    "hike_percentage": ["employee_payroll.csv"],
    "currency": ["employee_payroll.csv"],
    "pay_frequency": ["employee_payroll.csv"],
    "bank_account_number": ["employee_payroll.csv"],
}

FIELD_POLICIES: dict[str, dict[str, str]] = {
    "employee_id": {
        "classification": DataClassification.INTERNAL,
        "required_role": UserRole.IMPLEMENTATION_CONSULTANT,
    },
    "full_name": {
        "classification": DataClassification.PERSONAL,
        "required_role": UserRole.IMPLEMENTATION_CONSULTANT,
    },
    "email": {
        "classification": DataClassification.PERSONAL,
        "required_role": UserRole.IMPLEMENTATION_CONSULTANT,
    },
    "phone": {
        "classification": DataClassification.PERSONAL,
        "required_role": UserRole.IMPLEMENTATION_CONSULTANT,
    },
    "date_of_birth": {
        "classification": DataClassification.PERSONAL_SENSITIVE,
        "required_role": UserRole.HR_DATA_STEWARD,
    },
    "annual_salary": {
        "classification": DataClassification.CONFIDENTIAL_COMPENSATION,
        "required_role": UserRole.COMPENSATION_MANAGER,
    },
    "hike_percentage": {
        "classification": DataClassification.CONFIDENTIAL_COMPENSATION,
        "required_role": UserRole.COMPENSATION_MANAGER,
    },
    "bank_account_number": {
        "classification": DataClassification.RESTRICTED_PAYROLL,
        "required_role": UserRole.PAYROLL_MANAGER,
    },
    "tax_identifier": {
        "classification": DataClassification.RESTRICTED_PAYROLL,
        "required_role": UserRole.PAYROLL_MANAGER,
    },
}
