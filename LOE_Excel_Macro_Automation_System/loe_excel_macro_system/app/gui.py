from __future__ import annotations
import tkinter as tk
from tkinter import filedialog, messagebox
from pathlib import Path
from datetime import date
import traceback

from ip_parser import parse_ip_report_ai
from excel_macro_engine import populate_template_openpyxl, run_excel_macro, export_latest_docm_to_pdf

BASE_DIR = Path(__file__).resolve().parents[1]
TEMPLATE_XLSM = BASE_DIR / "templates" / "LOE Izibalo Template (DataMark Analytics).xlsm"
TEMPLATE_DOCM = BASE_DIR / "templates" / "LOE Izibalo Template (DataMark Analytics).docm"

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("RAF LOE AI Automation - Llama / PyTorch / OCR Reader")
        self.geometry("920x720")
        self.ip_report = tk.StringVar(value=str(BASE_DIR / "samples" / "Protean - IP.pdf"))
        self.xlsm_template = tk.StringVar(value=str(TEMPLATE_XLSM))
        self.docm_template = tk.StringVar(value=str(TEMPLATE_DOCM))
        self.output_root = tk.StringVar(value=str(BASE_DIR / "runs"))
        self.past_pre = tk.StringVar(value="0.05")
        self.past_post = tk.StringVar(value="0.05")
        self.future_pre = tk.StringVar(value="0.15")
        self.future_post = tk.StringVar(value="0.25")
        self._build()

    def _browse(self, var, filetypes):
        p = filedialog.askopenfilename(filetypes=filetypes)
        if p:
            var.set(p)

    def _browse_dir(self, var):
        p = filedialog.askdirectory()
        if p:
            var.set(p)

    def _log(self, text):
        self.txt.insert("end", text + "\n")
        self.txt.see("end")
        self.update_idletasks()

    def _build(self):
        frm = tk.Frame(self, padx=10, pady=10)
        frm.pack(fill="both", expand=True)

        def row(r, label, var, cmd=None):
            tk.Label(frm, text=label).grid(row=r, column=0, sticky="w", pady=4)
            tk.Entry(frm, textvariable=var, width=92).grid(row=r, column=1, sticky="we", pady=4)
            if cmd:
                tk.Button(frm, text="Browse", command=cmd).grid(row=r, column=2, padx=4)

        row(0, "Industrial Psychologist Report", self.ip_report, lambda: self._browse(self.ip_report, [
            ("Supported IP reports", "*.pdf *.docx *.doc *.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp"),
            ("PDF files", "*.pdf"),
            ("Word documents", "*.docx *.doc"),
            ("Pictures / scanned pages", "*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp"),
            ("All files", "*.*"),
        ]))
        row(1, "XLSM Template", self.xlsm_template, lambda: self._browse(self.xlsm_template, [("XLSM", "*.xlsm")]))
        row(2, "DOCM Template", self.docm_template, lambda: self._browse(self.docm_template, [("DOCM", "*.docm")]))
        row(3, "Output Root Folder", self.output_root, lambda: self._browse_dir(self.output_root))

        tk.Label(frm, text="Contingencies").grid(row=4, column=0, sticky="w", pady=(12,4))
        cfrm = tk.Frame(frm); cfrm.grid(row=4, column=1, sticky="w")
        for i, (lab, var) in enumerate([("Past Pre", self.past_pre), ("Past Post", self.past_post), ("Future Pre", self.future_pre), ("Future Post", self.future_post)]):
            tk.Label(cfrm, text=lab).grid(row=0, column=i*2, padx=(0,4))
            tk.Entry(cfrm, textvariable=var, width=8).grid(row=0, column=i*2+1, padx=(0,12))

        tk.Button(frm, text="Generate from IP -> Excel -> Word -> PDF", bg="#0b6", fg="white", command=self.run_case).grid(row=5, column=1, sticky="w", pady=10)
        self.txt = tk.Text(frm, height=28, width=110)
        self.txt.grid(row=6, column=0, columnspan=3, sticky="nsew")
        frm.columnconfigure(1, weight=1)
        frm.rowconfigure(6, weight=1)

    def run_case(self):
        try:
            self.txt.delete("1.0", "end")
            self._log("Reading Industrial Psychologist report...")
            case = parse_ip_report_ai(Path(self.ip_report.get()), use_llama=True, llama_model="llama3.1:8b")
            self._log(f"Claimant: {case.get('full_name','')}")
            self._log(f"Attorney: {case.get('attorney_name','')}")
            self._log(f"Extraction method: {case.get('extraction_method','')} ({case.get('extracted_characters',0)} characters)")
            output_root = Path(self.output_root.get())
            output_root.mkdir(parents=True, exist_ok=True)
            case_dir = output_root / f"{case.get('surname','Case')}_{date.today().isoformat()}"
            case_dir.mkdir(parents=True, exist_ok=True)
            out_xlsm = case_dir / TEMPLATE_XLSM.name

            self._log("Populating workbook...")
            populate_template_openpyxl(
                Path(self.xlsm_template.get()),
                out_xlsm,
                case,
                {"past_pre": float(self.past_pre.get()), "past_post": float(self.past_post.get()), "future_pre": float(self.future_pre.get()), "future_post": float(self.future_post.get())}
            )
            self._log(f"Workbook saved: {out_xlsm}")

            self._log("Running Excel VBA macro LOEOpenWordandSave ...")
            run_excel_macro(out_xlsm, Path(self.docm_template.get()).parent, output_root)

            self._log("Exporting latest DOCM to PDF...")
            pdf = export_latest_docm_to_pdf(output_root)
            if pdf:
                self._log(f"PDF: {pdf}")

            self._log("Done.")
            messagebox.showinfo("Success", "Processing complete. Check the output folder.")
        except Exception as e:
            self._log("ERROR")
            self._log(str(e))
            self._log(traceback.format_exc())
            messagebox.showerror("Error", str(e))

if __name__ == "__main__":
    App().mainloop()
