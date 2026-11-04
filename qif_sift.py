#!/usr/bin/env python3
"""QifSift engine: bank download files (QIF / QBO / QFX / OFX) -> clean CSV,
with a verification pass that re-parses the CSV and proves the books balance.

Deterministic, 100% local, pure standard library.

Usage:
    python qif_sift.py statement.qbo out/
    python qif_sift.py statement.qif out/
    python qif_sift.py --dedupe statement.qif out/
    python qif_sift.py --merge a.qif b.qbo c.ofx out/
    python qif_sift.py --merge --dedupe a.qif b.qbo out/
Outputs (in out/):
    transactions.csv   - Date,Payee,Memo,Amount,Type,Check #,FITID,Category
    qifsift_report.md  - what was parsed, normalized, flagged and proven
With --dedupe (opt-in; default is flag-only, nothing is ever removed unless
this is switched on) a second CSV is written alongside the full one:
    transactions_deduped.csv - same columns, suspected duplicates removed,
                               each removal listed with its reason in the report
With --merge (2+ input files) one combined CSV is written instead:
    transactions_merged.csv          - all files, plus a Source File column
    transactions_merged_deduped.csv  - only when --dedupe is also given
    qifsift_merge_report.md          - per-file rows/total/duplicates + totals
"""
import csv
import os
import re
import sys
from decimal import Decimal, InvalidOperation

# ---------------------------------------------------------------- amounts

def parse_amount(raw):
    """Return Decimal or None. Handles commas and (parenthesized) negatives."""
    if raw is None:
        return None
    s = str(raw).strip().replace(",", "").replace(" ", "")
    if not s:
        return None
    neg = False
    if s.startswith("(") and s.endswith(")"):
        neg = True
        s = s[1:-1]
    try:
        v = Decimal(s)
    except InvalidOperation:
        return None
    return -v if neg else v


def fmt_amount(v):
    return f"{v:.2f}"

# ---------------------------------------------------------------- dates

def parse_qif_date(raw, fixes):
    """Quicken dates: MM/DD/YYYY, M/D/YY, MM/DD'YY (apostrophe year), ISO."""
    s = raw.strip()
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", s)
    if m:
        y, mo, d = m.groups()
        return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
    m = re.match(r"^(\d{1,2})/(\d{1,2})['/](\d{2,4})$", s)
    if m:
        mo, d, y = m.groups()
        y = int(y)
        if y < 100:
            y += 2000 if y < 70 else 1900
            fixes.append(f"two-digit year in date {raw!r} read as {y}")
        return f"{y:04d}-{int(mo):02d}-{int(d):02d}"
    return None


def parse_ofx_date(raw, fixes):
    """OFX dates: YYYYMMDD, YYYYMMDDHHMMSS, optional [gmt offset:...] suffix."""
    s = raw.strip()
    m = re.match(r"^(\d{4})(\d{2})(\d{2})", s)
    if not m:
        return None
    y, mo, d = m.groups()
    if "[" in s:
        fixes.append(f"timezone suffix dropped from OFX date {raw!r}")
    return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"

# ---------------------------------------------------------------- QIF

QIF_TYPE_MAP = {"Bank": "bank", "CCard": "credit card", "Cash": "cash"}


def parse_qif(text):
    """Yield (records, warnings, fixes). Only Bank/CCard/Cash sections convert;
    other sections (Invst etc.) are counted and warned about, never guessed."""
    records, warnings, fixes = [], [], []
    section = None
    supported = False
    cur = None

    def flush():
        nonlocal cur
        if cur is not None and supported:
            records.append(cur)
        cur = None

    for line in text.splitlines():
        line = line.rstrip("\n")
        if line.startswith("!Type:"):
            flush()
            section = line[6:].strip()
            supported = section in QIF_TYPE_MAP
            if not supported:
                warnings.append(
                    f"section !Type:{section} is out of scope and was skipped "
                    "(only Bank/CCard/Cash transactions convert)")
            continue
        if line.strip() == "^":
            flush()
            continue
        if not line:
            continue
        if cur is None:
            cur = {"date": None, "amount": None, "payee": "", "memo": "",
                   "checknum": "", "category": "", "type": QIF_TYPE_MAP.get(section, ""),
                   "fitid": ""}
        code, val = line[0], line[1:]
        if code == "D":
            cur["date"] = parse_qif_date(val, fixes)
            if cur["date"] is None:
                warnings.append(f"unparseable QIF date {val!r} — row kept with blank date")
                cur["date"] = ""
        elif code == "T":
            amt = parse_amount(val)
            if amt is None:
                warnings.append(f"unparseable QIF amount {val!r} — row dropped")
                cur = None
            else:
                if "," in val:
                    fixes.append(f"thousands separator removed from amount {val!r}")
                cur["amount"] = amt
        elif code == "P":
            cur["payee"] = val.strip()
        elif code == "M":
            cur["memo"] = val.strip()
        elif code == "N":
            cur["checknum"] = val.strip()
        elif code == "L":
            cur["category"] = val.strip()
        # S/E/$ split lines: category already captured from L; splits ignored
    flush()
    return [r for r in records if r.get("amount") is not None], warnings, fixes

