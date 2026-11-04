#!/usr/bin/env python3
"""QifSift upgrade test: opt-in dedupe dual output + multi-file merge.

Covers the wave-1 upgrade:
1. Default convert is unchanged: duplicates flagged, nothing removed,
   no deduped file written.
2. dedupe=True writes transactions_deduped.csv next to the full CSV,
   with per-row removal reasons in the report.
3. merge_files combines 3 files (sample QIF + sample QBO + a synthetic
   QBO carrying cross-file duplicates) into one CSV with a Source File
   column; per-file and combined totals must reconcile.
4. Merged dedupe removes exactly the flagged later occurrences.
"""
import csv
import os
import sys
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from qif_sift import convert, merge_files

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(HERE, "out", "upgrade")

QIF = os.path.join(ROOT, "sample_statement.qif")
QBO = os.path.join(ROOT, "sample_statement.qbo")
SYNTH = os.path.join(HERE, "synth_statement.qbo")

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def read_rows(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.reader(f))


def main():
    # 1. default behaviour unchanged
    s = convert(QIF, os.path.join(OUT, "default"))
    check("default: 4 rows, duplicate kept", s["count"] == 4, f"got {s['count']}")
    check("default: no deduped file written",
          not os.path.exists(os.path.join(OUT, "default", "transactions_deduped.csv"))
          and s["deduped_path"] is None)

    # 2. single-file dedupe dual output
    s = convert(QIF, os.path.join(OUT, "dedupe"), dedupe=True)
    check("dedupe: full CSV still 4 rows", len(read_rows(s["csv_path"])) == 5)
    rows = read_rows(s["deduped_path"])
    check("dedupe: deduped CSV has 3 data rows", len(rows) == 4, f"got {len(rows) - 1}")
    check("dedupe: exactly 1 row removed", len(s["removed"]) == 1, f"got {len(s['removed'])}")
    check("dedupe: removal carries a reason",
          bool(s["removed"]) and "same date, amount and payee" in s["removed"][0]["reasons"][0])
    check("dedupe: deduped net total 1109.06", str(s["deduped_total"]) == "1109.06",
          f"got {s['deduped_total']}")
    check("dedupe: deduped re-check PASS", s["deduped_recheck_ok"])
    with open(s["report_path"], encoding="utf-8") as f:
        report = f.read()
    check("dedupe: report lists removed count + reason",
          "Rows removed from the deduped copy: 1" in report and "removed row 3" in report)

    # 3. merge without dedupe
    m = merge_files([QIF, QBO, SYNTH], os.path.join(OUT, "merge"))
    check("merge: 11 combined rows", m["count"] == 11, f"got {m['count']}")
    check("merge: combined net 3386.18", str(m["total"]) == "3386.18", f"got {m['total']}")
    per = {pf["name"]: pf for pf in m["files"]}
    check("merge: per-file rows 4/3/4",
          (per["sample_statement.qif"]["count"], per["sample_statement.qbo"]["count"],
           per["synth_statement.qbo"]["count"]) == (4, 3, 4))
    check("merge: per-file totals 1083.56/1199.06/1103.56",
          (str(per["sample_statement.qif"]["total"]), str(per["sample_statement.qbo"]["total"]),
           str(per["synth_statement.qbo"]["total"])) == ("1083.56", "1199.06", "1103.56"))
    check("merge: per-file totals sum to combined total",
          sum((pf["total"] for pf in m["files"]), Decimal("0")) == m["total"])
    check("merge: 8 duplicate flags across the set", len(m["duplicates"]) == 8,
          f"got {len(m['duplicates'])}")
    check("merge: per-file flags 1/3/4",
          (per["sample_statement.qif"]["flags"], per["sample_statement.qbo"]["flags"],
           per["synth_statement.qbo"]["flags"]) == (1, 3, 4))
    rows = read_rows(m["csv_path"])
    check("merge: header carries Source File column", rows[0][-1] == "Source File")
    check("merge: every data row names its source file",
          all(r[-1] in per for r in rows[1:]))
    check("merge: re-check PASS (totals reconcile)", m["recheck_ok"])
    check("merge: no deduped merged file without opt-in",
          not os.path.exists(os.path.join(OUT, "merge", "transactions_merged_deduped.csv")))

    # 4. merge with dedupe
    m = merge_files([QIF, QBO, SYNTH], os.path.join(OUT, "merge_dedupe"), dedupe=True)
    check("merge+dedupe: 7 rows removed", len(m["removed"]) == 7, f"got {len(m['removed'])}")
    rows = read_rows(m["deduped_path"])
    check("merge+dedupe: deduped CSV has 4 data rows", len(rows) == 5, f"got {len(rows) - 1}")
    check("merge+dedupe: deduped net 1029.06", str(m["deduped_total"]) == "1029.06",
          f"got {m['deduped_total']}")
    check("merge+dedupe: deduped re-check PASS", m["deduped_recheck_ok"])
    check("merge+dedupe: full merged CSV still 11 rows",
          len(read_rows(m["csv_path"])) == 12)
    with open(m["report_path"], encoding="utf-8") as f:
        report = f.read()
    check("merge+dedupe: report has per-file table + totals row",
          "| sample_statement.qif | QIF | 4 | 1083.56 | 1 | 1 |" in report
          and "**3386.18**" in report)

    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)}/{len(results)} PASS")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
