
from __future__ import annotations
from typing import Dict, Any


def report_tab_fields_from_ip(case: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "surname": case.get("surname"),
        "first_names": case.get("first_names"),
        "id_number": case.get("id_number"),
        "date_of_birth": case.get("dob_text"),
        "date_of_accident": case.get("doa_text"),
        "attorney_name": case.get("attorney_name"),
        "attorney_reference": case.get("attorney_reference"),
        "ip_name": case.get("ip_name") or "Industrial Psychologist",
        "ip_report_date": case.get("ip_report_date_text"),
    }
