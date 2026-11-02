# QifSift — 验收记录（ACCEPTANCE）

种子缺陷验收（`test/acceptance_test.py`，真实运行结果见 `test/acceptance_results.txt`）：**13/13 PASS**

## 种子缺陷设计

QIF 文件（`test/seed_statement.qif`）：
1. 撇号两位数年份日期 `03/16'26` → 必须规范化为 2026-03-16 并记录 fix
2. 千分位逗号金额 `1,234.56` → 必须规范化为 1234.56 并记录 fix
3. 一笔完全重复交易（同日期/金额/收款人）→ 必须保留并标记 suspected duplicate
4. `!Type:Invst` 投资段 → 必须警告并跳过，不许猜测转换

QBO 文件（`test/seed_statement.qbo`，OFX 1.x SGML 未闭合标签）：
5. DTPOSTED 带时区后缀 `20260315080000[-5:EST]` → 规范化并记录 fix
6. 重复 FITID → 必须标记

## 断言口径

- 转换笔数与净额精确断言：QIF 4 笔 / 1083.56；QBO 3 笔 / 1199.06
- 复检层独立重读 CSV：行数、净额、ISO 日期、金额可解析，四项全对才 PASS
- 重复交易只标记不删除（资金记录保守口径，与 StatementSift/InvoiceBatch 先例一致）
