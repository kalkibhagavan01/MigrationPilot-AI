from app.services.cleaning import clean_value


class ValidationRepairService:
    def repair(self, data: dict[str, object]) -> tuple[dict[str, object], list[dict[str, object]]]:
        repaired = dict(data)
        repair_events: list[dict[str, object]] = []

        for field, value in data.items():
            if value is None:
                continue
            cleaned, issues = clean_value(field, value)
            if issues or cleaned is None or cleaned == value:
                continue
            repaired[field] = cleaned
            repair_events.append(
                {
                    "type": "SAFE_REPAIR_APPLIED",
                    "field": field,
                    "old_value": str(value),
                    "new_value": str(cleaned),
                    "reason": "Deterministic cleanup before second validation.",
                }
            )

        return repaired, repair_events
