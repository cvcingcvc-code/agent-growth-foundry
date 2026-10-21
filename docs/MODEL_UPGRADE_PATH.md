# 模型升级路线（Phase D 调研记录）

> 生成时间：2026-10-21 ｜ 分支：feat/local-model-usage-v1
> 状态：DOCUMENTATION_ONLY_NOT_MEASURED（除标注"实测"外，所有 VRAM 数字来自公开量化资料，非本机实测）

## 1. 本机当前容量

实测硬件：NVIDIA GeForce GTX 1660（6GB VRAM，WDDM 模式，CUDA 13.0 驱动 581.80）。

实测结论（本机训练 v0-v3a 验证）：
- Qwen3-0.6B + LoRA（r=8, bf16, gradient checkpointing）：**可训练**，实测通过
- Qwen3-0.6B 推理（greedy）：实测 ~3-6s/回答（200 tokens）
- 0.6B fp16 训练实测占用约 4-5GB VRAM，6GB 卡可用但接近上限

## 2. 各尺寸容量评估（文档值，estimated 标注）

| 模型 | 参数量 | 推理 VRAM (q4) | LoRA 训练 VRAM | 6GB 卡可行性 |
|------|--------|---------------|----------------|--------------|
| Qwen3-0.6B | 0.6B | ~0.6GB | ~4GB fp16（**实测**） | ✅ 训练+推理均可 |
| Qwen3-1.7B | 1.7B | ~1.4GB | ~6GB fp16 (est.) | ⚠️ 推理可，训练紧 |
| Qwen3-4B | 4B | ~2GB | ~8-10GB QLoRA (est.) | ❌ 训练不可，推理可 |
| Qwen3-8B | 8B | ~4.9GB | ~12GB QLoRA (est.) | ❌ 训练不可，推理勉强 |
| Qwen3-Coder-30B-A3B (MoE) | 30B/3.3B active | ~19.2GB (Q4_K_M) | ~17.5GB QLoRA (est.) | ❌ 均不可 |

Qwen3-Coder-30B 量化参考（quantized.uk / getlocalia，2026-10 资料）：
- Q4_K_M：~19.2GB VRAM，~92 tok/s（RTX 4090 实测值，非本机）
- Q5_K_M：~22GB，质量保持 99%
- 本机 6GB 卡完全无法运行任何量化版本

## 3. 核心约束：LoRA adapter 与基座维度绑定

**已实测并固化为代码规则**（`model_registry.py` + `champion.py` 双重检查）：

- PEFT LoRA 权重矩阵的维度 = f(基座隐藏层维度)。0.6B 的 q_proj 是 (Qwen3-0.6B hidden=1024)，8B 的 q_proj 是 (hidden=4096)
- 把 0.6B adapter 挂到 8B 基座 → 权重 shape 不匹配，要么报错要么静默产生乱码
- **0.6B adapter 禁止挂 1.7B/4B/8B/30B 基座；换基座 = 重新训练 adapter**

`champion.py::adapter_base_compatible` 用精确基座 ID 匹配强制执行此规则（曾修复过把 Qwen3-Coder-30B 误归为 Qwen3 同族的正则 bug——同族不同尺寸也不兼容）。

## 4. 升级路线建议（按硬件门槛分档）

### 档位 A：当前硬件可做（6GB 卡）
1. **0.6B 继续迭代**（当前路线）：扩数据 → 调超参 → 编码能力成长闭环
2. **1.7B 推理尝试**（可选）：Q4 量化推理 ~1.4GB 可行；LoRA 训练需 ~6GB，极限可行但需缩短序列长度
3. 建议：先把 0.6B 的数据质量和评测闭环做扎实，小模型方法论可直接迁移

### 档位 B：12GB 卡（RTX 3060/4070 级）
- Qwen3-4B QLoRA 训练（~8-10GB est.）
- Qwen3-8B Q4 推理（~4.9GB）
- 这是"编码能力明显跃升"的最低门槛档

### 档位 C：24GB 卡（RTX 3090/4090 级）
- Qwen3-8B QLoRA 训练（~12GB est.）
- Qwen3-Coder-30B-A3B Q4_K_M 推理（~19.7GB est.，含 4K ctx）
- MoE 编码模型是专业编码能力的质变点

### 档位 D：云端/租用（A6000/多卡）
- Qwen3-Coder-30B QLoRA 训练（~17.5GB est.）
- 完整 256K 上下文推理（Q4_K_M 需 ~46GB）

## 5. 对 GrowthFoundry 项目的具体建议

1. **短期（不变）**：0.6B + 现有成长闭环。当前瓶颈是数据质量（百条级）而非模型尺寸
2. **中期（数据量到 1000+ 条后）**：考虑 1.7B——同家族、tokenizer 兼容、训练流程零改动（只改 base_model id 和 VRAM 预算）
3. **换基座时的迁移清单**：
   - `model_registry.py` 注册新基座 + 更新 ADAPTER_BINDINGS
   - `champion.py` 的兼容检查自动拦截旧 adapter（无需改动）
   - 重新训练 adapter（数据集格式不变，chat template 相同）
   - 重新跑固定评测集建立新基线（eval_loss 跨基座不可比！）
4. **禁止事项**：
   - 禁止把 0.6B adapter 挂到任何更大基座上"试试看"
   - 禁止跨基座比较 eval_loss 并据此晋升
   - 大模型推理数据（tok/s 等）未在本机实测前不得写进任何 PASS 记录

## 6. 数据来源

- 本机实测：GTX 1660 6GB，v0-v3a 训练记录（TRAINING_RECORD_*.md）
- Qwen3-Coder-30B 量化数字：quantized.uk/quant-hub/qwen3-coder-30b-a3b、getlocalia.com（2026-10 同步）
- QLoRA 训练 VRAM 区间：aithinkerlab.com Qwen3 QLoRA 指南（2026）、Unsloth 官方文档转述
- 所有 estimated 数字未在本机验证，使用前必须实测
