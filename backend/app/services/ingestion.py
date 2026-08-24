import hashlib
from pathlib import Path

import pandas as pd
from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.core.constants import (
    MAX_COMBINED_ROWS,
    MAX_FILES_PER_MIGRATION,
    MAX_FILE_SIZE_BYTES,
    SUPPORTED_SOURCE_EXTENSIONS,
)
from app.core.errors import AppError
from app.models.source_file import SourceFile


class IngestedDataset:
    def __init__(self, source_file: SourceFile, sheets: dict[str | None, pd.DataFrame]) -> None:
        self.source_file = source_file
        self.sheets = sheets


class IngestionService:
    def __init__(self, db: Session, storage_dir: str) -> None:
        self.db = db
        self.storage_dir = Path(storage_dir)

    async def ingest(self, migration_id: str, files: list[UploadFile]) -> list[IngestedDataset]:
        if not files:
            raise AppError("NO_FILES", "At least one file is required.", 400)

        if len(files) > MAX_FILES_PER_MIGRATION:
            raise AppError("DATASET_LIMIT_EXCEEDED", "Too many files uploaded.", 413)

        self.storage_dir.mkdir(parents=True, exist_ok=True)
        datasets: list[IngestedDataset] = []
        total_rows = 0

        for upload in files:
            original_name = Path(upload.filename or "").name
            extension = Path(original_name).suffix.lower()
            if extension not in SUPPORTED_SOURCE_EXTENSIONS:
                raise AppError("UNSUPPORTED_FILE_TYPE", "Only CSV and XLSX files are supported.", 415)

            content = await upload.read()
            if len(content) > MAX_FILE_SIZE_BYTES:
                raise AppError("FILE_TOO_LARGE", "File exceeds the 10 MB limit.", 413)

            checksum = hashlib.sha256(content).hexdigest()
            stored_path = self.storage_dir / f"{migration_id}_{checksum[:12]}{extension}"
            stored_path.write_bytes(content)

            sheets = read_tabular_file(stored_path, extension)
            row_count = sum(len(frame.index) for frame in sheets.values())
            total_rows += row_count
            if total_rows > MAX_COMBINED_ROWS:
                raise AppError("DATASET_LIMIT_EXCEEDED", "Combined row limit exceeded.", 413)

            source_file = SourceFile(
                migration_id=migration_id,
                original_name=original_name,
                stored_path=str(stored_path),
                file_type=extension.lstrip("."),
                size_bytes=len(content),
                checksum_sha256=checksum,
                row_count=row_count,
            )
            self.db.add(source_file)
            self.db.flush()
            datasets.append(IngestedDataset(source_file=source_file, sheets=sheets))

        return datasets


def read_tabular_file(path: Path, extension: str) -> dict[str | None, pd.DataFrame]:
    try:
        if extension == ".csv":
            frame = pd.read_csv(path, dtype=str, keep_default_na=False)
            if frame.empty and len(frame.columns) == 0:
                raise AppError("INVALID_WORKBOOK", "CSV file is empty.", 422)
            return {None: frame}

        workbook = pd.read_excel(path, dtype=str, keep_default_na=False, sheet_name=None)
        if not workbook:
            raise AppError("INVALID_WORKBOOK", "Workbook has no readable sheets.", 422)
        return dict(workbook)
    except AppError:
        raise
    except Exception as exc:
        raise AppError("INVALID_WORKBOOK", "Could not parse uploaded file.", 422) from exc
