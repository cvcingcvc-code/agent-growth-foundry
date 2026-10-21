# 训练记录 — Round 4：本地模型使用与编码能力成长系统

> 日期：2026-10-21 ｜ 分支：feat/local-model-usage-v1（基于 main b8a2ee1）
> 执行环境：GTX 1660 6GB（实测），Windows，agf-venv（smoke）+ agf-venv-train（GPU）

## 0. 本轮目标

按用户 Phase A-E 规范推进「本地模型使用与编码能力成长系统」：
- Phase A：本地模型 CLI（chat_local.py）+ 三个真实示例
- Phase B：冠军注册表修复 + 50 条未见编码任务验收集
- Phase C：100 条候选样本 + 规则审核 + 沙箱流水线 + v3 训练对比
- Phase D：大模型兼容性调研 + 模型注册表
- Phase E：交付 + 推送功能分支

停止条件全部达成（见第 8 节）。

## 1. Phase A：本地模型 CLI（chat_local.py）

**实测完成**。`scripts/chat_local.py` + `tests/test_chat_local.py`（8 项纯逻辑测试）：
- `--question` 单发 / 交互 REPL 两种模式
- 超时保护（threading guard）、`--adapter none` 切基座对照、版本元数据显示

三个真实示例（outputs/chat_examples/）：
- ex1_qa_v0.txt：问答示例
- ex2_code_v0.txt：质数函数生成正确
- ex3_debug_v0.txt：add bug 修复正确 + ex3_debug_base.txt 基座对照

## 2. Phase B：冠军注册表 + 独立验收集

**实测完成**。
- `src/growthfoundry/champion.py`：Champion 注册表（v0 注册于 data/champion.json，eval_loss 5.197）。PROMOTE 仅为建议（pending_human_review），champion_changed 永远 False；adapter_base_compatible 用精确基座 ID 匹配（0.6B adapter 禁止挂大模型）
- `src/growthfoundry/code_metrics.py`：语法正确率/重复循环率/任务相关性/单测通过率/补丁成功率
- `data/eval/coding_eval_v1.jsonl`：**50 条训练时未见过的编码任务**（code_gen/debug/qa）
- `scripts/eval_coding.py`：统一采样（greedy）评估
- v0 冠军编码基线（10 任务）：syntax 1.0 / repetition(2gram) 0.4 / relevance 1.0

## 3. Phase C-1：100 条候选样本 + 规则审核

**实测完成**。`scripts/generate_coding_candidates.py` 生成 `data/seed/coding_candidates_v1.jsonl`：

| 类型 | 数量 | 说明 |
|------|------|------|
| code_gen | 60 | 真实 Python 函数（字符串/列表/字典/数学/循环），函数名与验收集零重叠 |
| debug | 20 | 真实 buggy 代码 + 最小修复，全部 ast 语法检查通过 |
| qa | 14 | 带声明关键词的问答 |
| counterexample_019 | 4 | 答非所问反例（直接最小代码答案，真实任务上） |
| counterexample_020 | 2 | 重复循环反例（最多一句话，真实任务上） |

**规则审核**（`src/growthfoundry/candidate_audit.py` + `scripts/audit_candidates.py`）：
- 首轮实测抓出真问题：debug 任务 target_func 传错、3 条 QA 关键词缺失、1 条 `average` 与 eval-021 真实题目级泄漏——全部修复
- 修复后 **AUDIT_RULES_PASS：100/100 approved，0 泄漏**
- 检测器注入测试：6 类故意坏样本（语法错误/连续重复行/函数未定义/关键词缺失/019 非代码/020 双句）全部抓住（DETECTOR_SANITY_PASS）
- **重要修正**：2-gram 重复检测对代码答案是变量名误报（如 `return False` 两行被判"短语循环"）；重复循环真判据改为**句子级循环**（同句 ≥2 次）+ **连续重复行**（代码形式）；主题词自然重复不标记
- 泄漏扫描排除内置名（len/sum/print）和方法调用（.append）

审核产物：data/seed/coding_approved_v1.jsonl（100 条）+ outputs/audit_candidates_v1.json（含文件 SHA-256）

## 4. Phase C-2：编码沙箱流水线

**实测完成**。`scripts/coding_pipeline.py`：
- 生成 → 隔离执行（子进程 + 硬超时杀进程 + 临时目录隔离）→ test_hint 转译为断言 → 失败分析 → **一次修复重试** → 审核 → 候选池
- 沙箱执行器离线 5 案例全过：正确通过/错误结果/语法错误/**超时杀进程**/NameError
- process_task 5 场景 mock 验证全过：修复成功/修复仍失败（仅一次）/语法错误跳过/一次通过/禁用修复
- **E2E 真实实测**（冠军 v0，3+3 任务）：
  - code_gen 3 任务：3/3 一次通过（ALL_HINTS_PASS）
  - debug 3 任务（021/023/024）：3/3 一次通过——v0 直接修对了除零/平均/递归终止 bug
  - patch 分支未被真实触发（模型表现好），修复逻辑由 mock 场景保证
- 修正记录：E2E 报告中 repetition_loops 3/3 为 2-gram 误报，修正后为 0

## 5. Phase C-3：v3 训练对比实验（核心证据）

**实测完成**。数据集 v3 = 32 条旧 train + 100 条审核通过的编码候选 + 固定 4 条 eval（零重复，数据门控 PASS）。

