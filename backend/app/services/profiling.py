import json
import re

import pandas as pd
from sqlalchemy.orm import Session

from app.models.column_profile import ColumnProfile
from app.models.source_file import SourceFile

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_RE = re.compile(r"^\+?[\d\s().-]{7,}$")


class ProfilingService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def profile_dataset(
        self,
        source_file: SourceFile,
        sheets: dict[str | None, pd.DataFrame],
    ) -> list[ColumnProfile]:
        profiles: list[ColumnProfile] = []
        for sheet_name, frame in sheets.items():
            for column_name in frame.columns:
                profile = _profile_column(frame[column_name])
                column_profile = ColumnProfile(
                    source_file_id=source_file.id,
                    sheet_name=sheet_name,
                    column_name=str(column_name),
                    normalized_name=_normalize_name(str(column_name)),
                    inferred_type=profile["inferred_type"],
                    null_ratio=profile["null_ratio"],
                    unique_ratio=profile["unique_ratio"],
                    sample_values_json=json.dumps(profile["sample_values"]),
                    profile_json=json.dumps(profile, sort_keys=True),
                )
                self.db.add(column_profile)
                profiles.append(column_profile)

        self.db.flush()
        return profiles


def _profile_column(series: pd.Series) -> dict[str, object]:
    values = series.astype(str).map(str.strip)
    non_null = values[values != ""]
    row_count = int(len(values))
    null_count = int(row_count - len(non_null))
    unique_count = int(non_null.nunique())
    numeric_values = pd.to_numeric(non_null, errors="coerce")
    parsed_dates = pd.to_datetime(non_null, errors="coerce", format="mixed")

    email_ratio = _match_ratio(non_null, EMAIL_RE)
    phone_ratio = _match_ratio(non_null, PHONE_RE)
    numeric_ratio = _valid_ratio(numeric_values)
    date_parse_ratio = _valid_ratio(parsed_dates)

    profile: dict[str, object] = {
        "inferred_type": _infer_type(email_ratio, phone_ratio, numeric_ratio, date_parse_ratio),
        "row_count": row_count,
        "null_count": null_count,
        "null_ratio": _ratio(null_count, row_count),
        "unique_count": unique_count,
        "unique_ratio": _ratio(unique_count, max(len(non_null), 1)),
        "sample_values": non_null.drop_duplicates().head(5).tolist(),
        "date_parse_ratio": date_parse_ratio,
        "email_parse_ratio": email_ratio,
        "phone_parse_ratio": phone_ratio,
    }

    if numeric_ratio > 0 and numeric_values.notna().any():
        profile["minimum"] = float(numeric_values.min())
        profile["maximum"] = float(numeric_values.max())
        profile["mean"] = float(numeric_values.mean())
        profile["median"] = float(numeric_values.median())

    return profile


def _normalize_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")


def _infer_type(
    email_ratio: float,
    phone_ratio: float,
    numeric_ratio: float,
    date_parse_ratio: float,
) -> str:
    if email_ratio >= 0.8:
        return "email"
    if date_parse_ratio >= 0.8:
        return "date"
    if numeric_ratio >= 0.8:
        return "number"
    if phone_ratio >= 0.8:
        return "phone"
    return "string"


def _ratio(count: int, total: int) -> float:
    if total == 0:
        return 0.0
    return round(count / total, 4)


def _valid_ratio(series: pd.Series) -> float:
    if len(series.index) == 0:
        return 0.0
    return round(float(series.notna().mean()), 4)


def _match_ratio(values: pd.Series, pattern: re.Pattern[str]) -> float:
    if len(values.index) == 0:
        return 0.0
    return round(float(values.map(lambda value: bool(pattern.match(value))).mean()), 4)
