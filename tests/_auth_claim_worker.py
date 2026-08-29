"""AAF-v0.5-A0-PAID-GUARD-001-FIX-003 进程并发 worker。

在**独立 python 进程**内执行一次准入 claim（无 pytest / 无 monkeypatch；使用真实的
resolve_effective_hermes 路径，模型/provider/授权来自环境变量 —— invocation-truth）。

用法：
    python _auth_claim_worker.py <state_dir> [task_id]

依赖 env（调用方注入）：
    AAF_HERMES_MODEL / AAF_HERMES_PROVIDER / AAF_COST_AUTH

stdout 输出一行 JSON 证据（decision / authorization_consumed / ...）；
退出码：0 = ALLOWED_AUTHORIZED_PAID（赢得 claim）；3 = BLOCKED_COST_APPROVAL
（输掉/已消费）；9 = 其他 decision（意外）；2 = 异常。
"""
import json
import os
import sys

from ai_agent_framework import cost_guard as cg


def main() -> int:
    state_dir = sys.argv[1] if len(sys.argv) > 1 else "."
    task_id = (
        sys.argv[2] if len(sys.argv) > 2 else os.environ.get("AAF_FIX003_TASK_ID", "T1")
    )
    rec = cg.evaluate(task_id, "hermes", state_dir=state_dir)
    print(
        json.dumps(
            {
                "task_id": task_id,
                "decision": rec["decision"],
                "authorization_consumed": rec["authorization_consumed"],
                "authorization_matched": rec["authorization_matched"],
                "required_scope": rec.get("required_scope"),
            },
            ensure_ascii=False,
        )
    )
    if rec["decision"] == cg.DECISION_ALLOWED_AUTHORIZED_PAID:
        return 0
    if rec["decision"] == cg.DECISION_BLOCKED_COST_APPROVAL:
        return 3
    return 9


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # 证据可读性：异常也以 JSON 输出
        print(json.dumps({"error": f"{type(exc).__name__}: {exc}"}))
        sys.exit(2)
