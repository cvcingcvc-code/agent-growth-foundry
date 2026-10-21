# Windows NVIDIA GPU 首次真实本地 LoRA 训练

> 前提：你在自己的 Windows 电脑上运行，而不是在云端 Agent 对话环境里。需要 Python 3.10/3.11、NVIDIA GPU（建议 ≥8 GB 显存起步；是否够取决于设置和环境）、可用的 CUDA PyTorch 与可下载的模型权重。首次运行会联网下载基座，模型文件很大。

```powershell
cd agent-growth-foundry
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
# 按 https://pytorch.org/get-started/locally/ 安装与你的 CUDA 驱动相适配的 PyTorch
python -m pip install -e ".[train]"
python -c "import torch; print(torch.cuda.is_available()); print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'NO GPU')"
python scripts/check_dataset.py --input data/seed/sft_examples.jsonl
python scripts/train_lora.py --dataset data/seed/sft_examples.jsonl --output models/qwen3-0.6b-lora-v0 --epochs 1 --max-length 384
python scripts/infer_lora.py --adapter models/qwen3-0.6b-lora-v0 --question "怎样检查一个 GitHub 仓库是否适合制作商业教程？"
```

- 默认 Qwen/Qwen3-0.6B 基座；使用 HF 官方权重与 PEFT LoRA，不是从零训练通用模型。
- 本仓库种子数据规模只为验证流程，不能提供可靠的提升。真实训练前优先积累许可明确、质量经过审查的数据，并建立新评测集。
- 若显存不足：缩短 max-length，或换更小基座；不要假装 CUDA PASS，也不要自动进行 CPU 的完整大模型训练。
- 本地模型 adapter 只存在 `models/` 且被 `.gitignore` 排除，不自动上传。
- 如模型许可证、模型版本、依赖接口变化，先重新校验再运行。
