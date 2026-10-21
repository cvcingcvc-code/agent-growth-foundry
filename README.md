# Agent Growth Foundry — AI 自成长产品工厂

**双轨同步启动**：合法来源发现 → 可交付数字产品；同时开始本地小模型训练 → 保存评测 → 数据迭代 → 训练适配器。多个 Agent 根据同一仓库 `AGENTS.md` 协作。

> **截至 2026-10-21**：项目骨架 + 离线产品候选审核演示 + CPU 小模型真实参数训练 (smoke) + Windows 本地 Qwen3-0.6B LoRA 运行入口。**这不是** 已能持续无人值守产生收入的产品，也不是一个已经具备高质量生成能力的自训练模型。GPU LoRA 仍需在有 CUDA 的 Windows 主机上执行。

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

## 创建远端仓库

GitHub 连接无创建仓库权限。先在浏览器 `https://github.com/new` 创建 **private** 仓库 `agent-growth-foundry`。在项目目录使用：

```bash
git init
git add .
git commit -m "chore: bootstrap dual-track agent foundry and local model training"
git branch -M main
git remote add origin https://github.com/<YOUR_USERNAME>/agent-growth-foundry.git
git push -u origin main
```

仓库建好以后，WorkBuddy/Codex 均以 `AGENTS.md`、`docs/INTERFACES.md` 作为工作标准。

## 增量采集（真正的 API 接入，需用户本机联网）

```bash
python scripts/collect_github.py --repo QwenLM/Qwen3 --repo huggingface/peft
python scripts/run_demo.py --input data/inbox/github_candidates.jsonl
```

仅保存公开仓库基本元数据；这一步并未下载源代码，也不能证明获得了许可。默认没有无限循环；未来定时任务由宿主调度，并受配额控制。
