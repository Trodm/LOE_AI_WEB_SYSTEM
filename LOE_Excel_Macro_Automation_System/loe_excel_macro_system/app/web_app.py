
from __future__ import annotations

import os
import shutil
import traceback
import uuid
import warnings
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from actuarial_reasoning_engine import run_medico_legal_actuarial_reasoning
from excel_macro_engine import export_latest_docm_to_pdf, populate_template_openpyxl, run_excel_macro
from ip_parser import SUPPORTED_REPORT_EXTENSIONS, extract_ip_report_text, parse_base_case
from report_generator import generate_actuarial_report_docx, try_convert_docx_to_pdf
from summary_mapper import missing_inputs

warnings.filterwarnings("ignore", message="Unknown extension is not supported and will be removed")

APP_DIR = Path(__file__).resolve().parent
BASE_DIR = APP_DIR.parent
UPLOAD_DIR = BASE_DIR / "uploads"
RUNS_DIR = BASE_DIR / "runs"
STATIC_DIR = APP_DIR / "static"
TEMPLATE_DIR = APP_DIR / "templates"
TRAINING_DIR = RUNS_DIR / "training"
TEMPLATE_XLSM = BASE_DIR / "templates" / "LOE Izibalo Template (DataMark Analytics).xlsm"
TEMPLATE_DOCM = BASE_DIR / "templates" / "LOE Izibalo Template (DataMark Analytics).docm"
for folder in [UPLOAD_DIR, RUNS_DIR, STATIC_DIR, TEMPLATE_DIR, TRAINING_DIR]:
    folder.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="RAF LOE AI Medico-Legal Actuarial Web Platform", version="5.0")
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))


def _allowed(filename: str) -> bool:
    return Path(filename or "").suffix.lower() in SUPPORTED_REPORT_EXTENSIONS


def _save_upload(upload: UploadFile, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("wb") as f:
        shutil.copyfileobj(upload.file, f)


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(request, "index.html", {"request": request, "supported": ", ".join(sorted(SUPPORTED_REPORT_EXTENSIONS))})


@app.post("/process-ip", response_class=HTMLResponse)
async def process_ip(
    request: Request,
    file: UploadFile = File(...),
    use_llama: Optional[str] = Form(default="yes"),
    llama_model: str = Form(default="llama3.1:8b"),
    past_pre: float = Form(default=0.05),
    past_post: float = Form(default=0.05),
    future_pre: float = Form(default=0.15),
    future_post: float = Form(default=0.25),
):
    job_id = datetime.now().strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:8]
    job_dir = RUNS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    try:
        if not _allowed(file.filename or ""):
            raise ValueError("Unsupported file type. Upload PDF, scanned PDF, Word DOCX/DOC, or image files.")

        # 1. Upload and read IP report
        upload_path = UPLOAD_DIR / f"{job_id}_{Path(file.filename or 'ip_report').name}"
        _save_upload(file, upload_path)

        # 2. Extract full report text
        extracted = extract_ip_report_text(upload_path)
        raw_text = extracted.get("clean") or extracted.get("text") or ""
        base_case = parse_base_case(raw_text)
        base_case["extraction_method"] = extracted.get("method")
        base_case["source_characters"] = extracted.get("characters")

        # 3. AI medico-legal actuarial reasoning and earnings descriptions FIRST
        case = run_medico_legal_actuarial_reasoning(
            raw_text=raw_text,
            base_case=base_case,
            use_llama=(use_llama == "yes"),
            llama_model=llama_model.strip() or "llama3.1:8b",
        )
        earnings_description = case.get("earnings_description") or ""

        # 4. Downloadable earnings descriptions
        earnings_file = job_dir / "Earnings_Description.txt"
        earnings_file.write_text(earnings_description, encoding="utf-8")

        # 5. Generate actuarial report from IP + earnings descriptions
        actuarial_docx = job_dir / "Actuarial_Report.docx"
        generate_actuarial_report_docx(case, earnings_description, actuarial_docx)
        actuarial_pdf = try_convert_docx_to_pdf(actuarial_docx)

        # 6. Populate Report tab and Summary tab from AI-generated earnings descriptions
        out_xlsm = job_dir / TEMPLATE_XLSM.name
        populate_template_openpyxl(
            TEMPLATE_XLSM,
            out_xlsm,
            case,
            {"past_pre": past_pre, "past_post": past_post, "future_pre": future_pre, "future_post": future_post},
            earnings_description=earnings_description,
        )

        # 7. Optional Windows macro calculation/PDF
        doc_error = None
        macro_pdf = None
        if os.name == "nt":
            try:
                run_excel_macro(out_xlsm, TEMPLATE_DOCM.parent, job_dir)
                macro_pdf = export_latest_docm_to_pdf(job_dir)
            except Exception as exc:
                doc_error = str(exc)
        else:
            doc_error = "Render/Linux cannot run Microsoft Excel/Word macros. The populated XLSM, earnings write-up and DOCX report were generated. Run the XLSM macro on Windows Office for full macro-driven Word/PDF automation."

        files = [
            {"label": "Populated Excel calculation model", "path": out_xlsm.name, "url": f"/download/{job_id}/{out_xlsm.name}"},
            {"label": "AI-generated earnings description write-up", "path": earnings_file.name, "url": f"/download/{job_id}/{earnings_file.name}"},
            {"label": "Generated actuarial Word report", "path": actuarial_docx.name, "url": f"/download/{job_id}/{actuarial_docx.name}"},
        ]
        if actuarial_pdf:
            files.append({"label": "Generated actuarial PDF report", "path": actuarial_pdf.name, "url": f"/download/{job_id}/{actuarial_pdf.name}"})
        if macro_pdf:
            files.append({"label": "Generated macro PDF report", "path": macro_pdf.name, "url": f"/download/{job_id}/{macro_pdf.name}"})

        return templates.TemplateResponse(
            request,
            "result.html",
            {
                "request": request,
                "job_id": job_id,
                "case": case,
                "files": files,
                "doc_error": doc_error,
                "success": True,
                "earnings_description": earnings_description,
                "missing_inputs": missing_inputs(case),
                "supported": ", ".join(sorted(SUPPORTED_REPORT_EXTENSIONS)),
            },
        )
    except Exception as exc:
        return templates.TemplateResponse(
            request,
            "result.html",
            {
                "request": request,
                "job_id": job_id,
                "success": False,
                "error": str(exc),
                "traceback": traceback.format_exc(),
                "supported": ", ".join(sorted(SUPPORTED_REPORT_EXTENSIONS)),
            },
            status_code=500,
        )


