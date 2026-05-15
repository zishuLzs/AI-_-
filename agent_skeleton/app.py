from __future__ import annotations

import argparse

from run import run


def interactive_main() -> None:
    parser = argparse.ArgumentParser(description="Pension planning agent (interactive)")
    parser.add_argument("--session-id", default="demo", help="Conversation session id")
    parser.add_argument(
        "--db",
        default=None,
        help="Deprecated — database config is read from environment variables.",
    )
    args = parser.parse_args()

    print("Pension Planning Agent 已启动，输入 quit 退出。")
    print(f"Session ID: {args.session - id}")
    while True:
        question = input(">>> ").strip()
        if question.lower() in {"quit", "exit"}:
            break
        try:
            print(run(question))
        except Exception as exc:
            print(f"[ERROR] {exc}")


if __name__ == "__main__":
    interactive_main()
