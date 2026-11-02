#!/usr/bin/env python3
"""QifSift engine: bank download files (QIF / QBO / QFX / OFX) -> clean CSV,
with a verification pass that re-parses the CSV and proves the books balance.

Deterministic, 100% local, pure standard library.

Usage:
    python qif_sift.py statement.qbo out/
    python qif_sift.py statement.qif out/
Outputs (in out/):
    transactions.csv   - Date,Payee,Memo,Amount,Type,Check #,FITID,Category
    qifsift_report.md  - what was parsed, normalized, flagged and proven
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


def convert(src_path, outdir):
    with open(src_path, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()
    ext = os.path.splitext(src_path)[1].lower()
    if ext == ".qif":
        records, warnings, fixes = parse_qif(text)
        fmt = "QIF"
    elif ext in (".qbo", ".qfx", ".ofx"):
        records, warnings, fixes = parse_ofx(text)
        fmt = ext[1:].upper()
    else:
        raise ValueError(f"unsupported file type {ext} — use .qif, .qbo, .qfx or .ofx")

    # duplicate detection: FITID repeats, and exact (date, amount, payee) repeats
    seen_fitid, seen_row = {}, {}
    duplicates = []
    for i, r in enumerate(records):
        if r["fitid"]:
            if r["fitid"] in seen_fitid:
                duplicates.append(f"row {i + 1}: FITID {r['fitid']} already used by row {seen_fitid[r['fitid']] + 1}")
            else:
                seen_fitid[r["fitid"]] = i
        key = (r["date"], str(r["amount"]), r["payee"])
        if key in seen_row:
            duplicates.append(f"row {i + 1}: same date, amount and payee as row {seen_row[key] + 1}")
        else:
            seen_row[key] = i

    os.makedirs(outdir, exist_ok=True)
    csv_path = os.path.join(outdir, "transactions.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(CSV_HEADER)
        for r in records:
            w.writerow([r["date"], r["payee"], r["memo"], fmt_amount(r["amount"]),
                        r["type"], r["checknum"], r["fitid"], r["category"]])

    total = sum((r["amount"] for r in records), Decimal("0"))
    recheck = recheck_csv(csv_path, len(records), total)

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
    }


def recheck_csv(csv_path, expect_rows, expect_total):
    """Independent re-read: row count, amount sum, ISO dates, numeric amounts."""
    rows = 0
    total = Decimal("0")
    ok = True
    with open(csv_path, newline="", encoding="utf-8") as f:
        r = csv.reader(f)
        header = next(r)
        if header != CSV_HEADER:
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


def run_qifsift(src_path, outdir):
    return convert(src_path, outdir)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(2)
    s = convert(sys.argv[1], sys.argv[2])
    print(f"{s['format']}: {s['count']} transactions, net {fmt_amount(s['total'])}, "
          f"{len(s['duplicates'])} suspected duplicates, re-check "
          f"{'PASS' if s['recheck_ok'] else 'FAIL'}")
    print(f"CSV: {s['csv_path']}\nReport: {s['report_path']}")
