import os
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext

from qif_sift import run_merge, run_qifsift


def run_job(src, outdir, dedupe=False):
    """src is a single path (convert) or a list of 2+ paths (merge)."""
    if isinstance(src, (list, tuple)):
        s = run_merge(list(src), outdir, dedupe=dedupe)
        lines = [f"Files merged: {len(s['files'])}"]
        for pf in s["files"]:
            lines.append(f"  {pf['name']}: {pf['count']} transactions, "
                         f"net {pf['total']}, {pf['flags']} duplicate flags")
        lines += [f"Combined transactions: {s['count']}",
                  f"Combined net total: {s['total']}",
                  f"Suspected duplicates flagged (kept): {len(s['duplicates'])}",
                  f"Warnings: {len(s['warnings'])}",
                  f"Re-check: {'PASS' if s['recheck_ok'] else 'FAIL'}"]
        if dedupe:
            lines += [f"Deduped copy: {s['count'] - len(s['removed'])} rows "
                      f"after removing {len(s['removed'])} (see report for reasons)",
                      f"Deduped CSV: {s['deduped_path']}"]
        lines += [f"CSV: {s['csv_path']}", f"Report: {s['report_path']}"]
        return lines
    s = run_qifsift(src, outdir, dedupe=dedupe)
    lines = [f"Format: {s['format']}",
             f"Transactions converted: {s['count']}",
             f"Net total: {s['total']}",
             f"Suspected duplicates flagged (kept): {len(s['duplicates'])}",
             f"Warnings: {len(s['warnings'])}",
             f"Re-check: {'PASS' if s['recheck_ok'] else 'FAIL'}"]
    if dedupe:
        lines += [f"Deduped copy: {s['count'] - len(s['removed'])} rows "
                  f"after removing {len(s['removed'])} (see report for reasons)",
                  f"Deduped CSV: {s['deduped_path']}"]
    lines += [f"CSV: {s['csv_path']}", f"Report: {s['report_path']}"]
    return lines


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("QifSift")
        self.geometry("640x560")
        self.resizable(False, False)
        self.file = tk.StringVar()
        self.merge_files = []
        self.merge_label = tk.StringVar(value="(none — single-file mode)")
        self.dedupe = tk.BooleanVar(value=False)
        row = tk.Frame(self); row.pack(fill="x", padx=12, pady=(12, 2))
        tk.Label(row, text="Statement file (.qif/.qbo/.qfx/.ofx):", width=34, anchor="w").pack(side="left")
        tk.Entry(row, textvariable=self.file, width=38).pack(side="left")
        tk.Button(row, text="Browse", command=lambda: self.pick(self.file,
                  [("Bank files", "*.qif *.qbo *.qfx *.ofx"), ("All files", "*.*")])).pack(side="left", padx=4)
        row2 = tk.Frame(self); row2.pack(fill="x", padx=12, pady=(2, 2))
        tk.Label(row2, text="Or merge several files into one CSV:", width=34, anchor="w").pack(side="left")
        tk.Button(row2, text="Add files...", command=self.pick_merge).pack(side="left", padx=4)
        tk.Button(row2, text="Clear", command=self.clear_merge).pack(side="left")
        tk.Label(self, textvariable=self.merge_label, anchor="w").pack(fill="x", padx=12)
        tk.Checkbutton(self, text="One-click dedupe: also write a deduped CSV "
                                  "(duplicates removed there only; the full CSV is always kept)",
                       variable=self.dedupe, anchor="w").pack(fill="x", padx=12, pady=(6, 0))
        tk.Button(self, text="Convert && re-check", font=("Segoe UI", 11, "bold"),
                  command=self.start).pack(pady=10)
        self.log = scrolledtext.ScrolledText(self, width=76, height=16,
                                             font=("Consolas", 9))
        self.log.pack(padx=12, pady=4)
        self.write("Pick a QIF / QBO / QFX / OFX statement file — or add 2+ files to merge them into one CSV. Nothing is uploaded; the original files are never modified.")

    def write(self, msg):
        self.log.insert(tk.END, str(msg) + "\n")
        self.log.see(tk.END)
        self.update_idletasks()

    def pick(self, var, types):
        p = filedialog.askopenfilename(filetypes=types)
        if p:
            var.set(p)

    def pick_merge(self):
        paths = filedialog.askopenfilenames(
            filetypes=[("Bank files", "*.qif *.qbo *.qfx *.ofx"), ("All files", "*.*")])
        for p in paths:
            if p not in self.merge_files:
                self.merge_files.append(p)
        self._refresh_merge_label()

    def clear_merge(self):
        self.merge_files = []
        self._refresh_merge_label()

    def _refresh_merge_label(self):
        if self.merge_files:
            names = ", ".join(os.path.basename(p) for p in self.merge_files)
            self.merge_label.set(f"Merge mode: {len(self.merge_files)} file(s): {names}")
        else:
            self.merge_label.set("(none — single-file mode)")

    def collect(self):
        dedupe = bool(self.dedupe.get())
        if len(self.merge_files) >= 2:
            for p in self.merge_files:
                if not os.path.isfile(p):
                    raise ValueError(f"Merge file not found: {p}")
            outdir = os.path.join(os.path.dirname(self.merge_files[0]), "qifsift_out")
            return (list(self.merge_files), outdir, dedupe)
        if self.merge_files:
            raise ValueError("Merge needs at least 2 files — add one more, or Clear and use the single file above.")
        src = self.file.get().strip()
        if not src or not os.path.isfile(src):
            raise ValueError("Choose a statement file first.")
        return (src, os.path.join(os.path.dirname(src), "qifsift_out"), dedupe)

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