# ---------------------------------------------------------------- OFX family

def _tag(block, name):
    m = re.search(rf"<{name}>([^<\r\n]*)", block, re.IGNORECASE)
    return m.group(1).strip() if m else ""


def parse_ofx(text):
    """QBO/QFX/OFX: pull every <STMTTRN> block. Works for OFX 1.x (unclosed
    leaf tags) and OFX 2.x (XML), because leaf values are read by regex."""
    records, warnings, fixes = [], [], []
    blocks = re.findall(r"<STMTTRN>(.*?)</STMTTRN>", text, re.IGNORECASE | re.DOTALL)
    if not blocks:
        warnings.append("no <STMTTRN> transaction blocks found")
    for b in blocks:
        amt = parse_amount(_tag(b, "TRNAMT"))
        if amt is None:
            warnings.append("a transaction block had no readable TRNAMT and was dropped")
            continue
        date = parse_ofx_date(_tag(b, "DTPOSTED"), fixes) or ""
        if not date:
            warnings.append("a transaction block had no readable DTPOSTED — row kept with blank date")
        records.append({
            "date": date,
            "amount": amt,
            "payee": _tag(b, "NAME"),
            "memo": _tag(b, "MEMO"),
            "checknum": _tag(b, "CHECKNUM"),
            "category": "",
            "type": _tag(b, "TRNTYPE"),
            "fitid": _tag(b, "FITID"),
        })
    return records, warnings, fixes

# ---------------------------------------------------------------- pipeline

CSV_HEADER = ["Date", "Payee", "Memo", "Amount", "Type", "Check #", "FITID", "Category"]


