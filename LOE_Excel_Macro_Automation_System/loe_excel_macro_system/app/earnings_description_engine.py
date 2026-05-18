
from __future__ import annotations
from typing import Dict, Any
from ai_extractor import compose_earnings_description


def generate_downloadable_earnings_description(case: Dict[str, Any]) -> str:
    return compose_earnings_description(case)
