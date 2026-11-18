import csv
import io
from typing import Any, Dict, List
import openpyxl


def sanitize_cell_value(val: Any) -> Any:
    """
    Prevents CSV/Excel formula injection by stripping leading executable prefixes (=, +, -, @).
    """
    if isinstance(val, str):
        val = val.strip()
        if val.startswith(("=", "+", "-", "@")):
            val = val.lstrip("=+-@")
        return val
    return val


def parse_csv_bytes(content: bytes) -> List[Dict[str, Any]]:
    """
    Parses CSV content using Python's built-in csv module with delimiter sniffing
    and formula injection sanitization.
    """
    text = content.decode("utf-8-sig", errors="replace")
    stream = io.StringIO(text)
    
    # Delimiter sniffing
    sample = text[:4096]
    delimiter = ","
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t;|")
        delimiter = dialect.delimiter
    except Exception:
        delimiter = ","

    stream.seek(0)
    reader = csv.reader(stream, delimiter=delimiter)
    headers = None
    records: List[Dict[str, Any]] = []

    for row in reader:
        if not row:
            continue
        if headers is None:
            headers = [str(col).strip() for col in row]
            continue
        
        # Build row dict
        row_dict = {}
        for idx, header in enumerate(headers):
            val = row[idx].strip() if idx < len(row) else None
            # Treat empty strings as None
            if val == "":
                val = None
            row_dict[header] = sanitize_cell_value(val)
        records.append(row_dict)

    return records


def parse_excel_bytes(content: bytes) -> List[Dict[str, Any]]:
    """
    Parses Excel (.xlsx, .xls) content directly via openpyxl.
    """
    stream = io.BytesIO(content)
    wb = openpyxl.load_workbook(stream, data_only=True)
    sheet = wb.active

    records: List[Dict[str, Any]] = []
    headers: List[str] = []

    for row_idx, row in enumerate(sheet.iter_rows(values_only=True)):
        if not row or all(v is None for v in row):
            continue
        if not headers:
            headers = [str(c).strip() if c is not None else f"col_{i}" for i, c in enumerate(row)]
            continue

        row_dict = {}
        for i, header in enumerate(headers):
            val = row[i] if i < len(row) else None
            row_dict[header] = sanitize_cell_value(val)
        records.append(row_dict)

    return records
