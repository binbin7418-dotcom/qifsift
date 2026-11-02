#!/usr/bin/env python3
"""QifSift acceptance test: seeded QIF + OFX files with planted defects.

QIF seed defects: (1) apostrophe two-digit year date, (2) thousands-comma
amount, (3) exact duplicate transaction, (4) an out-of-scope !Type:Invst
section that must be warned about and skipped, never guessed.
OFX seed defects: (5) timezone suffix on DTPOSTED, (6) duplicate FITID.
Asserts exact counts, totals, flags and the re-check verdict.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from qif_sift import convert

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")

QIF = """!Type:Bank
D03/15/2026
T-25.50
PCoffee Shop
MCoffee with Sam
^
D03/16'26
T1,234.56
PPaycheck
LIncome:Salary
^
D03/15/2026
T-25.50
PCoffee Shop
MCoffee with Sam
^
D03/17/2026
T-100.00
PUtility Co
N1042
^
!Type:Invst
D03/18/2026
T-500.00
PIndex Fund Buy
^
"""

OFX = """OFXHEADER:100
DATA:OFXSGML
VERSION:102
<OFX>
<BANKMSGSRSV1>
<STMTTRNRS>
<STMTRS>
<BANKTRANLIST>
<STMTTRN>
<TRNTYPE>DEBIT
<DTPOSTED>20260315080000[-5:EST]
<TRNAMT>-25.50
<FITID>20260315001
<NAME>Coffee Shop
<MEMO>Coffee with Sam
</STMTTRN>
<STMTTRN>
<TRNTYPE>CREDIT
<DTPOSTED>20260316
<TRNAMT>1234.56
<FITID>20260316001
<NAME>Paycheck
</STMTTRN>
<STMTTRN>
<TRNTYPE>DEBIT
<DTPOSTED>20260317
<TRNAMT>-10.00
<FITID>20260315001
<NAME>Bookstore
</STMTTRN>
</BANKTRANLIST>
</STMTRS>
</STMTTRNRS>
</BANKMSGSRSV1>
</OFX>
"""

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def main():
    qif_path = os.path.join(HERE, "seed_statement.qif")
    ofx_path = os.path.join(HERE, "seed_statement.qbo")
    with open(qif_path, "w") as f:
        f.write(QIF)
    with open(ofx_path, "w") as f:
        f.write(OFX)

    s = convert(qif_path, os.path.join(OUT, "qif"))
    check("qif: 4 bank records converted (duplicate kept)", s["count"] == 4, f"got {s['count']}")
    check("qif: net total 1083.56", str(s["total"]) == "1083.56", f"got {s['total']}")
    check("qif: duplicate flagged", len(s["duplicates"]) >= 1, f"got {len(s['duplicates'])}")
    check("qif: two-digit-year + comma fixes recorded", len(s["fixes"]) >= 2, f"got {s['fixes']}")
    check("qif: Invst section warned + skipped", any("Invst" in w for w in s["warnings"]))
    check("qif: re-check PASS", s["recheck_ok"])
    with open(s["csv_path"]) as f:
        body = f.read()
    check("qif: dates normalized to ISO", "2026-03-16" in body and "03/16" not in body)
    check("qif: comma amount normalized", "1234.56" in body)

    s = convert(ofx_path, os.path.join(OUT, "ofx"))
    check("ofx: 3 records converted", s["count"] == 3, f"got {s['count']}")
    check("ofx: net total 1199.06", str(s["total"]) == "1199.06", f"got {s['total']}")
    check("ofx: duplicate FITID flagged", any("FITID" in d for d in s["duplicates"]))
    check("ofx: timezone suffix fix recorded", any("timezone" in x for x in s["fixes"]))
    check("ofx: re-check PASS", s["recheck_ok"])

    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)}/{len(results)} PASS")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
