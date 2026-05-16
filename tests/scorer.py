"""Autoresearch scorer: evaluates agent_skeleton against task2 requirements.

Each dimension returns 0-100.  Total is weighted composite (0-100).
Scores are designed to be monotonic — fixes increase, regressions decrease.

Usage: python3 tests/scorer.py [--verbose]
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent


# ── Dimension 1: 提交协议合规 (15%) ─────────────────────────────


def score_submission_contract() -> dict:
    """run.py CLI entry, env vars, parallel safety, requirements.txt."""
    issues: list[str] = []
    passed: list[str] = []

    run_py = PROJECT / "run.py"
    if not run_py.exists():
        issues.append("run.py not found")
        return {"score": 0, "issues": issues, "passed": passed}

    src = run_py.read_text()

    # CLI entry point
    if 'if __name__ == "__main__":' in src and "sys.argv" in src:
        passed.append("CLI entry point present")
    else:
        issues.append("Missing CLI entry point (if __name__ == '__main__')")

    if "print(run(question))" in src:
        passed.append("prints answer to stdout")
    else:
        issues.append("Does not print answer to stdout")

    # Env var reading — check across ALL source files, not just run.py
    all_src = ""
    for root, _dirs, files in os.walk(PROJECT):
        for f in files:
            if f.endswith(".py"):
                all_src += (Path(root) / f).read_text()
    env_vars = [
        "TASK2_DB_HOST",
        "TASK2_DB_PORT",
        "TASK2_DB_USER",
        "TASK2_DB_PASSWORD",
        "TASK2_DB_NAME",
        "TASK2_BASE_TABLE",
        "TASK2_ACTION_TABLE",
        "ONE_API_URL",
        "ONE_API_KEY",
        "ONE_API_MODEL",
    ]
    for var in env_vars:
        if var in all_src:
            passed.append(f"Reads env var {var}")
        else:
            issues.append(f"Missing env var read: {var}")

    # No global mutable state (check line-by-line, not in comments/docstrings)
    has_global = any(line.strip().startswith("global ") for line in src.splitlines())
    if not has_global and "_build_agent()" in src:
        passed.append("No global mutable state — fresh agent per call")
    else:
        issues.append("Uses global state")

    # requirements.txt
    req = PROJECT / "requirements.txt"
    if req.exists():
        passed.append("requirements.txt present")
    else:
        issues.append("Missing requirements.txt")

    raw = 100 - len(issues) * 12
    return {"score": max(0, min(100, raw)), "issues": issues, "passed": passed}


# ── Dimension 2: 意图路由准确率 (15%) ───────────────────────────


def score_routing() -> dict:
    issues: list[str] = []
    passed: list[str] = []

    router_py = PROJECT / "tools" / "router.py"
    src = router_py.read_text()

    # Profile intent check
    if '"年龄"' in src and '"平均"' in src:
        passed.append("Profile intent handles age and average queries")
    else:
        issues.append("Profile intent may miss average queries")

    # Behavior intent with browse/purchase
    if '"浏览"' in src and '"购买"' in src:
        passed.append("Behavior intent recognizes browse/purchase")
    else:
        issues.append("Behavior intent missing browse/purchase keywords")

    # Retirement intent
    for kw in ['"退休"', '"缺口"', '"积攒"', '"养老金"']:
        if kw in src:
            passed.append(f"Retirement intent recognizes {kw}")
        else:
            issues.append(f"Retirement intent missing {kw}")

    # Proposal intent
    if '"建议书"' in src:
        passed.append("Proposal intent recognized")
    else:
        issues.append("Proposal intent not found")

    # Clause-level extraction
    if "_CLAUSE_SPLIT" in src:
        passed.append("Clause-level scenario/preference separation")
    else:
        issues.append("Missing clause-level extraction")

    raw = 100 - len(issues) * 14
    return {"score": max(0, min(100, raw)), "issues": issues, "passed": passed}


# ── Dimension 3: 假设/观点隔离 (10%) ────────────────────────────


def score_memory_isolation() -> dict:
    issues: list[str] = []
    passed: list[str] = []

    # Check for scenario/preference separation
    has_clear = False
    for root, _dirs, files in os.walk(PROJECT):
        for f in files:
            if f.endswith(".py"):
                path = Path(root) / f
                src = path.read_text()
                if "clear_scenario" in src:
                    passed.append(f"{f}: clear_scenario found")
                    has_clear = True
    if not has_clear:
        issues.append("No clear_scenario — state may leak")

    mem_py = PROJECT / "tools" / "memory_manager.py"
    src = mem_py.read_text()
    if "scenario" in src and "preferences" in src:
        passed.append("Scenario and preferences stored separately")
    else:
        issues.append("Scenario/preferences not separated in MemoryManager")

    raw = 100 - len(issues) * 25
    return {"score": max(0, min(100, raw)), "issues": issues, "passed": passed}


# ── Dimension 4: 数值计算精度 (10%) ─────────────────────────────


def score_formula_accuracy() -> dict:
    issues: list[str] = []
    passed: list[str] = []

    formula_py = PROJECT / "tools" / "formula_engine.py"
    src = formula_py.read_text()

    required_funcs = [
        "calculate_retirement_age",
        "future_value",
        "future_value_annuity",
        "present_value_annuity",
        "present_value_annuity_factor",
        "duration_text",
    ]
    for func in required_funcs:
        if f"def {func}" in src:
            passed.append(f"Formula function: {func}")
        else:
            issues.append(f"Missing formula function: {func}")

    # Run unit tests
    result = subprocess.run(
        [sys.executable, "-m", "unittest", "tests.test_formula", "-v"],
        capture_output=True,
        text=True,
        cwd=PROJECT,
        timeout=30,
    )
    test_count = result.stdout.count("... ok") + result.stdout.count("FAIL")
    if "FAIL" in result.stdout or "ERROR" in result.stdout:
        issues.append("Formula tests have failures")
    else:
        passed.append(f"All formula tests pass ({result.stdout.count('ok')} ok)")

    raw = 100 - len(issues) * 20
    return {"score": max(0, min(100, raw)), "issues": issues, "passed": passed}


# ── Dimension 5: 建议书质量 (20%) ───────────────────────────────


def score_proposal_quality() -> dict:
    issues: list[str] = []
    passed: list[str] = []

    proposal_py = PROJECT / "skills" / "proposal_writer.py"
    src = proposal_py.read_text()

    # Has all 8 sections
    sections = [
        "客户概况",
        "基本假设",
        "养老目标",
        "退休后财富需求测算",
        "产品偏好分析",
        "资产配置方式",
        "其他建议",
        "综合结论",
    ]
    for s in sections:
        if s in src:
            passed.append(f"Proposal section: {s}")
        else:
            issues.append(f"Missing proposal section: {s}")

    # LLM integration
    if "ONE_API_URL" in src and "requests.post" in src:
        passed.append("LLM integration present")
    else:
        issues.append("No LLM integration for proposal polish")

    # Focus points aggregation
    if "focus_points" in src:
        passed.append("Focus points aggregated in proposal")
    else:
        issues.append("Focus points not aggregated")

    raw = 100 - len(issues) * 14
    return {"score": max(0, min(100, raw)), "issues": issues, "passed": passed}


# ── Dimension 6: 资产配置质量 (10%) ─────────────────────────────


def score_allocation_quality() -> dict:
    issues: list[str] = []
    passed: list[str] = []

    alloc_py = PROJECT / "tools" / "allocation_engine.py"
    src = alloc_py.read_text()

    # Risk scoring
    if "risk_score" in src:
        passed.append("Risk scoring present")
    else:
        issues.append("No risk scoring")

    # Lifecycle constraint
    if "_lifecycle_equity_cap" in src:
        passed.append("Lifecycle equity caps")
    else:
        issues.append("Missing lifecycle equity caps")

    # Cash floor
    if "_CASH_FLOOR" in src and "_LIQUID_PRODUCTS" in src:
        passed.append("Cash floor constraint")
    else:
        issues.append("Missing cash floor")

    # Enterprise annuity
    if "enterprise_ann" in src:
        passed.append("Enterprise annuity included in projection")
    else:
        issues.append("Enterprise annuity not in projection")

    # Granularity check (5% or finer)
    if "slots = 20" in src or "slots = 100" in src:
        passed.append("Allocation step ≤5%")
    else:
        issues.append("Allocation step too coarse (>5%)")

    raw = 100 - len(issues) * 17
    return {"score": max(0, min(100, raw)), "issues": issues, "passed": passed}


# ── Dimension 7: 工程健壮性 (10%) ───────────────────────────────


def score_robustness() -> dict:
    issues: list[str] = []
    passed: list[str] = []

    # Check all Python files for common patterns
    for root, _dirs, files in os.walk(PROJECT / "tools"):
        for f in files:
            if f.endswith(".py"):
                path = Path(root) / f
                src = path.read_text()

                # Bare except without logging
                if "except:" in src or "except Exception:" in src:
                    if "logger" not in src:
                        issues.append(f"{f}: bare except without logging")

    # PyMySQL connection handling
    sql_py = PROJECT / "tools" / "sql_executor.py"
    src = sql_py.read_text()
    if "pymysql" in src:
        passed.append("MySQL connector present")
    if "FileNotFoundError" in src:
        passed.append("SQLite path error handled")

    # app.py exists as interactive wrapper
    app_py = PROJECT / "app.py"
    if app_py.exists():
        passed.append("app.py present (interactive mode)")

    raw = 100 - len(issues) * 15
    return {"score": max(0, min(100, raw)), "issues": issues, "passed": passed}


# ── Dimension 8: SQL 正确性 (10%) ───────────────────────────────


def score_sql_correctness() -> dict:
    issues: list[str] = []
    passed: list[str] = []

    sql_py = PROJECT / "tools" / "sql_templates.py"
    src = sql_py.read_text()

    # Correct field: action_typ (not act_typ)
    if "action_typ" in src:
        passed.append("Uses correct field: action_typ")
    else:
        issues.append("Uses wrong field name (not action_typ)")

    # Product mapping CASE
    if "_product_case_expr" in src:
        passed.append("Product mapping CASE expression present")
    else:
        issues.append("Missing product mapping")

    # 非财富 filter
    if "非财富" in src:
        passed.append("非财富 filter applied")
    else:
        issues.append("Missing 非财富 filter")

    # Parameterized queries
    param_count = src.count("%s")
    if param_count > 0:
        passed.append(f"{param_count} parameterized placeholders")
    else:
        issues.append("No parameterized queries")

    # Table names from env vars
    behav_py = PROJECT / "skills" / "behavior_analysis.py"
    behav_src = behav_py.read_text()
    if "prod_typ <> '非财富'" in behav_src:
        passed.append("Behavior analysis filters 非财富")
    else:
        issues.append("Behavior analysis missing 非财富 filter")

    raw = 100 - len(issues) * 17
    return {"score": max(0, min(100, raw)), "issues": issues, "passed": passed}


# ── Dimension 9: 集成测试覆盖率 (bonus) ──────────────────────


def score_test_coverage() -> dict:
    issues: list[str] = []
    passed: list[str] = []

    result = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
        capture_output=True,
        text=True,
        cwd=PROJECT,
        timeout=30,
    )
    output = result.stdout + result.stderr
    total = output.count("... ok")
    failures = output.count("FAIL") + output.count("ERROR")

    passed.append(f"{total} tests pass")
    if failures > 0:
        issues.append(f"{failures} test failures")
    else:
        passed.append("All tests pass (no failures)")

    # Check for specific test categories
    for pattern, label in [
        ("test_integration", "Integration tests"),
        ("test_formula", "Formula unit tests"),
        ("test_router", "Router unit tests"),
        ("test_memory", "Memory unit tests"),
    ]:
        if output.count(pattern) > 1:
            passed.append(f"{label} present")
        else:
            issues.append(f"Missing {label}")

    raw = min(100, total * 2)  # 2 points per passing test, cap at 100
    return {"score": raw, "issues": issues, "passed": passed}


# ── Aggregate ──────────────────────────────────────────────────

DIMENSIONS = [
    ("提交协议合规", score_submission_contract, 0.15),
    ("意图路由准确率", score_routing, 0.15),
    ("假设/观点隔离", score_memory_isolation, 0.10),
    ("数值计算精度", score_formula_accuracy, 0.10),
    ("建议书质量", score_proposal_quality, 0.20),
    ("资产配置质量", score_allocation_quality, 0.10),
    ("工程健壮性", score_robustness, 0.10),
    ("SQL正确性", score_sql_correctness, 0.10),
    ("集成测试覆盖率", score_test_coverage, 0.00),  # bonus, no weight
]


def score_all(verbose: bool = False) -> dict:
    total = 0.0
    results = {}
    for name, scorer_fn, weight in DIMENSIONS:
        result = scorer_fn()
        weighted = result["score"] * weight
        total += weighted
        results[name] = {
            "raw": result["score"],
            "weighted": round(weighted, 1),
            "weight": weight,
            "issues": result["issues"],
            "passed": result["passed"],
        }
        if verbose:
            print(f"\n{'=' * 50}")
            print(f"{name}: raw={result['score']}, weighted={weighted:.1f}")
            for p in result["passed"]:
                print(f"  ✅ {p}")
            for i in result["issues"]:
                print(f"  ❌ {i}")
    return {"total": round(total, 1), "dimensions": results}


def main() -> None:
    verbose = "--verbose" in sys.argv or "-v" in sys.argv
    result = score_all(verbose)
    if not verbose:
        print(f"Total Score: {result['total']}/100")
        for name, info in result["dimensions"].items():
            print(
                f"  {name}: {info['raw']}/100 (weighted: {info['weighted']}) "
                f"[{len(info['issues'])} issues, {len(info['passed'])} passed]"
            )
    print(f"\nFinal Score: {result['total']}/100")


if __name__ == "__main__":
    main()
