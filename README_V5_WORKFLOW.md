# RAF LOE AI Actuarial System V5

Workflow:
1. Upload IP Report
2. Read full IP report
3. Extract full text
4. AI Medico-Legal Actuarial reasoning
5. Generate pre/post earnings descriptions first
6. Download earnings descriptions
7. Populate Report tab from IP report
8. Populate Summary tab red fields from earnings descriptions
9. Run LOE calculation
10. Download XLSM and actuarial report

AI order:
- PyTorch semantic reasoning first (uses torch if installed).
- Optional PyTorch text generation if ENABLE_PYTORCH_GENERATION=true and transformers are installed.
- Llama/Ollama second via LLAMA_API_URL or local Ollama.
- Deterministic rule fallback last.
