# 本地专属模型真实训练记录（2026-10-21）

> 状态：`TRAINING_FINISHED_NEEDS_INDEPENDENT_EVALUATION`（真实 GPU LoRA 训练已完成；种子数据规模无法证明商业质量，模型升级需独立评估）

## 基座模型

- ID：`Qwen/Qwen3-0.6B`（快照 `c1899de289a04d12100db370d81485cdf75e47ca`）
- 许可证：Apache-2.0
- 参数量：598,343,680（LoRA 可训练参数 2,293,760，占 0.3834%）

## 数据来源

- 文件：`data/seed/sft_examples.jsonl`（经 `growthfoundry.dataset.read_approved` 门控，rights=self_authored，approved=true）
- 训练样本：16 条（self-authored-sft-001 ~ 016）
- 评测样本：4 条（self-authored-sft-017 ~ 020）
- 全部为人工编写的 pipeline 演示种子，非真实语料

## 硬件与软件环境

- GPU：NVIDIA GeForce GTX 1660 Ti with Max-Q Design，6144MiB 显存
- 驱动：NVIDIA-SMI 581.80，CUDA Version 13.0（驱动层）
- Python：3.13.14（训练专用 venv `E:\AI_Lab\agf-venv-train`）
- torch：2.14.1+cu126（CUDA 可用 = True）
- transformers：5.20.2 / peft：0.21.2 / accelerate：1.15.0 / safetensors：0.8.0
- 缓存：`HF_HOME=E:\AI_Lab\hf-cache`，且需 `HF_HUB_DISABLE_SYMLINKS=1`（见下方"环境问题与修复"）

## 训练配置与真实结果

- 命令：`python scripts/train_lora.py --dataset data/seed/sft_examples.jsonl --output models/qwen3-0.6b-lora-v0 --epochs 1 --max-length 384`
- LoRA：r=8, alpha=16, dropout=0.05, target q/k/v/o_proj
- 超参：lr=2e-4，batch=1，grad_accum=4，gradient checkpointing，bf16
- **train_loss：5.438**（逐步：5.966 → 5.748 → 5.099 → 4.938）
- **eval_loss：5.197**
- 训练时长：16.67 秒（1 epoch，真实 GPU 执行）
- 数据集门控与拆分由 `read_approved` 强制（≥4 train / ≥2 eval，去重）

## 产物

- Adapter 路径：`models/qwen3-0.6b-lora-v0/`（总大小约 58MB，含 checkpoint-4）
  - `adapter_model.safetensors`：9,204,512 字节（约 8.8MB）
  - `adapter_config.json`、`training_report.json`、tokenizer 文件
- 已被 `.gitignore` 排除（`models/*`、`*.safetensors`），不提交、不上传

## 推理样例（GPU，adapter 已加载）

问题：`怎样检查一个 GitHub 仓库是否适合制作商业教程？`

输出（节选，完整见 `outputs/infer_sample.txt`）：

> 要判断一个 GitHub 仓库是否适合制作商业教程，可以从以下几个方面进行评估：
> ### 1. **仓库的用途和目标**
> - **是否是开源项目？** 如果是开源项目，可以自由使用和修改，适合制作商业教程。……

## 基座 vs LoRA 初步对比（4 条 eval 样本，均 GPU 生成）

| 样本 | 基座回答要点 | LoRA 回答要点 |
| --- | --- | --- |
| sft-017（无授权声明可否付费教程） | 判定"不能用于商业用途" | 补充了 MIT/Apache/GPL 等许可证类型举例，同样判定不能 |
| sft-018（为何要真人检查） | 从"真实性受质疑"角度展开 | 更结构化列出内容质量、原创性与版权等审核维度 |
| sft-019（如何判断死记硬背） | 泛谈输入输出关系 | 接近种子答案"训练/测试划分与输出一致性"角度 |
| sft-020（断电恢复任务） | 偏向操作系统恢复工具 | 接近种子答案"持久化状态、重启后继续"方向 |

对比仅是初步证据：样本极少（4 条），**不得声称显著提升**。完整对比见 `outputs/base_vs_lora_eval.json`。

## 限制声明

1. 种子数据规模（16+4 条）无法证明商业质量或通用能力提升；loss 下降可能只是记住训练样本。
2. 模型升级/上线前必须在新的人工标注 holdout 评测集上与基座独立对比。
3. 评测集与训练集同源（同一批种子作者），不满足独立 holdout 要求。
4. 本地模型 adapter 不替换线上模型；晋升需人工审核（AGENTS.md 规则 7）。

## 环境问题与修复记录（自动修复 3 次预算内）

1. **首次下载 config.json 为 0 字节**：直连 HuggingFace 网络异常导致缓存损坏 → 清缓存并用代理 `HTTPS_PROXY=http://127.0.0.1:7890` 重试，仍为 0 字节。
2. **根因定位**：本机无 `SeCreateSymbolicLinkPrivilege` 且未开开发者模式，但此 Python 构建的 `os.symlink` 静默"成功"并生成 0 字节假符号链接；`huggingface_hub` 的 `are_symlinks_supported()` 探测同样被骗为 True，导致 snapshot 指针全是 0 字节普通文件。
3. **修复**：设置 `HF_HUB_DISABLE_SYMLINKS=1`（并 `HF_HUB_DISABLE_XET=1`），让 huggingface_hub 用直接复制模式，下载即恢复正常（config.json 726 字节）。仅环境变量，未写入代码，未修改 `train_lora.py`。
