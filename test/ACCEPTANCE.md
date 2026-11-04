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

## Wave-1 升级验收（2026-11-04 追加）

升级测试（`test/upgrade_test.py`，结果见 `test/upgrade_results.txt`）：**26/26 PASS**；既有种子验收仍 **13/13 PASS**（默认行为不变）。

- 剔除双输出：默认不写剔除版；`--dedupe` 后全量版 4 行保留、剔除版 3 行（净额 1109.06），报告逐条写明剔除行号与理由，剔除版复检 PASS
- 多文件合并：sample QIF（4 行/1083.56）＋ sample QBO（3 行/1199.06）＋ 合成 QBO（`test/synth_statement.qbo`，4 行/1103.56，含跨文件重复）一次进 → 总 CSV 11 行/净额 3386.18（分项合计对上），带 Source File 列；跨集合重复标记 8 条（分文件 1/3/4）；合并剔除版 4 行/1029.06（剔 7 行），双复检 PASS
- GUI 无头冒烟（Xvfb）：单文件＋勾选剔除、3 文件合并两条路径均走通
