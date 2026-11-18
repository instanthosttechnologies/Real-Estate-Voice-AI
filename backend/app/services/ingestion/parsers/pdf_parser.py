import io
import re
from typing import Any, Dict, List
import pymupdf as fitz


def parse_pdf_bytes(content: bytes) -> List[Dict[str, Any]]:
    """
    Parses PDF documents by extracting tabular records or structured property cards.
    Uses PyMuPDF (fitz) table detection with structured key-value fallback.
    """
    doc = fitz.open(stream=content, filetype="pdf")
    extracted_records: List[Dict[str, Any]] = []

    # 1. Attempt Tabular Extraction
    for page in doc:
        tabs = page.find_tables()
        if tabs.tables:
            for tab in tabs:
                data = tab.extract()
                if data and len(data) >= 2:
                    raw_headers = [str(c).strip() if c else f"col_{i}" for i, c in enumerate(data[0])]
                    for row in data[1:]:
                        if not row or all(not cell for cell in row):
                            continue
                        row_dict = {}
                        for i, h in enumerate(raw_headers):
                            val = row[i].strip() if i < len(row) and row[i] else None
                            row_dict[h] = val
                        if len(row_dict) >= 3:
                            extracted_records.append(row_dict)

    if extracted_records:
        return extracted_records

    # 2. Fallback: Parse structured key-value property blocks
    full_text = ""
    for page in doc:
        full_text += page.get_text() + "\n---PAGE---\n"

    sections = re.split(r"\n\s*\n|---PAGE---|Property\s*#?\d+:", full_text)
    for section in sections:
        lines = [line.strip() for line in section.splitlines() if line.strip()]
        if not lines:
            continue
        record: Dict[str, Any] = {}
        for line in lines:
            if ":" in line:
                k, v = line.split(":", 1)
                record[k.strip()] = v.strip()
        if len(record) >= 3:
            extracted_records.append(record)

    return extracted_records
