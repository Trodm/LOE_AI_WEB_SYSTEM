
from __future__ import annotations
from typing import Any, Dict, List


def summary_rows_from_earnings_descriptions(case: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    """Returns the rows that must drive Summary tab red fields."""
    return {
        "pre_rows": case.get("pre_rows") or [],
        "post_rows": case.get("post_rows") or [],
    }


def missing_inputs(case: Dict[str, Any]) -> list[str]:
    missing = list(case.get("missing_values_to_request") or [])
    if not case.get("pre_rows"):
        missing.append("Pre-accident earnings at the time of accident or future progression values")
    if not case.get("post_rows"):
        missing.append("Post-accident earnings/current earnings or future progression values")
    return list(dict.fromkeys(missing))
