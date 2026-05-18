
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from ai_extractor import ai_extract_ip_fields, compose_earnings_description, map_ai_to_calculation_case


def run_medico_legal_actuarial_reasoning(raw_text: str, base_case: Dict[str, Any] | None = None, use_llama: bool = True, llama_model: str = "llama3.1:8b") -> Dict[str, Any]:
    """
    Main intelligence layer. This must run BEFORE Excel calculations.

    IP report text -> AI medico-legal actuarial reasoning -> earnings descriptions -> Summary inputs.
    """
    base_case = base_case or {}
    ai = ai_extract_ip_fields(raw_text, use_llama=use_llama, llama_model=llama_model)
    case = map_ai_to_calculation_case(base_case, ai)
    earnings_description = compose_earnings_description(case)
    case["earnings_description"] = earnings_description
    case["calculation_ready"] = bool(case.get("pre_rows") or case.get("post_rows"))
    case["processing_order"] = [
        "Upload IP Report",
        "Read full IP report",
        "Extract full text",
        "AI Medico-Legal Actuarial reasoning",
        "Generate pre/post earnings descriptions FIRST",
        "Populate Report tab from IP report",
        "Populate Summary tab red fields from earnings descriptions",
        "Run LOE calculation",
        "Download XLSM and actuarial report",
    ]
    return case
