# --- acceptance_backfill (EVAL_ACCEPTANCE_STANDARD.md P4) ---
# 证据来源: checks.yml
# 命令逐字取自该来源，未增删任何参数。
# 归一: python → python3（本机无 python 别名，实测 Error 127）
.PHONY: eval

# eval 目标 = 真跑验收题库（20 条，调用本仓 API / 解析本仓 artifact）
# + 既有能跑绿的测试。任一失败即 make 失败（run_cases 退出码 1，pytest 非 0）。
eval:
	python3 eval/run_cases.py
	python3 -m pytest tests -q