@app.post("/train-model", response_class=HTMLResponse)
async def train_model(request: Request, ip_report: UploadFile = File(...), loe_model: UploadFile = File(...), actuarial_report: Optional[UploadFile] = File(default=None), training_notes: str = Form(default="")):
    training_id = datetime.now().strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:8]
    training_dir = TRAINING_DIR / training_id
    training_dir.mkdir(parents=True, exist_ok=True)
    try:
        _save_upload(ip_report, training_dir / Path(ip_report.filename or "ip_report").name)
        _save_upload(loe_model, training_dir / Path(loe_model.filename or "loe_model").name)
        if actuarial_report and actuarial_report.filename:
            _save_upload(actuarial_report, training_dir / Path(actuarial_report.filename).name)
        (training_dir / "training_notes.txt").write_text(training_notes or "", encoding="utf-8")
        return templates.TemplateResponse(request, "index.html", {"request": request, "success": True, "training_message": "Training files saved. Future processing can use these paired examples to improve mapping and RAF-style wording.", "supported": ", ".join(sorted(SUPPORTED_REPORT_EXTENSIONS))})
    except Exception as exc:
        return templates.TemplateResponse(request, "index.html", {"request": request, "success": False, "error": str(exc), "traceback": traceback.format_exc(), "supported": ", ".join(sorted(SUPPORTED_REPORT_EXTENSIONS))}, status_code=500)


@app.get("/download/{job_id}/{filename}")
def download(job_id: str, filename: str):
    path = RUNS_DIR / Path(job_id).name / Path(filename).name
    if not path.exists():
        return HTMLResponse("File not found", status_code=404)
    return FileResponse(str(path), filename=path.name)


@app.get("/health")
def health():
    return {"status": "ok", "platform": "RAF LOE AI Medico-Legal Actuarial Web Platform", "version": "5.0", "workflow": ["Upload IP Report", "Read full IP report", "Extract full text", "AI Medico-Legal Actuarial reasoning", "Generate earnings descriptions first", "Populate Report tab", "Populate Summary tab", "Run calculations", "Download"]}
