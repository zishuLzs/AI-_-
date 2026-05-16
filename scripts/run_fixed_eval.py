from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from predicted_eval_cases import (
    all_multi_turn_sequences,
    calibration_probe_questions,
    single_turn_diverse_cases,
    single_turn_nlp_variant_cases,
)

DB_PATH = ROOT / "calibration_3customers" / "calibration_eval.db"


def normalize(text: str) -> str:
    return (
        text.replace(" ", "")
        .replace("，", ",")
        .replace("：", ":")
        .replace("；", ";")
        .replace("（", "(")
        .replace("）", ")")
    )


def run_one(question: str) -> str:
    code = (
        "import run as _r\n"
        "_r._get_agent().planner.plan = lambda q, s: (_ for _ in ()).throw(Exception('force_local_planner'))\n"
        f"print(_r.run({question!r}))"
    )
    env = os.environ.copy()
    env["TASK2_SQLITE_PATH"] = str(DB_PATH)
    env["ONE_API_URL"] = "http://127.0.0.1:9"
    env["ONE_API_KEY"] = "disabled"
    out = subprocess.check_output(
        [sys.executable, "-c", code],
        text=True,
        env=env,
    )
    return out.strip()


def run_sequence(turns: list[tuple[str, str]]) -> list[str]:
    env = os.environ.copy()
    env["TASK2_SQLITE_PATH"] = str(DB_PATH)
    env["ONE_API_URL"] = "http://127.0.0.1:9"
    env["ONE_API_KEY"] = "disabled"
    code_lines = [
        "import run as _r",
        "_r._get_agent().planner.plan = lambda q, s: (_ for _ in ()).throw(Exception('force_local_planner'))",
        "answers = []",
    ]
    for question, _expected in turns:
        code_lines.append(f"answers.append(_r.run({question!r}))")
    code_lines.append("print('\\n<<<SEP>>>\\n'.join(answers))")
    out = subprocess.check_output(
        [sys.executable, "-c", "\n".join(code_lines)],
        text=True,
        env=env,
    )
    return out.strip().split("\n<<<SEP>>>\n")


def main() -> None:
    subprocess.check_call([sys.executable, str(ROOT / "scripts" / "build_calibration_sqlite.py")])
    cases = list(single_turn_diverse_cases) + list(single_turn_nlp_variant_cases) + list(calibration_probe_questions)
    passed = 0
    for case in cases:
        label, question, expected = case
        answer = run_one(question)
        ok = normalize(expected) in normalize(answer)
        passed += int(ok)
        print(f"[{label}] {'OK' if ok else 'FAIL'} | {question}", flush=True)
        print(f"  返回: {answer}", flush=True)
        print(f"  预期: {expected}", flush=True)
    print(f"单轮通过: {passed}/{len(cases)}", flush=True)

    seq_passed = 0
    for seq in all_multi_turn_sequences:
        answers = run_sequence(seq["turns"])
        ok = True
        print(f"[{seq['label']}] {seq['purpose']}", flush=True)
        for (question, expected), answer in zip(seq["turns"], answers, strict=True):
            turn_ok = normalize(expected) in normalize(answer)
            ok = ok and turn_ok
            print(f"  {'OK' if turn_ok else 'FAIL'} | {question}", flush=True)
            print(f"    返回: {answer}", flush=True)
            print(f"    预期: {expected}", flush=True)
        seq_passed += int(ok)
    print(f"多轮通过: {seq_passed}/{len(all_multi_turn_sequences)}", flush=True)


if __name__ == "__main__":
    main()
