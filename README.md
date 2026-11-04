# QifSift

Convert bank download files — **QIF, QBO, QFX, OFX** — into one clean CSV, with suspected duplicates flagged (never silently deleted) and a re-check that proves the converted file balances against the source.

## Why

Banks and Quicken export four overlapping formats; bookkeeping tools each speak one. The well-known converter family sells the four conversions as four separate products at $39.99 each — and none of them re-checks its own output. QifSift does all four formats in one tool and then re-parses the CSV it wrote: row count and net total must match the parsed source exactly, or the report says FAIL.

## Use

**App (Windows):** launch `QifSift.exe`, pick your statement file, click **Convert & re-check**. Output lands in a `qifsift_out` folder next to the statement:

- `transactions.csv` — Date, Payee, Memo, Amount, Type, Check #, FITID, Category
- `qifsift_report.md` — normalizations applied, suspected duplicates, warnings, re-check verdict

Two opt-in extras (in the app and on the command line):

- **One-click dedupe:** tick the dedupe box (or pass `--dedupe`) and you also get `transactions_deduped.csv` — the same table with the suspected duplicates removed. The full `transactions.csv` is always kept untouched, and the report lists every removed row with its reason. Nothing is ever removed unless you switch this on.
- **Merge several files:** use **Add files...** in the app (or `--merge`) to combine 2+ statement files — say one export per account — into a single `transactions_merged.csv` with a Source File column, plus a `qifsift_merge_report.md` showing rows, net total and duplicate count per file and for the combined set. Duplicates are detected across the merged set, so the same account exported twice is caught too. Add `--dedupe` to also get `transactions_merged_deduped.csv`.

**Command line:** `python qif_sift.py statement.qbo out/` · `python qif_sift.py --dedupe statement.qif out/` · `python qif_sift.py --merge --dedupe a.qif b.qbo c.ofx out/`

## What it does

- Parses QIF Bank/CCard/Cash sections and OFX-family (QBO/QFX/OFX) `STMTTRN` blocks, including OFX 1.x files with unclosed tags
- Normalizes dates to ISO (including Quicken's apostrophe two-digit years, e.g. `03/16'26`) and amounts to plain numbers (thousands separators removed)
- Flags duplicate FITIDs and exact date+amount+payee repeats — flagged in the report and **kept** in the CSV; deleting money records is your call
- Warns about anything out of scope instead of guessing: QIF investment sections (`!Type:Invst`) are reported and skipped

## Verified

Seeded acceptance test (13/13 PASS, `test/acceptance_results.txt`): QIF with an apostrophe-year date, a comma amount and an exact duplicate → 4 rows, net 1083.56, duplicate flagged, Invst section warned/skipped; QBO with timezone-suffixed date and repeated FITID → 3 rows, net 1199.06, FITID flagged. Both re-checks PASS.

Upgrade test (26/26 PASS, `test/upgrade_results.txt`): default mode writes no deduped file; `--dedupe` on the sample QIF yields a 3-row deduped CSV (net 1109.06) with the removal reasoned in the report; merging the two samples plus a synthetic QBO with cross-file duplicates yields 11 rows / net 3386.18 with per-file flags 1/3/4, and the merged deduped copy holds 4 rows / net 1029.06 after removing 7. All re-checks PASS.

## Scope

Statement conversion for bookkeeping prep — not a bank sync, not accounting advice. Amounts use exact decimal arithmetic. The original file is never modified. 100% local: no upload, no account.

## Build from source

`pip install pyinstaller`, then `pyinstaller qifsift.spec` — pure standard library, no other dependencies. Or push to GitHub and let the included Actions workflow build the Windows package.
