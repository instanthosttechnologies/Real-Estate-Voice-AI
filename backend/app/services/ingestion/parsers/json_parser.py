import json
from typing import Any, Dict, List


def parse_json_bytes(content: bytes) -> List[Dict[str, Any]]:
    """
    Parses JSON and JSONLines datasets. Supports list of dicts, or wrapped objects
    with keys like 'properties', 'units', 'data', or 'listings'.
    """
    text = content.decode("utf-8-sig").strip()
    
    # Try parsing as JSONLines first if multiple newline-separated JSON objects
    if "\n" in text and not text.startswith("["):
        records = []
        for line in text.splitlines():
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        if records:
            return records

    # Parse standard JSON
    parsed = json.loads(text)
    if isinstance(parsed, list):
        return parsed
    elif isinstance(parsed, dict):
        for candidate_key in ["properties", "listings", "units", "data", "records", "items"]:
            if candidate_key in parsed and isinstance(parsed[candidate_key], list):
                return parsed[candidate_key]
        # Single property record wrapped in dictionary
        return [parsed]
    else:
        raise ValueError("Unsupported JSON structure: expected list or records dictionary.")
