import os
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext

from qif_sift import run_qifsift


def run_job(src, outdir):
    s = run_qifsift(src, outdir)
    return [f"Format: {s['format']}",
            f"Transactions converted: {s['count']}",
            f"Net total: {s['total']}",
            f"Suspected duplicates flagged (kept): {len(s['duplicates'])}",
            f"Warnings: {len(s['warnings'])}",
            f"Re-check: {'PASS' if s['recheck_ok'] else 'FAIL'}",
            f"CSV: {s['csv_path']}",
            f"Report: {s['report_path']}"]


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("QifSift")
        self.geometry("640x520")
        self.resizable(False, False)
        self.file = tk.StringVar()
        row = tk.Frame(self); row.pack(fill="x", padx=12, pady=(12, 2))
        tk.Label(row, text="Statement file (.qif/.qbo/.qfx/.ofx):", width=34, anchor="w").pack(side="left")
        tk.Entry(row, textvariable=self.file, width=38).pack(side="left")
        tk.Button(row, text="Browse", command=lambda: self.pick(self.file,
                  [("Bank files", "*.qif *.qbo *.qfx *.ofx"), ("All files", "*.*")])).pack(side="left", padx=4)
        tk.Button(self, text="Convert && re-check", font=("Segoe UI", 11, "bold"),
                  command=self.start).pack(pady=10)
        self.log = scrolledtext.ScrolledText(self, width=76, height=16,
                                             font=("Consolas", 9))
        self.log.pack(padx=12, pady=4)
        self.write("Pick a QIF / QBO / QFX / OFX statement file. Nothing is uploaded; the original file is never modified.")

    def write(self, msg):
        self.log.insert(tk.END, str(msg) + "\n")
        self.log.see(tk.END)
        self.update_idletasks()

    def pick(self, var, types):
        p = filedialog.askopenfilename(filetypes=types)
        if p:
            var.set(p)
    def collect(self):
        src = self.file.get().strip()
        if not src or not os.path.isfile(src):
            raise ValueError("Choose a statement file first.")
        return (src, os.path.join(os.path.dirname(src), "qifsift_out"))

    def start(self):
        try:
            args = self.collect()
        except Exception as e:
            messagebox.showerror("QifSift", str(e))
            return
        self.write("Working... (the window stays responsive)")
        threading.Thread(target=self._run, args=args, daemon=True).start()

    def _run(self, *args):
        try:
            lines = run_job(*args)
            for line in lines:
                self.after(0, self.write, line)
        except Exception as e:
            self.after(0, self.write, f"ERROR: {e}")


if __name__ == "__main__":
    App().mainloop()
