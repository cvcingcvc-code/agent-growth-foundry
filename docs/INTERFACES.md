# 多 Agent 统一接口

各 Agent 统一输出 JSON，并写入 `data/state.db` 和评审工单。最低字段：

```json
{
  "run_id": "2026-10-21-local-001",
  "agent": "trainer",
  "task_id": "B0",
  "status": "SMOKE_PASS",
  "inputs": ["data/seed/sft_examples.jsonl"],
  "artifacts": ["models/smoke/latest.pt"],
  "evidence": ["data/reports/smoke_train.json"],
  "limitations": ["Synthetic seed data, not a useful LLM"]
}
```

允许的状态：`PENDING`, `RUNNING`, `SMOKE_PASS`, `REAL_PASS`, `FAILED`, `BLOCKED`, `REVIEW_REQUIRED`。

版本策略：所有任务独立分支 PR；`main` 为稳定版；release 和模型晋升均人工审核。各 Agent 不并发修改同一个文件；先声明任务所有权。每天汇总：新来源、通过许可的候选、交付产物、训练样本、训练/评测结果、费用和失败原因。
