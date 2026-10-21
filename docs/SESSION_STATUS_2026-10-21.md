# 2026-10-21 First runnable evidence

## 环境事实

- Python 3.13.5, PyTorch 2.10.0+cpu, CPU-only, 5 logical CPU exposed, no CUDA device.
- No cached Qwen model weights and no installed transformers/peft in this sandbox.
- **Cannot claim real Qwen/LoRA training has run**: it needs a local GPU environment with installed packages and model downloads.

## 已运行（本轮真实执行）

1. `python scripts/check_dataset.py` → PASS：16 train、4 eval（所有示例自编，未证明模型能力）。
2. `python scripts/train_lora.py --dry-run` → CONFIG_VALIDATED_ONLY_NOT_TRAINED。
3. `python scripts/run_demo.py` → 3 synthetic candidates checked；1 blocked，2 review；auto publish false；SQLite + report generated。
4. `python scripts/train_smoke.py --epochs 8` → tiny PyTorch classifier weights changed, checkpoint saved & reloaded。
5. `python scripts/infer_smoke.py --text '原创AI工具图文部署教程'` → GUIDE on the saved tiny model (one example, not trustworthy performance evidence).
6. `python -m unittest discover -s tests -v` → 5/5 PASS。

## 模型评估 / 不能夸大

- 训练集：39 条自编小样本（分类）；留出集：9 条。
- 训练前 eval accuracy 2/9；8 轮后 3/9。loss 1.15942 → 1.10219。
- 训练/评测基于极少量人工构造文本，泛化和商业质量 **UNKNOWN**。
- 不授权该模型做法律/许可/发布的自动最终决策。

## 给 WorkBuddy 的后续任务

- 在用户 Windows 电脑核验 `nvidia-smi` 和 CUDA PyTorch。
- 在本机跑 `python scripts/train_lora.py ...`：GPU /下载条件满足才可标记 GPU_TRAINED。
- 连接用户旧资料采集工程，不迁移或删除其历史数据库。
- 通过独立评测后才允许模型版本升级，不能用训练 loss 自证进步。
