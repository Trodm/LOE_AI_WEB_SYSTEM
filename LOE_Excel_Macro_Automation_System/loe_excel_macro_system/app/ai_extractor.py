
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

# =========================================================
# RAF LOE AI EXTRACTOR
# Priority: PyTorch reasoning first -> Llama/Ollama second -> deterministic fallback
# =========================================================

try:
    import torch  # type: ignore
    TORCH_AVAILABLE = True
except Exception:
    torch = None  # type: ignore
    TORCH_AVAILABLE = False

try:
    from transformers import pipeline  # type: ignore
    TRANSFORMERS_AVAILABLE = True
except Exception:
    pipeline = None  # type: ignore
    TRANSFORMERS_AVAILABLE = False

EXAMPLES_PATH = Path(__file__).resolve().parent / "training_examples" / "loe_ip_mapping_examples.json"

MONEY_PATTERN = re.compile(
    r"(?i)(?:R|ZAR)\s*\d[\d\s,]*(?:\.\d{1,2})?(?:\s*(?:per\s+annum|p\.a\.|pa|per\s+month|per\s+week|per\s+day|per\s+hour|weekly|monthly|annually))?"
)
SCALE_PATTERN = re.compile(
    r"(?i)(lower\s+quartile|median|upper\s+quartile|midpoint\s+between[^.,;\n]{0,160}|between\s+the\s+lower\s+quartile[^.,;\n]{0,160}|between\s+the\s+median[^.,;\n]{0,160}|Paterson\s+[A-E]\s*\d?(?:\s*(?:to|\-|–)\s*[A-E]?\s*\d?)?|National\s+Minimum\s+Wage|prescribed\s+minimum\s+wage|Bargaining\s+Council[^.,;\n]{0,140}|Koch\s*(?:19|20)\d{2}|SalaryExpert[^.,;\n]{0,100}|unskilled\s+worker[^.,;\n]{0,100}|semi[-\s]?skilled\s+worker[^.,;\n]{0,100})"
)

FORBIDDEN_EARNINGS_WORDS = [
    "family", "socio", "medical history", "sustained injuries", "orthopaedic", "neurosurgeon",
    "clinical psychologist", "occupational therapist", "pain", "headache", "scar", "hospital records",
    "current complaints", "father", "mother", "sibling", "household", "water", "electricity",
]

EARNINGS_ALLOWED_WORDS = [
    "earning", "earnings", "salary", "income", "remunerat", "wage", "per month", "per annum",
    "per week", "per day", "employed", "employment", "unemployed", "occupation", "cashier",
    "assistant", "operator", "worker", "technician", "mechanic", "driver", "manager", "clerk",
    "quartile", "median", "paterson", "koch", "minimum wage", "bargaining", "payslip", "affidavit",
    "bank", "retire", "retirement", "inflation", "linear", "linearly", "secured", "returned",
    "resigned", "promoted", "promotion", "nil", "no source of income", "contract", "plateau", "future",
]

SCHEMA = {
    "claimant": {"full_name": None, "id_number": None, "date_of_birth": None, "date_of_accident": None},
    "pre_morbid": {
        "occupation": None,
        "retirement_age": None,
        "actuarial_bullets": [],
        "annual_earnings": [
            {"financial_year": None, "age": None, "salary": None, "salary_today": None, "financial_terms": None, "progression": None, "source_sentence": None}
        ],
    },
    "post_morbid": {
        "occupation": None,
        "retirement_age": None,
        "actuarial_bullets": [],
        "annual_earnings": [
            {"financial_year": None, "age": None, "salary": None, "salary_today": None, "financial_terms": None, "progression": None, "source_sentence": None}
        ],
    },
    "missing_values_to_request": [],
    "confidence": {"overall": None, "notes": []},
}

