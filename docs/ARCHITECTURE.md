# 技术架构

```text
                               ┌───────────────────────────┐
GitHub API / permitted sources ─▶ Source metadata + license ├───▶ SQLite event log / candidate queue
                               └───────────────────────────┘                   │
                                         ┌────────────────────────────────────┤
                                         ▼                                    ▼
                                  Product Builder                    Training Data Gate
                                  → QA → Review                      → train/eval split
                                  → user feedback                          │
                                         │                                   ▼
                                         └─▶ verified experience ───▶ PEFT/LoRA / local model
                                                                             │
                                                                     offline evaluation
                                                                             │
                                                                     human promotion
```

- Orchestrator: V1 offline CLI/SQLite, future scheduler + restart-safe workers, concurrency=1 default.
- Inference: base model + LoRA adapter loaded locally; optional Ollama/llama.cpp export only after separate compatibility test.
- Memory: raw source evidence, human-reviewed facts, tested lessons and dataset are *separate* stores.
- Training data: immutable manifest with source_id, rights, approved, reviewed_by, split; holdout never exported into active training.
- Secrets: environment variables only, never tracked in GitHub.
- Publication: manual release queue; no automatic monetization flow in V1.

### 实现范围说明（V0.1）

- 已实现：SQLite 审核/事件记录、确定性授权预筛、种子数据校验、真实 CPU 分类器训练及其 reload。
- 已提供待在联网环境验证的实现：GitHub REST 元数据采集器、Qwen LoRA 训练及推理入口。
- 尚未实现：跨设备分布式 Agent 调度、自动生成真实售卖产品、自动接单、GPU 实际 LoRA 权重、线上长周期自运行。
