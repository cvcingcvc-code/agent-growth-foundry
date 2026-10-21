# Agent Growth Foundry — AI 自成长产品工厂

**双轨同步启动**：合法来源发现 → 可交付数字产品；同时开始本地小模型训练 → 保存评测 → 数据迭代 → 训练适配器。多个 Agent 根据同一仓库 `AGENTS.md` 协作。

> **截至 2026-10-21（双轨首次交付）**：项目骨架 + 离线产品候选审核演示 + CPU 小模型真实参数训练 (smoke) + **真实 GPU Qwen3-0.6B LoRA 训练完成（GTX 1660 Ti, train_loss 5.438 / eval_loss 5.197, adapter 未上传）** + 产品工厂首个真实闭环（真实采集 3 仓库 → 门控 → 评分 → 2 个原创资料包 READY_FOR_REVIEW）。**这不是** 已能持续无人值守产生收入的产品，也不是一个已经具备高质量生成能力的自训练模型。模型晋升需独立评估（AGENTS.md 规则 7）。

## 分支结构

- `main` 稳定版（双轨合并后：c4f00d8）
- `feat/product-factory-v1` 产品工厂轨道（collector 缓存/评分/构建器，已合并）
- `feat/local-model-training-v1` 本地模型轨道（GPU LoRA 训练记录 + eval 脚本，已合并）
- 所有改动通过分支 + PR / 人工审核进入 main，Agent 不并发修改同一文件

## 一次完整生产闭环（已验证，元数据 only）

```bash
# 1. 采集（ETag 缓存 + 有界重试，最多 10 仓库/次）
python scripts/collect_github.py --repo huggingface/peft --cache data/cache/github_etag.json --output data/inbox/github_candidates.jsonl
# 2. 门控入库（BLOCKED/REVIEW 分级）
python scripts/run_demo.py --input data/inbox/github_candidates.jsonl
# 3. 构建原创资料包（REVIEW 候选 → BUILDING→TESTING→READY_FOR_REVIEW）
python scripts/build_product.py --input data/inbox/github_candidates.jsonl --output-root outputs/product_packs
# 4. 全量测试
python -m unittest discover -s tests -v
```

## 本地 GPU LoRA 迭代（已验证可复现）

```bash
# 训练（需 CUDA GPU；HF 缓存在 E:\AI_Lab\hf-cache，本机需 HF_HUB_DISABLE_SYMLINKS=1）
python scripts/train_lora.py --dataset data/seed/sft_examples.jsonl --output models/qwen3-0.6b-lora-v0 --epochs 1 --max-length 384
# 推理验证
python scripts/infer_lora.py --adapter models/qwen3-0.6b-lora-v0 --question "你的问题"
# 基座 vs LoRA 对比（独立评估初步证据）
python scripts/eval_lora.py --adapter models/qwen3-0.6b-lora-v0
```

## 成长闭环机制

发现资料 → 授权审核（policy.py 门控）→ 知识积累（experience.py 账本）→ 产品生成（builder.py）→ 测试（unittest）→ 修复（≤3 次，超限 BLOCKED）→ 经验总结 → 构建训练样本（dataset.py 准入门）→ 本地微调（train_lora.py）→ 独立评估（eval_lora.py）→ 人工晋升。

- **资源预算**（.env.example）：`GF_MAX_CANDIDATES_PER_RUN=3`、`GF_MAX_RETRIES=3`、`GF_DAILY_USD_BUDGET=0`、`GF_ENABLE_AUTO_PUBLISH=false`；采集每次最多 10 仓库，训练自动修复最多 3 次。
- **数据版本**：训练数据经 dataset.py 门控（rights/approved/split 强制），模型只有通过独立评估才可替换旧版本。
- **暂停/恢复**：授权不明、连续失败、超预算 → 状态置 BLOCKED 待人工审核，SQLite 事件日志可审计。

## 快速开始：无需联网

```bash
python scripts/run_demo.py
python scripts/train_smoke.py --epochs 8
python scripts/check_dataset.py --input data/seed/sft_examples.jsonl
python -m unittest discover -s tests -v
```

`train_smoke.py` 需要本地安装 PyTorch。这次实际训练的是一个很小的中文文本分类模型，证明能够更新权重、保存模型、重新加载和评估，不是大语言模型，也不证明可用于商业场景。

## Windows GPU 实际训练

见 [`docs/WINDOWS_GPU.md`](docs/WINDOWS_GPU.md)。基座 [`Qwen/Qwen3-0.6B`](https://huggingface.co/Qwen/Qwen3-0.6B) 使用 Apache-2.0，微调使用 PEFT/LoRA。正式使用请重新检查许可证和模型版本。

## 目录结构

- `AGENTS.md` 多智能体开发操作契约
- `src/growthfoundry/` 许可证初筛、数据准入、SQLite 状态队列
- `scripts/train_smoke.py` 可在 CPU 真实运行的轻量训练验证
- `scripts/train_lora.py` 在本机 GPU 上训练 Qwen LoRA 的正式入口
- `scripts/infer_lora.py` 加载 Qwen + adapter 本地推理
- `data/seed/` **自编且标记为演示** 的离线种子数据，绝非采集成果
- `docs/ROADMAP.md` 两条轨道并行的长期规划
- `docs/DATA_POLICY.md` 授权/训练数据/安全规范
- `docs/WORK_ITEMS.md` 可导入 GitHub Issues 的实施清单

## 成长原则

- 记忆/检索：可随采集与审核即时增长；**不等于模型参数增长**。
- 本地训练：获得数据且符合授权 → 定期 LoRA → 与基座比较 → 达标再部署。
- 运行预算：默认 0 外部花费、0 自动发布、0 不受限的循环。
- GitHub 无明确许可证的代码、图片和教程不直接用于数字产品或训练。

## 远端仓库与协作

远端仓库：`https://github.com/cvcingcvc-code/agent-growth-foundry`（Public，2026-10-21 首次推送）。所有 Agent 以 `AGENTS.md`、`docs/INTERFACES.md` 作为工作标准；改动通过独立分支 + PR / 人工审核进入 main。

## 增量采集（真正的 API 接入，需用户本机联网）

```bash
python scripts/collect_github.py --repo QwenLM/Qwen3 --repo huggingface/peft --cache data/cache/github_etag.json
python scripts/run_demo.py --input data/inbox/github_candidates.jsonl
```

仅保存公开仓库基本元数据；这一步并未下载源代码，也不能证明获得了许可。默认没有无限循环；未来定时任务由宿主调度，并受配额控制。