EARNINGS_DESCRIPTION_PROMPT = """
You are an expert South African RAF medico-legal actuarial Loss of Earnings assistant.

Read the whole Industrial Psychologist report and perform actuarial reasoning. Do NOT merely summarise the report.

Generate the earnings descriptions BEFORE any calculation. The descriptions must reconstruct:
1. earnings at the time of the accident;
2. pre-accident employment progression and earnings;
3. post-accident employment earnings;
4. post-accident employment progression and earnings;
5. retirement ages; and
6. the earnings basis, including payslips, affidavit, bank statements, National Minimum Wage, prescribed minimum wage, Bargaining Council, Koch quartiles, Paterson bands, SalaryExpert or other benchmarks.

STRICT OUTPUT FORMAT:
Pre-accident Income

• At the time of the accident, ...
• ...
• Thereafter, salary inflationary increases until retirement at the age of ... years.

Post-accident Income

• Following the accident, ...
• ...
• Thereafter, salary inflationary increases until retirement at the age of ... years. OR nil/reduced earnings until retirement.

RULES:
- Use short RAF actuarial bullet points only.
- Include employment dates, promotions, resignations, unemployment periods, alternative employment, salaries, annual equivalents, money terms, sources and retirement ages.
- Exclude medical stories, injury details, family background and general expert summaries unless directly explaining no income or time off work.
- Preserve Paterson, Koch, lower quartile, median, upper quartile, unskilled, semi-skilled, National Minimum Wage, prescribed minimum wage, Bargaining Council and payslip references.
- Do not invent figures. If unavailable, state: Not specified in the Industrial Psychologist report.

STRICT CONTINUITY / CHRONOLOGY RULES:
PRE-ACCIDENT:
1. The first bullet MUST state employment/earnings status at the time of the accident.
2. Then write subsequent employment changes in date order.
3. Then write promotions/progression in date/age order.
4. Then write alternative employment or future projected progression.
5. The final bullet MUST be the retirement age / salary inflation statement.

POST-ACCIDENT:
1. The first bullet MUST state the immediate post-accident employment/income impact.
2. Then write recuperation/unemployment or no-income periods.
3. Then write return-to-work or current earnings.
4. Then write reduced/alternative/future progression in date/age order.
5. The final bullet MUST be the retirement age / nil earnings to retirement statement.

The retirement age sentence must never appear in the middle of the description.
"""

# =========================================================
# General helpers
# =========================================================

def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _load_examples() -> str:
    try:
        return json.dumps(json.loads(EXAMPLES_PATH.read_text(encoding="utf-8")), indent=2)
    except Exception:
        return "{}"


def _safe_json(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    cleaned = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.I)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except Exception:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(cleaned[start:end+1])
            except Exception:
                return None
    return None


