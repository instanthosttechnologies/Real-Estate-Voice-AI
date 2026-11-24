import csv
import io
import re
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Set, Tuple
import openpyxl

from app.services.ingestion.parsers.csv_excel import sanitize_cell_value

MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB
MAX_INSPECTION_ROWS = 100_000


def detect_data_type(values: List[Any]) -> str:
    """
    Infers the predominant data type from a sample of non-null cell values.
    Returns: 'integer', 'float', 'boolean', 'date', 'currency', 'url', 'text_short', 'text_long'
    Completely domain-agnostic.
    """
    if not values:
        return "text_short"

    int_count = 0
    float_count = 0
    bool_count = 0
    date_count = 0
    url_count = 0
    currency_count = 0
    total = len(values)

    for val in values:
        if isinstance(val, bool):
            bool_count += 1
            continue
        if isinstance(val, int):
            int_count += 1
            continue
        if isinstance(val, float):
            float_count += 1
            continue
        if isinstance(val, (datetime, date)):
            date_count += 1
            continue

        s = str(val).strip()
        # Null indicator check
        if s.lower() in ("null", "none", "n/a", "na", "", "-"):
            continue

        # URL check
        if re.match(r"^https?://[^\s]+$", s):
            url_count += 1
            continue

        # Currency check (e.g. ₹, $, €, £, ¥, or currency words)
        if re.search(r"[$€₹£¥]|\b(usd|eur|gbp|inr|cad|aud|jpy)\b", s, re.IGNORECASE):
            currency_count += 1
            continue

        # Numeric string check
        cleaned_num = s.replace(",", "")
        try:
            int(cleaned_num)
            int_count += 1
            continue
        except ValueError:
            pass
        try:
            float(cleaned_num)
            float_count += 1
            continue
        except ValueError:
            pass

    if total == 0:
        return "text_short"
    if int_count / total >= 0.70:
        return "integer"
    if (int_count + float_count) / total >= 0.70:
        return "float"
    if bool_count / total >= 0.70:
        return "boolean"
    if date_count / total >= 0.70:
        return "date"
    if url_count / total >= 0.60:
        return "url"
    if currency_count / total >= 0.50:
        return "currency"

    # Check length for text
    max_len = max(len(str(v)) for v in values)
    return "text_long" if max_len > 120 else "text_short"


def inspect_sheet_records(
    rows: List[Tuple[Any, ...]],
    sheet_name: str,
    max_rows: int = MAX_INSPECTION_ROWS,
) -> Dict[str, Any]:
    """
    Analyzes columns, types, null counts, candidate keys, and sample statistics for a single worksheet.
    Completely independent of business domain.
    """
    if not rows:
        return {
            "sheet_name": sheet_name,
            "total_rows": 0,
            "total_columns": 0,
            "columns": [],
            "candidate_identifiers": [],
            "records": [],
        }

    # Extract header row
    header_raw = rows[0]
    headers: List[str] = []
    seen_headers: Set[str] = set()

    for i, col in enumerate(header_raw):
        clean_col = str(col).strip() if col is not None else ""
        if not clean_col:
            clean_col = f"COLUMN_{i+1}"
        # Ensure unique column names in case of duplicate raw headers
        base_col = clean_col
        dup_counter = 1
        while clean_col in seen_headers:
            clean_col = f"{base_col}_{dup_counter}"
            dup_counter += 1
        seen_headers.add(clean_col)
        headers.append(clean_col)

    data_rows = rows[1:max_rows + 1]

    records: List[Dict[str, Any]] = []
    column_values: Dict[str, List[Any]] = {h: [] for h in headers}

    for row in data_rows:
        if not row or all(c is None or str(c).strip() == "" for c in row):
            continue
        row_dict: Dict[str, Any] = {}
        for col_idx, header in enumerate(headers):
            val = row[col_idx] if col_idx < len(row) else None
            sanitized = sanitize_cell_value(val)
            row_dict[header] = sanitized
            if sanitized is not None and str(sanitized).strip().lower() not in ("null", "none", "", "-"):
                column_values[header].append(sanitized)
        records.append(row_dict)

    column_meta: List[Dict[str, Any]] = []
    candidate_keys: List[str] = []
    total_records_count = len(records)

    for header in headers:
        values = column_values[header]
        inferred_type = detect_data_type(values[:100])
        unique_vals = list(dict.fromkeys([v for v in values if v is not None]))
        cardinality = len(unique_vals)
        non_null_count = len(values)
        null_count = total_records_count - non_null_count

        is_unique = (non_null_count == total_records_count) and non_null_count > 0
        # Generic identifier heuristic (ID, CODE, KEY, NUMBER, SKU, VIN, SL_NO, UID)
        is_candidate_key = is_unique or any(
            k in header.upper()
            for k in ["ID", "CODE", "KEY", "SKU", "VIN", "NUMBER", "NO", "TAG", "SL_NO", "UID"]
        )

        if is_candidate_key and cardinality >= min(total_records_count, 3):
            candidate_keys.append(header)

        column_meta.append({
            "column_name": header,
            "detected_type": inferred_type,
            "total_values": non_null_count,
            "null_count": null_count,
            "unique_values_count": cardinality,
            "is_unique": is_unique,
            "is_candidate_identifier": header in candidate_keys,
            "example_values": [str(v) for v in unique_vals[:4]],
            "sample_distinct": [str(v) for v in unique_vals[:10]],
        })

    return {
        "sheet_name": sheet_name,
        "total_rows": total_records_count,
        "total_columns": len(headers),
        "columns": column_meta,
        "candidate_identifiers": candidate_keys,
        "records": records,
    }


