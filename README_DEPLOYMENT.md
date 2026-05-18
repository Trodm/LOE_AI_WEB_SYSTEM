# RAF LOE AI Actuarial Web Platform v3.0

This version is updated from the paired Industrial Psychologist reports, completed LOE Excel calculation models and actuarial reports provided by the user.

## Main workflow
1. Upload an Industrial Psychologist report (PDF, scanned PDF, Word or image).
2. The system extracts pre-accident and post-accident earnings sections.
3. Llama/Ollama is used where available; deterministic PyTorch/rule fallback is used where Llama is unavailable.
4. The Excel Summary tab red fields are overridden with IP report actual values.
5. The Report tab is populated with claimant, attorney, dates, IP report and contingency values.
6. The system generates downloadable:
   - populated XLSM calculation model,
   - earnings description TXT,
   - actuarial DOCX report,
   - PDF report when LibreOffice or Windows Office is available.

## Render settings
Build command:
```
pip install -r requirements.txt
```
Start command:
```
uvicorn app:app --host 0.0.0.0 --port $PORT
```
Environment:
```
PYTHON_VERSION=3.12.1
```
Optional external Llama endpoint:
```
LLAMA_API_URL=https://your-ollama-compatible-endpoint
OLLAMA_MODEL=llama3.1:8b
```

## Important deployment note
Render/Linux cannot run Microsoft Excel/Word macros. This system still produces a populated XLSM and DOCX report on Render. For macro-generated DOCM/PDF, run on Windows with Microsoft Office installed.