def split_sentences(text: str) -> List[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+|•", text or "")
    return [_norm(p).strip(" -–\t") for p in parts if len(_norm(p)) > 12]


def _years(text: str) -> List[int]:
    return [int(x) for x in re.findall(r"\b(?:19|20)\d{2}\b", text or "")]


def _money_terms(text: str) -> Optional[str]:
    for pat in [
        r"(?i)((?:19|20)\d{2}\s+money\s+terms)",
        r"(?i)(January\s+(?:19|20)\d{2}\s+money\s+terms)",
        r"(?i)(Koch\s*(?:19|20)\d{2})",
        r"(?i)(as\s+per\s+the\s+year[-\s]?to[-\s]?date[^.,;\n]{0,140})",
        r"(?i)(payslip[^.,;\n]{0,140})",
        r"(?i)(affidavit[^.,;\n]{0,140})",
        r"(?i)(bank\s+statements?[^.,;\n]{0,140})",
        r"(?i)(Bargaining\s+Council[^.,;\n]{0,160})",
        r"(?i)(National\s+Minimum\s+Wage[^.,;\n]{0,120})",
        r"(?i)(SalaryExpert[^.,;\n]{0,120})",
    ]:
        m = re.search(pat, text or "")
        if m:
            return _norm(m.group(1))
    ys = _years(text)
    return str(ys[-1]) if ys else None


def _age(text: str) -> Optional[float]:
    for pat in [
        r"(?i)by\s+(?:approximately\s+)?(?:the\s+)?age\s+(?:of\s+)?(\d{1,2}(?:\.5)?)",
        r"(?i)at\s+(?:approximately\s+)?(?:the\s+)?age\s+(?:of\s+)?(\d{1,2}(?:\.5)?)",
        r"(?i)until\s+retirement\s+at\s+(?:the\s+)?age\s+of\s+(\d{1,2}(?:\.5)?)",
    ]:
        m = re.search(pat, text or "")
        if m:
            try:
                return float(m.group(1))
            except Exception:
                pass
    return None


def _retirement_age(text: str) -> Optional[float]:
    for pat in [
        r"(?i)retirement\s+at\s+the\s+age\s+of\s+(\d{1,2}(?:\.5)?)",
        r"(?i)retirement\s+age\s+(?:of|at)?\s*(\d{1,2}(?:\.5)?)",
        r"(?i)retire(?:ment)?\s+(?:at|by)\s+(?:the\s+age\s+of\s+)?(\d{1,2}(?:\.5)?)",
        r"(?i)age[-\s]?related\s+retirement[^.]{0,100}?(\d{1,2}(?:\.5)?)",
    ]:
        m = re.search(pat, text or "")
        if m:
            try:
                return float(m.group(1))
            except Exception:
                pass
    return None


def _progression(text: Any) -> str:
    t = str(text or "").lower()
    if any(k in t for k in ["linear", "linearly", "straight-line", "straight line", "increased to", "would increase", "promoted", "promotion", "progress", "plateau", "career ceiling", "by age", "by the age", "paterson", "upper quartile", "midpoint"]):
        return "Linear"
    if any(k in t for k in ["flat", "remain", "same", "nil", "unemployed", "no source of income", "salary inflation"]):
        return "Flat"
    return "Flat"


def _salary_or_scale(text: str) -> Optional[Any]:
    t = text or ""
    if re.search(r"(?i)nil|no source of income|unemployed|no income|not generate any income", t):
        return 0
    m = MONEY_PATTERN.search(t)
    if m:
        raw = _norm(m.group(0))
        num = re.sub(r"[^0-9.]", "", raw)
        try:
            return float(num)
        except Exception:
            return raw
    m = SCALE_PATTERN.search(t)
    if m:
        return _norm(m.group(0))
    return None


def _annualise_salary(value: Any, source_sentence: str = "") -> Any:
    """Annualise obvious weekly/monthly/daily amounts; keep scales as text."""
    if value in (None, ""):
        return value
    if isinstance(value, (int, float)):
        amount = float(value)
    else:
        s = str(value)
        n = re.search(r"(\d[\d\s,]*(?:\.\d{1,2})?)", s)
        if not n:
            return value
        try:
            amount = float(n.group(1).replace(" ", "").replace(",", ""))
        except Exception:
            return value
    text = f"{value} {source_sentence}".lower()
    if "per annum" in text or "p.a" in text:
        return round(amount, 2)
    if "per month" in text or "monthly" in text:
        return round(amount * 12, 2)
    if "per week" in text or "weekly" in text:
        return round(amount * 52, 2)
    if "per day" in text or "daily" in text:
        days = 260
        m = re.search(r"(\d(?:\.\d+)?)\s+days?\s+per\s+week", text)
        if m:
            days = float(m.group(1)) * 52
        return round(amount * days, 2)
    return round(amount, 2)

# =========================================================
# Section extraction
# =========================================================

def _extract_section(text: str, start_patterns: List[str], end_patterns: List[str], max_chars: int = 20000) -> str:
    t = text or ""
    candidates: List[Tuple[int, int, str]] = []
    for p in start_patterns:
        for m in re.finditer(p, t, flags=re.I | re.S):
            start = m.start()
            after = t[start + len(m.group(0)):]
            rel_end = len(after)
            for ep in end_patterns:
                em = re.search(ep, after, flags=re.I | re.S)
                if em:
                    rel_end = min(rel_end, em.start())
            sec = t[start:start + len(m.group(0)) + rel_end]
            sec = sec[:max_chars]
            # Penalise contents page snippets
            score = len(sec) - (5000 if "contents" in sec[:500].lower() or "....." in sec[:500] else 0)
            candidates.append((score, start, sec))
    if not candidates:
        return ""
    return max(candidates, key=lambda x: x[0])[2]


def split_pre_post_sections(text: str) -> Dict[str, str]:
    pre = _extract_section(
        text,
        [
            r"PRE[-\s]?ACCIDENT\s+EMPLOYMENT\s*&\s*EARNINGS\s+SCENARIO",
            r"PRE[-\s]?ACCIDENT\s+EMPLOYMENT\s+SCENARIO",
            r"PRE[-\s]?MORBID\s+EARNINGS",
            r"PRE[-\s]?MORBID\s+POTENTIAL\s+FUNCTIONING",
            r"PRE[-\s]?ACCIDENT\s+SCENARIO\s+LOSS\s+OF\s+EMPLOYMENT",
            r"PRE[-\s]?ACCIDENT\s+INCOME",
        ],
        [r"POST[-\s]?ACCIDENT", r"POST[-\s]?MORBID", r"LOSS\s+OF\s+EARNINGS", r"RECOMMENDATIONS"],
    )
    post = _extract_section(
        text,
        [
            r"POST[-\s]?ACCIDENT\s+LOSS\s+OF\s+EMPLOYMENT\s+AND\s+EARNINGS\s+SCENARIO",
            r"POST[-\s]?ACCIDENT\s+EMPLOYMENT\s+SCENARIO",
            r"POST[-\s]?MORBID\s+PROBABLE\s+EARNING\s+PROJECTIONS",
            r"POST[-\s]?MORBID\s+POTENTIAL\s+FUNCTIONING",
            r"POST[-\s]?ACCIDENT\s+INCOME",
        ],
        [r"LOSS\s+OF\s+EARNINGS", r"RECOMMENDATIONS", r"CONCLUSION", r"RIGHT\s+TO\s+AMEND", r"DISCLAIMER", r"BIBLIOGRAPHY", r"APPENDIX", r"ANNEXURE"],
    )
    if not pre:
        pre = text[:12000]
    if not post:
        post = text[-12000:]
    return {"pre": pre, "post": post}

# =========================================================
# PyTorch first: semantic sentence ranking and optional generation
# =========================================================

_transformer_generator = None


def _rank_with_pytorch(sentences: List[str], limit: int = 120) -> List[str]:
    if not sentences:
        return []
    keywords = EARNINGS_ALLOWED_WORDS + ["career", "plateau", "continued", "ceased", "alternative", "market", "future"]
    if TORCH_AVAILABLE:
        scores = []
        for s in sentences:
            vals = [1.0 if k.lower() in s.lower() else 0.0 for k in keywords]
            penalty = sum(1 for k in FORBIDDEN_EARNINGS_WORDS if k in s.lower()) * 0.6
            try:
                score = float(torch.tensor(vals).sum().item()) - penalty  # type: ignore
            except Exception:
                score = sum(vals) - penalty
            scores.append(score)
        ranked = [s for score, s in sorted(zip(scores, sentences), key=lambda x: x[0], reverse=True) if score > 0]
        return ranked[:limit] or sentences[:limit]
    return sorted(sentences, key=lambda s: sum(k.lower() in s.lower() for k in keywords), reverse=True)[:limit]


def rank_sentences(text: str, limit: int = 120) -> List[str]:
    return _rank_with_pytorch(split_sentences(text), limit=limit)


def _call_pytorch_generator(prompt: str) -> Optional[str]:
    """Optional local transformer generation. Disabled by default to avoid Render memory crashes."""
    if os.getenv("ENABLE_PYTORCH_GENERATION", "false").lower() not in {"1", "true", "yes"}:
        return None
    if not (TORCH_AVAILABLE and TRANSFORMERS_AVAILABLE):
        return None
    global _transformer_generator
    try:
        if _transformer_generator is None:
            model_name = os.getenv("PYTORCH_TEXT_MODEL", "google/flan-t5-base")
            _transformer_generator = pipeline("text2text-generation", model=model_name, device=-1)  # type: ignore
        result = _transformer_generator(prompt[:12000], max_new_tokens=900, do_sample=False)
        if result:
            return result[0].get("generated_text", "").strip()
    except Exception:
        return None
    return None

# =========================================================
# Llama/Ollama second
# =========================================================

def call_llama(prompt: str, llama_model: str = "llama3.1:8b", timeout: int = 240, json_format: bool = False) -> Optional[str]:
    urls = []
    env_url = (os.getenv("LLAMA_API_URL") or os.getenv("OLLAMA_BASE_URL") or "").strip().rstrip("/")
    if env_url:
        urls.append(env_url + ("/api/generate" if not env_url.endswith("/api/generate") else ""))
    urls.append("http://127.0.0.1:11434/api/generate")
    payload = {"model": os.getenv("OLLAMA_MODEL", llama_model), "prompt": prompt, "stream": False}
    if json_format:
        payload["format"] = "json"
    for url in urls:
        try:
            r = requests.post(url, json=payload, timeout=timeout)
            r.raise_for_status()
            data = r.json()
            return (data.get("response") or data.get("text") or data.get("content") or "").strip()
        except Exception:
            continue
    return None


def _extract_with_llama_json(text: str, model: str) -> Optional[Dict[str, Any]]:
    parts = split_pre_post_sections(text)
    prompt = f"""
You are a South African RAF Loss of Earnings actuarial extraction model.

Return strict JSON only. Extract calculation-ready earnings assumptions from the Industrial Psychologist report.
Use no defaults. If missing, return null and add the missing item to missing_values_to_request.

Schema:
{json.dumps(SCHEMA, indent=2)}

Rules:
- Pre-accident values come from pre-accident employment/earnings scenario or equivalent.
- Post-accident values come from post-accident loss of employment/earnings scenario or equivalent.
- Extract employment chronology, earnings at accident, future progression, post-accident earnings, future post progression, retirement ages, Paterson/Koch/quartile/NMW/Bargaining Council references.
- annual_earnings rows must contain financial_year, age, salary, salary_today, financial_terms, progression, source_sentence.
- progression must be Flat or Linear only.

Examples/rules from prior cases:
{_load_examples()[:12000]}

PRE SECTION:
{parts['pre'][:22000]}

POST SECTION:
{parts['post'][:22000]}

FULL REPORT CONTEXT:
{text[:30000]}
""".strip()
    raw = call_llama(prompt, model, json_format=True)
    return _safe_json(raw or "")

# =========================================================
# Deterministic extraction and row mapping
# =========================================================

def _is_actuarial_sentence(s: str) -> bool:
    sl = s.lower()
    if not any(k in sl for k in EARNINGS_ALLOWED_WORDS):
        return False
    if any(k in sl for k in FORBIDDEN_EARNINGS_WORDS) and not any(k in sl for k in ["unemployed", "not remunerated", "returned to work", "salary", "earning", "income", "hospitalised", "recuperated"]):
        return False
    return True


def rows_from_section(section: str, max_rows: int = 30) -> List[Dict[str, Any]]:
    rows = []
    for s in rank_sentences(section, limit=200):
        if not _is_actuarial_sentence(s):
            continue
        sal = _salary_or_scale(s)
        # keep retirement/inflation sentence but not as salary row unless actual salary/scale exists
        if sal is None:
            continue
        yrs = _years(s)
        row = {
            "fin_year": yrs[0] if yrs else _money_terms(s),
            "financial_year": yrs[0] if yrs else _money_terms(s),
            "age": _age(s),
            "salary": _annualise_salary(sal, s),
            "salary_today": None,
            "financial_terms": _money_terms(s),
            "progression": _progression(s),
            "source_sentence": s,
        }
        rows.append(row)
        if len(rows) >= max_rows:
            break
    return rows


def _norm_row(item: Dict[str, Any], source_text: str = "") -> Optional[Dict[str, Any]]:
    if not isinstance(item, dict):
        return None
    joined = " ".join(str(v) for v in item.values() if v not in (None, "")) + " " + source_text[:500]
    sal = item.get("salary") or item.get("earnings") or item.get("annual_salary") or item.get("amount") or _salary_or_scale(joined)
    if sal in (None, ""):
        return None
    source_sentence = item.get("source_sentence") or joined[:400]
    return {
        "fin_year": item.get("financial_year") or item.get("fin_year") or item.get("year") or _money_terms(joined),
        "financial_year": item.get("financial_year") or item.get("fin_year") or item.get("year") or _money_terms(joined),
        "age": item.get("age") or _age(joined),
        "salary": _annualise_salary(sal, source_sentence),
        "salary_today": item.get("salary_today") or item.get("present_value"),
        "financial_terms": item.get("financial_terms") or item.get("terms") or _money_terms(joined),
        "progression": _progression(item.get("progression") or joined),
        "source_sentence": source_sentence,
    }


def _first_number(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    m = re.search(r"(\d{1,3}(?:[ ,]\d{3})*|\d+)(?:\.\d+)?", str(value))
    if not m:
        return None
    try:
        return float(m.group(0).replace(" ", "").replace(",", ""))
    except Exception:
        return None


def _extract_field(text: str, patterns: List[str]) -> Optional[str]:
    for p in patterns:
        m = re.search(p, text or "", flags=re.I)
        if m:
            return _norm(m.group(1))
    return None



def _bullet_text(value: str) -> str:
    return str(value or "").strip().lstrip("•").strip(" -–\t")


def _sentence_year_or_age(text: str) -> float:
    """Sort key for chronological earnings bullets."""
    t = text or ""
    # At accident / following accident should start first.
    if re.search(r"(?i)at\s+the\s+time\s+of\s+the\s+accident|at\s+accident|date\s+of\s+accident", t):
        return 0
    if re.search(r"(?i)following\s+the\s+accident|after\s+the\s+accident|hospitali[sz]ed|recuperated", t):
        return 0
    # Specific years before ages.
    years = _years(t)
    if years:
        return float(min(years))
    age = _age(t)
    if age is not None:
        return 3000 + float(age)
    # Keep generic progression before retirement but after dateable rows.
    if re.search(r"(?i)promoted|progress|increase|secured|alternative|would\s+have|would\s+be", t):
        return 4000
    return 5000


def _is_retirement_bullet(text: str) -> bool:
    return bool(re.search(r"(?i)retirement|retire|salary\s+inflation", text or ""))


def _continuity_score(text: str, is_post: bool) -> int:
    """Prioritise the natural actuarial order within dated ties."""
    t = (text or "").lower()
    if _is_retirement_bullet(t):
        return 99
    if not is_post:
        if "at the time of the accident" in t or "date of accident" in t:
            return 0
        if any(k in t for k in ["unemployed", "employed as", "earning", "earned"]):
            return 1
        if any(k in t for k in ["secured", "alternative employment", "returned"]):
            return 2
        if any(k in t for k in ["promoted", "promotion", "progress", "linearly", "paterson", "quartile", "median"]):
            return 3
        return 5
    else:
        if any(k in t for k in ["following the accident", "hospital", "recuperat", "away from work"]):
            return 0
        if any(k in t for k in ["unemployed", "no source of income", "nil"]):
            return 1
        if any(k in t for k in ["returned", "remains employed", "secured employment", "current"]):
            return 2
        if any(k in t for k in ["part-time", "future", "reduced", "progress", "quartile", "median", "paterson"]):
            return 3
        return 5


def _normalise_retirement_sentence(sentence: str, is_post: bool, default_age: Any = None) -> str:
    txt = _bullet_text(sentence)
    age = _retirement_age(txt) or _first_number(default_age)
    if age is not None:
        if is_post and re.search(r"(?i)nil|unemployed|no source of income|reduced", txt):
            return f"• Thereafter, nil or reduced earnings are applied until retirement at the age of {age:g} years."
        return f"• Thereafter, salary inflationary increases until retirement at the age of {age:g} years."
    if _is_retirement_bullet(txt):
        return "• " + txt.rstrip(".") + "."
    return ""


def order_earnings_bullets(bullets: List[str], is_post: bool, retirement_age: Any = None) -> List[str]:
    """
    Enforces continuity:
    - start with accident/initial earnings impact;
    - then dated employment/progression bullets;
    - retirement/inflation sentence is always last.
    """
    seen = set()
    cleaned: List[str] = []
    retirement_items: List[str] = []
    for b in bullets or []:
        txt = _bullet_text(b)
        if not txt:
            continue
        key = re.sub(r"\s+", " ", txt.lower()).strip(".")
        if key in seen:
            continue
        seen.add(key)
        if _is_retirement_bullet(txt):
            retirement_items.append(txt)
        else:
            cleaned.append(txt.rstrip("."))

    cleaned.sort(key=lambda x: (_sentence_year_or_age(x), _continuity_score(x, is_post), len(x)))

    final = ["• " + x.rstrip(".") + "." for x in cleaned]

    retirement_sentence = ""
    if retirement_items:
        # Prefer a sentence that contains an explicit retirement age.
        retirement_items.sort(key=lambda x: 0 if _retirement_age(x) is not None else 1)
        retirement_sentence = _normalise_retirement_sentence(retirement_items[0], is_post, retirement_age)
    elif retirement_age not in (None, "", []):
        try:
            age = float(retirement_age)
            retirement_sentence = f"• Thereafter, salary inflationary increases until retirement at the age of {age:g} years."
        except Exception:
            retirement_sentence = f"• Thereafter, salary inflationary increases until retirement at the age of {retirement_age} years."

    if retirement_sentence:
        final.append(retirement_sentence)

    return final

def _clean_bullets(values: Any, section_text: str, is_post: bool) -> List[str]:
    if isinstance(values, list):
        candidates = [str(x).strip() for x in values if str(x).strip()]
    elif isinstance(values, str):
        candidates = split_sentences(values)
    else:
        candidates = []
    out = []
    for s in candidates:
        s = s.strip("• -–\t")
        if _is_actuarial_sentence(s) or any(k in s.lower() for k in ["retirement", "salary inflation", "nil earnings", "no source of income"]):
            out.append("• " + s.rstrip("." ) + ".")
    if out:
        return order_earnings_bullets(out[:18], is_post)
    # fallback from ranked section sentences
    fallback = []
    for s in rank_sentences(section_text, limit=80):
        if _is_actuarial_sentence(s) or any(k in s.lower() for k in ["retirement", "salary inflation"]):
            fallback.append("• " + s.rstrip(".") + ".")
        if len(fallback) >= 12:
            break
    if not fallback:
        msg = "Post-accident earnings were not specified in the Industrial Psychologist report." if is_post else "Pre-accident earnings were not specified in the Industrial Psychologist report."
        fallback = ["• " + msg]
    return order_earnings_bullets(fallback, is_post)


def _build_case_from_payload(text: str, payload: Optional[Dict[str, Any]], sections: Dict[str, str], torch_sentences: List[str]) -> Dict[str, Any]:
    payload = payload or {}
    claimant = payload.get("claimant", {}) if isinstance(payload, dict) else {}
    pre = payload.get("pre_morbid", {}) if isinstance(payload, dict) else {}
    post = payload.get("post_morbid", {}) if isinstance(payload, dict) else {}
    pre_text, post_text = sections.get("pre", ""), sections.get("post", "")
    full_name = claimant.get("full_name") or _extract_field(text, [r"Full Name\s+([^\n]+)", r"CLAIMANT NAME\s+([^\n]+)", r"Name and Surname\s+([^\n]+)", r"For\s+([A-Z][A-Za-z\s.\-]+)"])

    def rows(payload_section: Dict[str, Any], section_text: str) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        earnings = payload_section.get("annual_earnings") if isinstance(payload_section, dict) else None
        if isinstance(earnings, list):
            for item in earnings:
                r = _norm_row(item, section_text)
                if r:
                    out.append(r)
        return out or rows_from_section(section_text)

    case: Dict[str, Any] = {
        "full_name": full_name,
        "claimant_name": full_name,
        "surname": (str(full_name).split()[-1] if full_name else None),
        "first_names": (" ".join(str(full_name).split()[:-1]) if full_name and len(str(full_name).split()) > 1 else full_name),
        "id_number": claimant.get("id_number") or _extract_field(text, [r"Identity Number\s+([^\n]+)", r"IDENTITY NUMBER\s+([^\n]+)"]),
        "dob_text": claimant.get("date_of_birth") or _extract_field(text, [r"Date of Birth\s+([^\n]+)", r"DATE OF BIRTH\s+([^\n]+)"]),
        "doa_text": claimant.get("date_of_accident") or _extract_field(text, [r"Date of Accident\s+([^\n]+)", r"ACCIDENT DATE\s+([^\n]+)"]),
        "ip_report_date_text": _extract_field(text, [r"Date of Report\s+([^\n]+)", r"REPORT RELEASE DATE\s+([^\n]+)", r"Report Date\s+([^\n]+)"]),
        "pre_occupation": pre.get("occupation"),
        "post_occupation": post.get("occupation"),
        "pre_rows": rows(pre, pre_text),
        "post_rows": rows(post, post_text),
        "pre_ret_age": _first_number(pre.get("retirement_age")) or _retirement_age(pre_text),
        "post_ret_age": _first_number(post.get("retirement_age")) or _retirement_age(post_text),
        "pre_peak_age": _age(pre_text),
        "post_peak_age": _age(post_text),
        "missing_values_to_request": payload.get("missing_values_to_request", []) if isinstance(payload, dict) else [],
        "ai_review_notes": torch_sentences[:15],
        "ai_llama_used": bool(payload),
    }
    case["earnings_description_pre"] = _clean_bullets(pre.get("actuarial_bullets") if isinstance(pre, dict) else [], pre_text, False)
    case["earnings_description_post"] = _clean_bullets(post.get("actuarial_bullets") if isinstance(post, dict) else [], post_text, True)
    # Direct convenience keys for old code
    if case["pre_rows"]:
        case["pre_accident_income"] = case["pre_rows"][0].get("salary")
        case["earnings_at_accident"] = case["pre_rows"][0].get("salary")
    if case["post_rows"]:
        case["post_accident_income"] = case["post_rows"][0].get("salary")
        case["earnings_after_accident"] = case["post_rows"][0].get("salary")
    return case

# =========================================================
# Public API expected by ip_parser.py and web_app.py
# =========================================================

def ai_extract_ip_fields(text: str, use_llama: bool = True, llama_model: str = "llama3.1:8b") -> Dict[str, Any]:
    sections = split_pre_post_sections(text)
    # PyTorch first: extract/rank earnings-relevant sentences from the whole IP report and the two sections.
    torch_sentences = rank_sentences("\n".join([sections.get("pre", ""), sections.get("post", ""), text]), limit=140)
    # Optional PyTorch generator first. Only enabled if ENABLE_PYTORCH_GENERATION=true.
    transformer_payload = None
    if os.getenv("ENABLE_PYTORCH_GENERATION", "false").lower() in {"1", "true", "yes"}:
        prompt = f"""{EARNINGS_DESCRIPTION_PROMPT}\n\nReturn JSON using this schema:\n{json.dumps(SCHEMA)}\n\nREPORT:\n{text[:18000]}"""
        gen = _call_pytorch_generator(prompt)
        transformer_payload = _safe_json(gen or "")
    # Llama second.
    llama_payload = None
    if use_llama and transformer_payload is None:
        llama_payload = _extract_with_llama_json(text, llama_model)
    payload = transformer_payload or llama_payload
    return {
        "pytorch_available": TORCH_AVAILABLE,
        "pytorch_generation_used": transformer_payload is not None,
        "llama_available": llama_payload is not None,
        "llama_payload": payload or {},
        "torch_key_sentences": torch_sentences,
        "sections": sections,
    }


def map_ai_to_calculation_case(case_data: dict, ai_data: dict = None) -> dict:
    if case_data is None:
        case_data = {}
    ai_data = ai_data or {}
    source_text = "\n".join([case_data.get("pre_accident_section_text", ""), case_data.get("post_accident_section_text", "")])
    if not source_text.strip():
        source_text = "\n".join(ai_data.get("sections", {}).values())
    built = _build_case_from_payload(source_text, ai_data.get("llama_payload") or {}, ai_data.get("sections") or {}, ai_data.get("torch_key_sentences") or [])
    merged = dict(case_data)
    merged.update({k: v for k, v in built.items() if v not in (None, "", [], {})})
    # Ensure rows exist even if Llama produced nothing
    if not merged.get("pre_rows"):
        merged["pre_rows"] = rows_from_section(ai_data.get("sections", {}).get("pre", case_data.get("pre_accident_section_text", "")))
    if not merged.get("post_rows"):
        merged["post_rows"] = rows_from_section(ai_data.get("sections", {}).get("post", case_data.get("post_accident_section_text", "")))
    if not merged.get("earnings_description_pre"):
        merged["earnings_description_pre"] = _clean_bullets([], ai_data.get("sections", {}).get("pre", ""), False)
    if not merged.get("earnings_description_post"):
        merged["earnings_description_post"] = _clean_bullets([], ai_data.get("sections", {}).get("post", ""), True)
    return merged


def compose_earnings_description(case: Dict[str, Any]) -> str:
    pre = case.get("earnings_description_pre") or []
    post = case.get("earnings_description_post") or []
    if isinstance(pre, str):
        pre = split_sentences(pre)
    if isinstance(post, str):
        post = split_sentences(post)
    pre = order_earnings_bullets(pre, is_post=False, retirement_age=case.get("pre_ret_age") or case.get("pre_accident_retirement_age"))
    post = order_earnings_bullets(post, is_post=True, retirement_age=case.get("post_ret_age") or case.get("post_accident_retirement_age"))

    if not pre:
        pre = ["• Pre-accident earnings were not specified in the Industrial Psychologist report."]
    if not post:
        post = ["• Post-accident earnings were not specified in the Industrial Psychologist report."]

    lines = ["Pre-accident Income", ""]
    lines.extend(pre)
    lines.extend(["", "Post-accident Income", ""])
    lines.extend(post)
    return "\n".join(lines).strip()


def generate_earnings_description_llama(raw_text: str = "", case: Optional[dict] = None, llama_model: str = "llama3.1:8b", **kwargs) -> str:
    case = case or kwargs.get("case_data") or {}
    raw_text = raw_text or kwargs.get("text", "") or ""
    # If case already contains AI-built bullets, use them first. This guarantees descriptions before calculations.
    if case.get("earnings_description_pre") or case.get("earnings_description_post"):
        return compose_earnings_description(case)
    # Otherwise run full extraction and compose.
    ai = ai_extract_ip_fields(raw_text, use_llama=True, llama_model=llama_model)
    built = map_ai_to_calculation_case(case, ai)
    return compose_earnings_description(built)