def detect_cross_sheet_relationships(
    sheets_data: Dict[str, Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Identifies semantic relationships and foreign key references across sheets.
    Uses generic value set overlaps and header matches without domain assumptions.
    """
    relationships: List[Dict[str, Any]] = []
    sheet_names = list(sheets_data.keys())

    for i in range(len(sheet_names)):
        for j in range(len(sheet_names)):
            if i == j:
                continue
            src_sheet = sheet_names[i]
            tgt_sheet = sheet_names[j]

            src_cols = {c["column_name"]: c for c in sheets_data[src_sheet]["columns"]}
            tgt_cols = {c["column_name"]: c for c in sheets_data[tgt_sheet]["columns"]}

            for src_name, src_meta in src_cols.items():
                for tgt_name, tgt_meta in tgt_cols.items():
                    # Exact header match or strong key match
                    if src_name == tgt_name and src_meta["detected_type"] == tgt_meta["detected_type"]:
                        if any(k in src_name.upper() for k in ["ID", "CODE", "KEY", "NUMBER", "SKU", "REF"]):
                            # Check sample value overlap
                            src_samples = set(src_meta.get("sample_distinct", []))
                            tgt_samples = set(tgt_meta.get("sample_distinct", []))
                            overlap = len(src_samples.intersection(tgt_samples))
                            if overlap > 0:
                                relationships.append({
                                    "source_sheet": src_sheet,
                                    "source_column": src_name,
                                    "target_sheet": tgt_sheet,
                                    "target_column": tgt_name,
                                    "relationship_type": "MANY_TO_ONE" if not src_meta.get("is_unique") else "ONE_TO_ONE",
                                    "overlap_sample_count": overlap,
                                    "confidence": 0.95 if src_name == tgt_name else 0.80,
                                })
    return relationships


def inspect_dataset_workbook(
    file_bytes: bytes,
    filename: str
) -> Dict[str, Any]:
    """
    Comprehensive, domain-agnostic inspection of an uploaded Excel or CSV dataset:
    - Safely enforces file size limits.
    - Discovers all worksheets, columns, inferred data types, null counts, sample values.
    - Identifies candidate record identifiers.
    - Detects cross-sheet foreign-key relationships.
    - Returns structured metadata registry without writing or activating data.
    """
    if not file_bytes:
        raise ValueError("Uploaded file is empty (0 bytes).")

    if len(file_bytes) > MAX_FILE_SIZE_BYTES:
        raise ValueError(
            f"File size exceeds maximum permitted limit ({MAX_FILE_SIZE_BYTES // (1024*1024)} MB)."
        )

    lower = filename.lower()
    sheets_data: Dict[str, Dict[str, Any]] = {}

    if lower.endswith((".xlsx", ".xls")):
        wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
        for sheet_name in wb.sheetnames:
            sheet = wb[sheet_name]
            rows = list(sheet.iter_rows(values_only=True))
            sheets_data[sheet_name] = inspect_sheet_records(rows, sheet_name)
    else:
        # CSV parsing
        text = file_bytes.decode("utf-8-sig", errors="replace")
        reader = csv.reader(io.StringIO(text))
        rows = [tuple(r) for r in reader if r]
        sheet_name = "Primary_Dataset"
        sheets_data[sheet_name] = inspect_sheet_records(rows, sheet_name)

    if not sheets_data or all(s["total_rows"] == 0 for s in sheets_data.values()):
        raise ValueError(f"No valid data records could be extracted from {filename}.")

    # Cross-sheet relationships
    relationships = detect_cross_sheet_relationships(sheets_data)

    # Pick the sheet with the most rows as primary sheet
    primary_sheet = max(sheets_data.keys(), key=lambda s: sheets_data[s]["total_rows"])
    total_primary_rows = sheets_data[primary_sheet]["total_rows"]

    # Gather candidate identifiers across worksheets
    primary_candidate_keys = sheets_data[primary_sheet]["candidate_identifiers"]

    # Build domain-neutral metadata registry
    metadata_registry = {
        "filename": filename,
        "file_size_bytes": len(file_bytes),
        "inspection_timestamp": datetime.utcnow().isoformat(),
        "primary_sheet": primary_sheet,
        "total_worksheets": len(sheets_data),
        "total_primary_rows": total_primary_rows,
        "candidate_identifiers": primary_candidate_keys,
        "worksheets": {
            s_name: {
                "sheet_name": s_name,
                "total_rows": s_data["total_rows"],
                "total_columns": s_data["total_columns"],
                "columns": s_data["columns"],
                "candidate_identifiers": s_data["candidate_identifiers"],
            }
            for s_name, s_data in sheets_data.items()
        },
        "relationships": relationships,
    }

    return {
        "metadata_registry": metadata_registry,
        "primary_sheet": primary_sheet,
        "total_rows": total_primary_rows,
        "sheets_data": sheets_data,
        "candidate_identifiers": primary_candidate_keys,
    }