| 版本 | epochs | lr | train_loss | eval_loss | 训练时长 |
|------|--------|-----|-----------|-----------|---------|
| v3a | 1 | 1e-4 | 2.068 | 4.780 | 140.9s |
| **v3b** | 1 | 2e-4 | **1.917** | **4.458** | 138.1s |
| v0 冠军 | 3 | 2e-4 | 5.438 | 5.197 | （round-1 记录） |

**闭环判定**（run_growth_loop，对冠军 v0 比较）：
- v3a：PROMOTE 建议（eval_loss 改善，退化 4→4 未恶化），pending_human_review=true
- v3b：PROMOTE 建议（eval_loss 5.197→4.458），pending_human_review=true
- **champion_changed 均为 false，冠军指针未动**

**⚠️ 执行级证据推翻表面指标**（outputs/execution_comparison_v0_vs_v3b.json）：

沙箱真实执行 4 个任务（含单断言）：

| 任务 | v0 | v3b |
|------|-----|------|
| eval-001 is_palindrome | PASS | **FAIL**（丢了 `[::-1]`，恒 True） |
| eval-006 remove_duplicates | FAIL | FAIL（两版以不同方式错） |
| eval-009 word_count | PASS | **FAIL**（返回列表非计数） |
| eval-010 second_largest | PASS | PASS |

- v0：3/4 通过；v3b：1/4 通过
- **eval_loss 下降（5.197→4.458）而真实执行通过率下降（3/4→1/4）**
- 两版语法正确率都是 1.0——「语法对但逻辑错」是真实且不可见的风险
- **结论：v3b 不因 eval_loss 晋升；执行级证据优先于表面指标；v0 仍为冠军**

这是 round-2「eval_loss 下降部分来自拟合训练分布」结论在编码任务上的复现与强化：**固定 4 条 eval 的 eval_loss 无法代表 50 条未见任务的真实能力**。

## 6. Phase D：大模型兼容性调研 + 模型注册表

**文档完成**（docs/MODEL_UPGRADE_PATH.md）：
- 本机实测容量：GTX 1660 6GB 训练 0.6B LoRA 可行（v0-v3b 五次真实训练验证）
- 各尺寸评估（文档值）：1.7B 训练紧/4B 需 QLoRA ~8-10GB/8B 需 ~12GB/Coder-30B Q4_K_M 推理 ~19.2GB（本机均不可）
- **核心约束已固化为代码**：`model_registry.py` + `champion.py` 双重拦截——LoRA adapter 与基座维度绑定，0.6B adapter 禁止挂 1.7B/4B/8B/30B（测试含 Coder-30B 拒绝 0.6B adapter 用例）
- 升级路线按 6GB/12GB/24GB/云端分档，换基座迁移清单明确（eval_loss 跨基座不可比）
- 所有非本机数字标注 estimated，未实测不写 PASS

## 7. 测试统计

| 测试文件 | 数量 | 状态 |
|----------|------|------|
| test_core.py | 3 | PASS |
| test_factory.py | 11 | PASS |
| test_regression.py | 11 | PASS |
| test_champion.py | 13 | PASS |
| test_code_metrics.py | 16 | PASS |
| test_chat_local.py | 8 | PASS |
| test_candidate_audit.py | 22 | PASS |
| test_coding_pipeline.py | 10 | PASS |
| test_coding_pipeline_process.py | 6 | PASS |
| test_model_registry.py | 10 | PASS |
| **合计** | **110** | **全部通过（实测）** |

## 8. 停止条件核对

| 停止条件 | 状态 | 证据 |
|----------|------|------|
| v0 真实可交互 | ✅ | chat_local.py 三示例 + 基座对照 |
| 编码任务真实可测试 | ✅ | 沙箱执行器 5 案例 + E2E 6 任务真实执行 |
| 闭环完成一次有证据 PROMOTE/HOLD | ✅ | v3a/v3b 双 PROMOTE 建议（eval_loss+退化门）+ **执行级证据反证 v3b 不该晋升**，冠军未动 |
| 大模型路线写入文档 | ✅ | docs/MODEL_UPGRADE_PATH.md |

## 9. 遗留与下一步

1. **评测集升级**：固定 4 条 eval 对 0.6B 太短（回答过短导致退化检测饱和 4/4）——下轮应把 50 条编码任务中的 10 条固定为标准 eval，配合执行级断言
2. **执行级门控进闭环**：把 sandbox 断言执行接入 run_growth_loop 回归门，让 PROMOTE/HOLD 判定基于执行结果而非 eval_loss
3. **数据继续扩量**：100 → 300+ 条（含执行验证通过的样本），coders 30B 调研已就绪但受硬件限制
4. **A-02 GraphQL 分页 / mcp servers NOASSERTION**：产品工厂轨遗留，未动

## 10. 契约遵守核对

- ✅ 所有文件/训练产物在 E 盘（models/qwen3-0.6b-lora-v3a、v3b）
- ✅ REAL/SMOKE 严格区分：GPU 训练/评测/E2E 为 REAL；process_task 场景为 mock 逻辑验证（明确标注）
- ✅ PROMOTE 不自动覆盖冠军（champion_changed=false）
- ✅ 权重/数据未上传（分支推送不含 models/、HF 缓存）
- ✅ 改动在功能分支 feat/local-model-usage-v1，未动 main
- ✅ 未实测的 VRAM/性能数字全部标注 estimated/DOCUMENTATION_ONLY
