# 本地专属模型真实训练记录 — Round 3 / v2 与统一成长闭环（2026-10-21）

> 状态：v2 训练完成，闭环回归门自动判定 **HOLD**（v2 未通过晋升）；统一成长闭环 `run_growth_loop.py` 全链路首次真实跑通。

## 本轮目标

1. 把「模型自己的训练」固化为一条逻辑清晰的闭环：**数据门控 → 训练 → 独立评估 → 回归门 → 晋升判定 → 记录**，每步落 JSON 证据。
2. 新增回归检测模块（针对 round-2 发现的 019/020 失败模式），让退化被自动检测而非人工逐条判读。

## 新增组件

| 组件 | 文件 | 说明 |
|---|---|---|
| 回归检测 | src/growthfoundry/regression.py | 重复循环检测（020 模式：短语重复 ≥3 次）、参考答案词汇重叠（019 模式：重叠 <0.15 视为答非所问信号）、PROMOTE/HOLD 判定（eval_loss 改善 + 退化不增加 + 新回归数 ≤ 上限） |
| 闭环编排 | scripts/run_growth_loop.py | 五步统一编排，每步 JSON 证据落 `data/reports/growth_loop/`，训练子进程带超时上限，--dry-run 支持，缺证据时保守 HOLD |
| 单元测试 | tests/test_regression.py | 10 项：两种失败模式检测、重叠边界、晋升判定四条 HOLD 路径 + 一条 PROMOTE 路径 |

## v2 数据集（定向扩充）

- `data/seed/sft_examples_v2.jsonl`：**32 train + 4 eval**（eval 与 v0/v1 完全相同，保持三方可比）
- 新增 32 条 train 中：8 条针对 019 失败模式（死记硬背判定/答非所问）、4 条针对 020 失败模式（断点恢复/重复循环）、其余覆盖晋升门规则、过拟合识别、超参教训、证据链与预算机制——全部 self_authored，来自 round-2 真实复盘

## v2 训练与闭环实测（两次运行，均为 GPU 真实执行）

| 运行 | train_loss | eval_loss | 结果 |
|---|---|---|---|
| growth-loop-20261021-201118 | 4.366 | 4.531 | 回归门 HOLD（缺 v1 逐样本证据，正确拒绝判定） |
| growth-loop-20261021-201639 | 4.392 | 4.560 | 回归门 **HOLD**（判定理由见下） |

**第二次运行的自动判定理由**（回归门输出，全部量化）：
1. `eval_loss 4.356 -> 4.560 (NOT improved)` —— v2 比 v1 更差
2. `degenerated samples 3 -> 4 (increased)` —— 退化样本数上升
3. `new regressions: self-authored-sft-018` —— 018 由正常变为重复循环退化

**闭环行为验证**：
- 第一次运行缺前置证据时**保守 HOLD**（HOLD_NO_PREVIOUS_EVIDENCE），没有假装能比较——门控逻辑正确
- 第二次运行三条 HOLD 理由全部由 `regression.py` 自动量化产出，无需人工逐条判读

## 结论与状态

- **v2 未通过晋升**（HOLD），当前最新可用版仍为 **v0**（round-1，eval_loss 5.197，无退化样本）；v1/v2 均保留本机供复盘。
- 闭环结论：32 条小数据 + 2 epochs 的组合在 017（基线即退化）上无法避免过拟合；下一轮要么先扩数据到 100+ 条再训练，要么显著降低 epochs（1）+ 学习率并重新评估。
- 晋升判定现在由代码自动给出（regression.py），但仍只是建议——最终替换需人工审核（AGENTS.md 规则 7 / DATA_POLICY）。

## 使用方式（下一轮直接跑）

```bash
python scripts/run_growth_loop.py --dataset data/seed/sft_examples_v3.jsonl \
  --adapter models/qwen3-0.6b-lora-v3 --prev-adapter models/qwen3-0.6b-lora-v0 \
  --prev-report outputs/base_vs_lora_eval_qwen3-0.6b-lora-v0.json --epochs 1
```

注意：`--prev-adapter` 应指向当前最新可用版（现为 v0），不要用未晋升的 v1/v2 作对比基线。