def parse_source(src_path):
    """Read one statement file and dispatch to the QIF or OFX parser.
    Returns (records, warnings, fixes, format_label)."""
    with open(src_path, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()
    ext = os.path.splitext(src_path)[1].lower()
    if ext == ".qif":
        records, warnings, fixes = parse_qif(text)
        return records, warnings, fixes, "QIF"
    if ext in (".qbo", ".qfx", ".ofx"):
        records, warnings, fixes = parse_ofx(text)
        return records, warnings, fixes, ext[1:].upper()
    raise ValueError(f"unsupported file type {ext} — use .qif, .qbo, .qfx or .ofx")


def find_duplicates(records):
    """Duplicate detection: FITID repeats, and exact (date, amount, payee)
    repeats. Returns (messages, reasons_by_row): messages are the human
    report lines (row numbers are 1-based over `records`); reasons_by_row
    maps a 0-based record index to every reason that row was flagged."""
    seen_fitid, seen_row = {}, {}
    duplicates = []
    reasons_by_row = {}
    for i, r in enumerate(records):
        if r["fitid"]:
            if r["fitid"] in seen_fitid:
                msg = f"row {i + 1}: FITID {r['fitid']} already used by row {seen_fitid[r['fitid']] + 1}"
                duplicates.append(msg)
                reasons_by_row.setdefault(i, []).append(msg)
            else:
                seen_fitid[r["fitid"]] = i
        key = (r["date"], str(r["amount"]), r["payee"])
        if key in seen_row:
            msg = f"row {i + 1}: same date, amount and payee as row {seen_row[key] + 1}"
            duplicates.append(msg)
            reasons_by_row.setdefault(i, []).append(msg)
        else:
            seen_row[key] = i
    return duplicates, reasons_by_row


def write_csv(csv_path, records, include_source=False):
    header = CSV_HEADER + ["Source File"] if include_source else CSV_HEADER
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        for r in records:
            row = [r["date"], r["payee"], r["memo"], fmt_amount(r["amount"]),
                   r["type"], r["checknum"], r["fitid"], r["category"]]
            if include_source:
                row.append(r.get("source", ""))
            w.writerow(row)


def convert(src_path, outdir, dedupe=False):
    records, warnings, fixes, fmt = parse_source(src_path)

    duplicates, reasons_by_row = find_duplicates(records)

    os.makedirs(outdir, exist_ok=True)
    csv_path = os.path.join(outdir, "transactions.csv")
    write_csv(csv_path, records)

    total = sum((r["amount"] for r in records), Decimal("0"))
    recheck = recheck_csv(csv_path, len(records), total)

    # opt-in one-click dedupe: the full CSV above is always kept untouched;
    # the deduped copy drops only the flagged later occurrences (the first
    # occurrence of each transaction always stays).
    removed, deduped_path, deduped_total, deduped_recheck = [], None, None, None
    if dedupe:
        removed = [{"row": i + 1, "record": records[i], "reasons": reasons_by_row[i]}
                   for i in sorted(reasons_by_row)]
        kept = [r for i, r in enumerate(records) if i not in reasons_by_row]
        deduped_path = os.path.join(outdir, "transactions_deduped.csv")
        write_csv(deduped_path, kept)
        deduped_total = sum((r["amount"] for r in kept), Decimal("0"))
        deduped_recheck = recheck_csv(deduped_path, len(kept), deduped_total)

    report_path = os.path.join(outdir, "qifsift_report.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(f"# QifSift report — {os.path.basename(src_path)}\n\n")
        f.write(f"- Source format: {fmt}\n")
        f.write(f"- Transactions converted: {len(records)}\n")
        f.write(f"- Net total of converted amounts: {fmt_amount(total)}\n")
        dates = [r["date"] for r in records if r["date"]]
        if dates:
            f.write(f"- Date range: {min(dates)} to {max(dates)}\n")
        f.write(f"\n## Normalizations applied ({len(fixes)})\n")
        for x in fixes:
            f.write(f"- {x}\n")
        f.write(f"\n## Suspected duplicates — kept, flagged, never silently deleted ({len(duplicates)})\n")
        for x in duplicates:
            f.write(f"- {x}\n")
        if dedupe:
            f.write(f"\n## One-click dedupe (opt-in, switched ON for this run)\n")
            f.write(f"- Full file kept as-is: transactions.csv ({len(records)} rows)\n")
            f.write(f"- Deduped file written: transactions_deduped.csv "
                    f"({len(records) - len(removed)} rows)\n")
            f.write(f"- Rows removed from the deduped copy: {len(removed)}\n")
            for x in removed:
                r = x["record"]
                f.write(f"- removed row {x['row']}: {r['date']} | {r['payee']} | "
                        f"{fmt_amount(r['amount'])} — {'; '.join(x['reasons'])}\n")
            f.write(f"- Deduped net total: {fmt_amount(deduped_total)}\n")
            f.write(f"- Deduped re-check: {'PASS' if deduped_recheck['ok'] else 'FAIL'} "
                    f"({deduped_recheck['rows']} rows re-parsed, net "
                    f"{fmt_amount(deduped_recheck['total'])})\n")
        else:
            f.write("\n## One-click dedupe (opt-in)\n")
            f.write("- Not enabled for this run: duplicates are flagged above only, "
                    "nothing was removed. Re-run with --dedupe (or tick the box in "
                    "the app) to also write transactions_deduped.csv.\n")
        f.write(f"\n## Warnings ({len(warnings)})\n")
        for x in warnings:
            f.write(f"- {x}\n")
        f.write("\n## Re-check of the written CSV\n")
        f.write(f"- Rows re-parsed: {recheck['rows']}\n")
        f.write(f"- Net total re-parsed: {fmt_amount(recheck['total'])}\n")
        f.write(f"- Verdict: {'PASS' if recheck['ok'] else 'FAIL'}\n")

    return {
        "format": fmt, "count": len(records), "total": total,
        "fixes": fixes, "warnings": warnings, "duplicates": duplicates,
        "csv_path": csv_path, "report_path": report_path,
        "recheck_ok": recheck["ok"], "recheck_rows": recheck["rows"],
        "recheck_total": recheck["total"],
        "dedupe": dedupe, "removed": removed,
        "deduped_path": deduped_path, "deduped_total": deduped_total,
        "deduped_recheck_ok": deduped_recheck["ok"] if deduped_recheck else None,
        "deduped_recheck_rows": deduped_recheck["rows"] if deduped_recheck else None,
    }


def recheck_csv(csv_path, expect_rows, expect_total, header=None):
    """Independent re-read: row count, amount sum, ISO dates, numeric amounts."""
    expect_header = CSV_HEADER if header is None else header
    rows = 0
    total = Decimal("0")
    ok = True
    with open(csv_path, newline="", encoding="utf-8") as f:
        r = csv.reader(f)
        header = next(r)
        if header != expect_header:
            ok = False
        for row in r:
            rows += 1
            amt = parse_amount(row[3])
            if amt is None:
                ok = False
            else:
                total += amt
            if row[0] and not re.match(r"^\d{4}-\d{2}-\d{2}$", row[0]):
                ok = False
    if rows != expect_rows or total != expect_total:
        ok = False
    return {"rows": rows, "total": total, "ok": ok}


def merge_files(src_paths, outdir, dedupe=False):
    """Merge 2+ statement files into one combined CSV with a Source File
    column, plus a merge summary report. Duplicate detection runs over the
    combined set, so repeats across files (e.g. the same account exported
    twice) are caught too. With dedupe=True a second, deduped combined CSV
    is written as well; the full combined CSV is always kept."""
    if len(src_paths) < 2:
        raise ValueError("merge needs at least 2 input files")

    per_file = []
    combined = []
    all_warnings, all_fixes = [], []
    for p in src_paths:
        records, warnings, fixes, fmt = parse_source(p)
        name = os.path.basename(p)
        for r in records:
            r = dict(r)
            r["source"] = name
            combined.append(r)
        per_file.append({
            "path": p, "name": name, "format": fmt, "count": len(records),
            "total": sum((r["amount"] for r in records), Decimal("0")),
            "flags": 0, "removed": 0,
        })
        all_warnings += [f"{name}: {w}" for w in warnings]
        all_fixes += [f"{name}: {x}" for x in fixes]

    duplicates, reasons_by_row = find_duplicates(combined)

    # attribute flags / removals back to the file each combined row came from
    bounds = []
    start = 0
    for pf in per_file:
        bounds.append((start, start + pf["count"], pf))
        start += pf["count"]
    for i, reasons in reasons_by_row.items():
        for lo, hi, pf in bounds:
            if lo <= i < hi:
                pf["flags"] += len(reasons)
                pf["removed"] += 1
                break

    os.makedirs(outdir, exist_ok=True)
    merged_header = CSV_HEADER + ["Source File"]
    total = sum((r["amount"] for r in combined), Decimal("0"))
    csv_path = os.path.join(outdir, "transactions_merged.csv")
    write_csv(csv_path, combined, include_source=True)
    recheck = recheck_csv(csv_path, len(combined), total, header=merged_header)

    removed, deduped_path, deduped_total, deduped_recheck = [], None, None, None
    if dedupe:
        removed = [{"row": i + 1, "record": combined[i], "reasons": reasons_by_row[i]}
                   for i in sorted(reasons_by_row)]
        kept = [r for i, r in enumerate(combined) if i not in reasons_by_row]
        deduped_path = os.path.join(outdir, "transactions_merged_deduped.csv")
        write_csv(deduped_path, kept, include_source=True)
        deduped_total = sum((r["amount"] for r in kept), Decimal("0"))
        deduped_recheck = recheck_csv(deduped_path, len(kept), deduped_total,
                                      header=merged_header)

    report_path = os.path.join(outdir, "qifsift_merge_report.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("# QifSift merge report\n\n")
        f.write(f"- Files merged: {len(per_file)}\n")
        f.write("\n## Per-file summary\n\n")
        f.write("| File | Format | Rows | Net total | Duplicate flags | Rows removed if deduped |\n")
        f.write("|---|---|---|---|---|---|\n")
        for pf in per_file:
            f.write(f"| {pf['name']} | {pf['format']} | {pf['count']} | "
                    f"{fmt_amount(pf['total'])} | {pf['flags']} | {pf['removed']} |\n")
        f.write(f"| **Total** | | **{len(combined)}** | **{fmt_amount(total)}** | "
                f"**{len(duplicates)}** | **{len(reasons_by_row)}** |\n")
        dates = [r["date"] for r in combined if r["date"]]
        if dates:
            f.write(f"\n- Combined date range: {min(dates)} to {max(dates)}\n")
        f.write(f"\n## Normalizations applied ({len(all_fixes)})\n")
        for x in all_fixes:
            f.write(f"- {x}\n")
        f.write(f"\n## Suspected duplicates across the merged set — kept, flagged, never silently deleted ({len(duplicates)})\n")
        for x in duplicates:
            f.write(f"- {x}\n")
        if dedupe:
            f.write(f"\n## One-click dedupe (opt-in, switched ON for this run)\n")
            f.write(f"- Full merged file kept as-is: transactions_merged.csv ({len(combined)} rows)\n")
            f.write(f"- Deduped file written: transactions_merged_deduped.csv "
                    f"({len(combined) - len(removed)} rows)\n")
            f.write(f"- Rows removed from the deduped copy: {len(removed)}\n")
            for x in removed:
                r = x["record"]
                f.write(f"- removed row {x['row']}: {r['date']} | {r['payee']} | "
                        f"{fmt_amount(r['amount'])} | from {r['source']} — "
                        f"{'; '.join(x['reasons'])}\n")
            f.write(f"- Deduped net total: {fmt_amount(deduped_total)}\n")
            f.write(f"- Deduped re-check: {'PASS' if deduped_recheck['ok'] else 'FAIL'} "
                    f"({deduped_recheck['rows']} rows re-parsed, net "
                    f"{fmt_amount(deduped_recheck['total'])})\n")
        else:
            f.write("\n## One-click dedupe (opt-in)\n")
            f.write("- Not enabled for this run: duplicates are flagged above only, "
                    "nothing was removed. Re-run with --dedupe (or tick the box in "
                    "the app) to also write transactions_merged_deduped.csv.\n")
        f.write(f"\n## Warnings ({len(all_warnings)})\n")
        for x in all_warnings:
            f.write(f"- {x}\n")
        f.write("\n## Re-check of the written merged CSV\n")
        f.write(f"- Rows re-parsed: {recheck['rows']}\n")
        f.write(f"- Net total re-parsed: {fmt_amount(recheck['total'])}\n")
        f.write(f"- Sum of per-file totals: {fmt_amount(total)} "
                f"({'matches' if recheck['total'] == total else 'MISMATCH'})\n")
        f.write(f"- Verdict: {'PASS' if recheck['ok'] else 'FAIL'}\n")

    return {
        "files": per_file, "count": len(combined), "total": total,
        "duplicates": duplicates, "warnings": all_warnings, "fixes": all_fixes,
        "csv_path": csv_path, "report_path": report_path,
        "recheck_ok": recheck["ok"], "recheck_rows": recheck["rows"],
        "recheck_total": recheck["total"],
        "dedupe": dedupe, "removed": removed,
        "deduped_path": deduped_path, "deduped_total": deduped_total,
        "deduped_recheck_ok": deduped_recheck["ok"] if deduped_recheck else None,
    }


def run_qifsift(src_path, outdir, dedupe=False):
    return convert(src_path, outdir, dedupe=dedupe)


def run_merge(src_paths, outdir, dedupe=False):
    return merge_files(src_paths, outdir, dedupe=dedupe)


if __name__ == "__main__":
    args = sys.argv[1:]
    dedupe = "--dedupe" in args
    merge = "--merge" in args
    args = [a for a in args if a not in ("--dedupe", "--merge")]
    if merge:
        if len(args) < 3:
            print(__doc__)
            sys.exit(2)
        s = merge_files(args[:-1], args[-1], dedupe=dedupe)
        print(f"MERGE: {len(s['files'])} files, {s['count']} transactions, "
              f"net {fmt_amount(s['total'])}, {len(s['duplicates'])} suspected "
              f"duplicates, re-check {'PASS' if s['recheck_ok'] else 'FAIL'}")
        for pf in s["files"]:
            print(f"  {pf['name']}: {pf['count']} rows, net {fmt_amount(pf['total'])}, "
                  f"{pf['flags']} duplicate flags")
        if dedupe:
            print(f"Deduped: {s['count'] - len(s['removed'])} rows after removing "
                  f"{len(s['removed'])}, net {fmt_amount(s['deduped_total'])}, "
                  f"re-check {'PASS' if s['deduped_recheck_ok'] else 'FAIL'}")
            print(f"Deduped CSV: {s['deduped_path']}")
        print(f"CSV: {s['csv_path']}\nReport: {s['report_path']}")
    elif len(args) == 2:
        s = convert(args[0], args[1], dedupe=dedupe)
        print(f"{s['format']}: {s['count']} transactions, net {fmt_amount(s['total'])}, "
              f"{len(s['duplicates'])} suspected duplicates, re-check "
              f"{'PASS' if s['recheck_ok'] else 'FAIL'}")
        if dedupe:
            print(f"Deduped: {s['count'] - len(s['removed'])} rows after removing "
                  f"{len(s['removed'])}, net {fmt_amount(s['deduped_total'])}, "
                  f"re-check {'PASS' if s['deduped_recheck_ok'] else 'FAIL'}")
            print(f"Deduped CSV: {s['deduped_path']}")
        print(f"CSV: {s['csv_path']}\nReport: {s['report_path']}")
    else:
        print(__doc__)
        sys.exit(2)
