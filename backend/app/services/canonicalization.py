import json
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.constants import SOURCE_PRECEDENCE
from app.core.enums import AuditActorType, MappingDecision, ValidationStatus
from app.models.canonical_record import CanonicalRecord
from app.models.mapping import Mapping
from app.models.source_file import SourceFile
from app.schemas.audit import AuditEventCreate
from app.services.audit import AuditService
from app.services.cleaning import clean_value
from app.services.ingestion import read_tabular_file
from app.services.repair import ValidationRepairService
from app.services.validation import ValidationService


class CanonicalizationService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.audit = AuditService(db)
        self.validation = ValidationService()
        self.repair = ValidationRepairService()

    def canonicalize(self, migration_id: str) -> list[CanonicalRecord]:
        mappings = self._approved_mappings(migration_id)
        source_files = self._source_files(migration_id)
        rows = self._mapped_rows(migration_id, source_files, mappings)
        merged = self._merge_rows(migration_id, rows)
        self._detect_numeric_outliers(merged)

        records: list[CanonicalRecord] = []
        for item in merged.values():
            status, validation_issues = self.validation.validate(item["data"])
            validation_attempts = 1
            repair_issues: list[dict[str, object]] = []
            if status != ValidationStatus.VALID:
                validation_attempts = 2
                repaired_data, repair_issues = self.repair.repair(item["data"])
                repaired_status, repaired_validation_issues = self.validation.validate(repaired_data)
                if repaired_status == ValidationStatus.VALID:
                    item["data"] = repaired_data
                    status = repaired_status
                    validation_issues = []
                else:
                    item["data"] = repaired_data
                    validation_issues = repaired_validation_issues
                self.audit.append(
                    AuditEventCreate(
                        migration_id=migration_id,
                        actor_type=AuditActorType.SYSTEM,
                        event_type="VALIDATION_REPAIR_ATTEMPTED",
                        entity_type="canonical_record",
                        metadata={
                            "employee_id": item["data"].get("employee_id"),
                            "repair_issues": repair_issues,
                            "result": status,
                        },
                    )
                )
            issues = item["issues"] + validation_issues
            if issues and status == ValidationStatus.VALID:
                status = ValidationStatus.NEEDS_REVIEW

            record = CanonicalRecord(
                migration_id=migration_id,
                employee_id=item["data"].get("employee_id"),
                data_json=_dump_json(item["data"]),
                provenance_json=_dump_json(item["provenance"]),
                validation_status=status,
                validation_attempts=validation_attempts,
                issues_json=_dump_json(issues),
            )
            self.db.add(record)
            records.append(record)

        self.db.flush()
        return records

    def _approved_mappings(self, migration_id: str) -> dict[tuple[str, str], str]:
        statement = select(Mapping).where(
            Mapping.migration_id == migration_id,
            Mapping.target_field.is_not(None),
            Mapping.decision.in_(
                [
                    MappingDecision.AUTO_APPROVED,
                    MappingDecision.MANUALLY_APPROVED,
                    MappingDecision.MANUALLY_CORRECTED,
                ]
            ),
        )
        return {
            (mapping.source_file_id, mapping.source_column): mapping.target_field
            for mapping in self.db.scalars(statement)
            if mapping.target_field is not None
        }

    def _source_files(self, migration_id: str) -> list[SourceFile]:
        return list(
            self.db.scalars(
                select(SourceFile)
                .where(SourceFile.migration_id == migration_id)
                .order_by(SourceFile.original_name)
            )
        )

    def _mapped_rows(
        self,
        migration_id: str,
        source_files: list[SourceFile],
        mappings: dict[tuple[str, str], str],
    ) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for source_file in source_files:
            sheets = read_tabular_file(Path(source_file.stored_path), f".{source_file.file_type}")
            for sheet_name, frame in sheets.items():
                for row_index, row in frame.iterrows():
                    data: dict[str, object] = {}
                    provenance: dict[str, dict[str, object]] = {}
                    issues: list[dict[str, object]] = []
                    for source_column, raw_value in row.items():
                        target_field = mappings.get((source_file.id, str(source_column)))
                        if target_field is None:
                            continue
                        cleaned, clean_issues = clean_value(target_field, raw_value)
                        if cleaned is None and raw_value not in ("", None):
                            issues.extend(clean_issues)
                            continue
                        source_provenance = {
                            "source_file": source_file.original_name,
                            "source_column": str(source_column),
                            "source_row": int(row_index) + 2,
                            "sheet_name": sheet_name,
                            "original_value": "" if raw_value is None else str(raw_value),
                            "cleaned_value": cleaned,
                        }
                        _assign_mapped_value(data, provenance, issues, target_field, cleaned, source_provenance)
                        issues.extend(clean_issues)
                    if data:
                        rows.append({"data": data, "provenance": provenance, "issues": issues})

                        if issues:
                            self.audit.append(
                                AuditEventCreate(
                                    migration_id=migration_id,
                                    actor_type=AuditActorType.SYSTEM,
                                    event_type="VALUE_TRANSFORM_ISSUE",
                                    entity_type="source_row",
                                    metadata={"issues": issues},
                                )
                            )
        return rows

    def _merge_rows(
        self,
        migration_id: str,
        rows: list[dict[str, object]],
    ) -> dict[str, dict[str, object]]:
        merged: dict[str, dict[str, object]] = {}
        for row in rows:
            data = row["data"]
            employee_id = data.get("employee_id")
            key = str(employee_id) if employee_id else f"missing-key-{len(merged)}"
            if key not in merged:
                merged[key] = {"data": {}, "provenance": {}, "issues": []}
            elif _is_exact_duplicate(merged[key]["data"], data):
                _merge_duplicate_provenance(merged[key], row)
                self.audit.append(
                    AuditEventCreate(
                        migration_id=migration_id,
                        actor_type=AuditActorType.SYSTEM,
                        event_type="EXACT_DUPLICATE_REMOVED",
                        entity_type="source_row",
                        metadata={"employee_id": key},
                    )
                )
                continue

            target = merged[key]
            for field, value in data.items():
                if value is None:
                    continue
                if field not in target["data"] or target["data"][field] in (None, ""):
                    target["data"][field] = value
                    target["provenance"][field] = row["provenance"][field]
                    continue

                if target["data"][field] == value:
                    preferred_provenance = _prefer_provenance_by_precedence(
                        field,
                        target["provenance"][field],
                        row["provenance"][field],
                    )
                    if preferred_provenance is not None:
                        target["provenance"][field] = preferred_provenance
                    continue

                chosen = _choose_by_precedence(
                    field,
                    target["data"][field],
                    target["provenance"][field],
                    value,
                    row["provenance"][field],
                )
                if chosen is None:
                    target["issues"].append(
                        {
                            "type": "SOURCE_VALUE_CONFLICT",
                            "field": field,
                            "existing": str(target["data"][field]),
                            "incoming": str(value),
                            "existing_source": target["provenance"][field],
                            "incoming_source": row["provenance"][field],
                        }
                    )
                else:
                    target["data"][field] = chosen["value"]
                    target["provenance"][field] = chosen["provenance"]
                    self.audit.append(
                        AuditEventCreate(
                            migration_id=migration_id,
                            actor_type=AuditActorType.SYSTEM,
                            event_type="CONFLICT_RESOLVED_BY_PRECEDENCE",
                            entity_type="canonical_field",
                            metadata={"field": field},
                        )
                    )

            target["issues"].extend(row["issues"])

        return merged

    def _detect_numeric_outliers(self, merged: dict[str, dict[str, object]]) -> None:
        for field in ("annual_salary", "hike_percentage"):
            self._detect_numeric_outliers_for_field(merged, field)

    def _detect_numeric_outliers_for_field(
        self,
        merged: dict[str, dict[str, object]],
        field: str,
    ) -> None:
        numeric_items = [
            (key, item["data"][field])
            for key, item in merged.items()
            if isinstance(item["data"].get(field), Decimal)
        ]
        if len(numeric_items) < 4:
            return

        values = sorted(value for _, value in numeric_items)
        q1 = values[len(values) // 4]
        q3 = values[(len(values) * 3) // 4]
        iqr = q3 - q1
        upper = q3 + (iqr * Decimal("1.5"))
        lower = q1 - (iqr * Decimal("1.5"))

        for key, value in numeric_items:
            if value < lower or value > upper:
                merged[key]["issues"].append(
                    {
                        "type": "NUMERIC_OUTLIER",
                        "field": field,
                        "value": str(value),
                    }
                )


def _choose_by_precedence(
    field: str,
    existing_value: object,
    existing_provenance: dict[str, object],
    incoming_value: object,
    incoming_provenance: dict[str, object],
) -> dict[str, object] | None:
    precedence = SOURCE_PRECEDENCE.get(field)
    if not precedence:
        return None

    existing_source = str(existing_provenance.get("source_file"))
    incoming_source = str(incoming_provenance.get("source_file"))
    if existing_source not in precedence or incoming_source not in precedence:
        return None

    if existing_source == incoming_source:
        return None

    if precedence.index(incoming_source) < precedence.index(existing_source):
        return {"value": incoming_value, "provenance": incoming_provenance}
    return {"value": existing_value, "provenance": existing_provenance}


def _prefer_provenance_by_precedence(
    field: str,
    existing_provenance: dict[str, object],
    incoming_provenance: dict[str, object],
) -> dict[str, object] | None:
    precedence = SOURCE_PRECEDENCE.get(field)
    if not precedence:
        return None

    existing_source = str(existing_provenance.get("source_file"))
    incoming_source = str(incoming_provenance.get("source_file"))
    if existing_source not in precedence or incoming_source not in precedence:
        return None

    if precedence.index(incoming_source) < precedence.index(existing_source):
        return incoming_provenance
    return None


def _merge_duplicate_provenance(
    target: dict[str, object],
    row: dict[str, object],
) -> None:
    target_provenance = target["provenance"]
    row_provenance = row["provenance"]
    if not isinstance(target_provenance, dict) or not isinstance(row_provenance, dict):
        return

    for field in row["data"]:
        if field not in target_provenance or field not in row_provenance:
            continue
        preferred = _prefer_provenance_by_precedence(
            field,
            target_provenance[field],
            row_provenance[field],
        )
        if preferred is not None:
            target_provenance[field] = preferred


def _assign_mapped_value(
    data: dict[str, object],
    provenance: dict[str, dict[str, object]],
    issues: list[dict[str, object]],
    target_field: str,
    cleaned_value: object,
    source_provenance: dict[str, object],
) -> None:
    if target_field not in data or data[target_field] in (None, ""):
        data[target_field] = cleaned_value
        provenance[target_field] = source_provenance
        return

    if data[target_field] == cleaned_value:
        return

    issues.append(
        {
            "type": "SOURCE_VALUE_CONFLICT",
            "field": target_field,
            "existing": str(data[target_field]),
            "incoming": str(cleaned_value),
            "existing_source": provenance[target_field],
            "incoming_source": source_provenance,
            "reason": "Two source columns in the same row mapped to the same target field with different values.",
        }
    )


def _is_exact_duplicate(existing_data: dict[str, object], incoming_data: dict[str, object]) -> bool:
    return bool(incoming_data) and all(
        field in existing_data and existing_data[field] == value
        for field, value in incoming_data.items()
    )


def _dump_json(value: object) -> str:
    return json.dumps(value, default=str, separators=(",", ":"), sort_keys=True)
