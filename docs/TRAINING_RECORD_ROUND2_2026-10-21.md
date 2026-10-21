# 本地专属模型真实训练记录 — Round 2 / v1（2026-10-21）

> 状态：`TRAINING_FINISHED_NEEDS_INDEPENDENT_EVALUATION`（真实 GPU LoRA 第二轮训练完成；**发现退化样本，不满足晋升条件，v1 不得替换 v0**，需第三轮修订数据或超参）

## 本轮目标

落实「自我训练」成长闭环：扩量自编数据（v0 的 16 train → v1 的 32 train），**固定同一评测集**（sft-017~020 不变），在相同基座上训练 v1，与 v0 和基座做可对比评估。

## 基座与数据

- 基座：`Qwen/Qwen3-0.6B`（Apache-2.0，快照同 round-1：`c1899de2…`）
- 数据：`data/seed/sft_examples_v1.jsonl`
  - **train 32 条**：原 16 条（sft-001~016）+ 新增 32 条 v1 问答（v1-001~032，全部 self_authored，内容来自本项目已验证的规则、门控行为与真实运行经验：ETag 采集、评分规则、状态机、LoRA 超参、HF 符号链接坑、回滚策略等）
  - **eval 4 条**：与 v0 完全相同（sft-017~020 原样复制，未改写），保证 v0/v1 可比
  - `check_dataset.py` 校验 PASS（rights=self_authored，dedup 通过）

## 硬件与软件环境（同 round-1）

- GPU：GTX 1660 Ti Max-Q 6GB / 驱动 581.80 / torch 2.14.1+cu126 / transformers 5.20.2 / peft 0.21.2
- 环境：`E:/AI_Lab/agf-venv-train`；HF 缓存 `E:/AI_Lab/hf-cache`；必须 `HF_HUB_DISABLE_SYMLINKS=1 + HF_HUB_DISABLE_XET=1`
- 命令：`python scripts/train_lora.py --dataset data/seed/sft_examples_v1.jsonl --output models/qwen3-0.6b-lora-v1 --epochs 3 --max-length 384`

## 真实结果

| 指标 | v0（round 1） | v1（round 2） |
|---|---|---|
| train 样本 | 16 | 32 |
| epochs | 1 | 3 |
| train_loss | 5.438 | **4.563** |
| eval_loss（同一 4 条 eval） | 5.197 | **4.356**（-16.2%） |
| 训练时长 | 16.67 s | 142.6 s（GPU 真实执行） |

- v1 eval_loss 相对 v0 在**同一固定评测集**下降 16.2%；eval_loss 与 train_loss 差距 0.21，未出现严重过拟合信号。
- Adapter：`models/qwen3-0.6b-lora-v1/`（adapter_model.safetensors 9,204,512 字节 + checkpoint-16/checkpoint-24），gitignore 排除，未上传。
- 推理验证（GPU）：问题「怎样检查一个 GitHub 仓库是否适合制作商业教程？」→ 输出结构化 5 点检查清单（公开性/开源代码/教程示例/版权信息/许可协议）。

## 基座 vs v1 对比（同一 4 条 eval，GPU 生成，`outputs/base_vs_lora_eval_v1.json`）

| 样本 | 基座 | v1 | 判读 |
|---|---|---|---|
| sft-017（无授权能否付费教程） | 长篇泛谈，结论绕 | **「不能。」** 果断且符合种子立场 | v1 优 |
| sft-018（为何要真人检查） | 长泛谈 | 简洁准确指出错误/不完整需人工审核 | v1 优 |
| sft-019（如何判断死记硬背） | 泛谈但方向正确 | **退化**：答非所问（把"判断死记硬背"答成"死记硬背不正确"） | v1 劣 |
| sft-020（断电恢复任务） | 泛谈恢复方法 | **退化**：句子重复循环（"若程序已断电，需手动重置…"×3） | v1 劣 |

**判读结论（如实）**：eval_loss 下降与生成质量**不一致**——019/020 的退化说明 loss 下降部分来自对训练分布的拟合而非通用能力提升；这正是 AGENTS.md 规则 7 要求独立评估的意义。**v1 不通过晋升，不替换 v0。**

## 限制与下一步

1. eval 仅 4 条且与训练数据同源（同批种子作者），统计效力不足；晋升需新人工标注 holdout。
2. 下一轮修订方向：针对 019/020 失败模式扩充对比样本（死记硬背判定、断点恢复），或降低 epochs/学习率后重训。
3. 训练损失自证进步无效；所有晋升以独立评估为准。
