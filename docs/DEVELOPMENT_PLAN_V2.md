# V2 方向冻结 — 从工程骨架到可用模型

> 生成时间：2026-11-23 ｜ 状态：**FROZEN — 后续所有 Agent 按此文档执行**
> 前置条件：V1 验收已通过（150/150 测试 PASS，冠军 v0 已注册，双轨首次交付完成）

## 目标定义

**V2 终极验收标准 — 什么叫「可用模型」：**

1. 在固定 50 题编码回归集上 **pass@1 ≥ 50%**（真实沙箱执行，非文本相似度）
2. 本地推理 CLI 支持**多轮对话**（≥3 轮上下文连贯）
3. 提供 **HTTP API 服务**（OpenAI 兼容 `/v1/chat/completions`）
4. 训练数据 ≥ **2,000 条**（已审核、去重、执行验证通过）
5. 至少完成 **1 次冠军换代**（v-next 通过执行级回归门取代 v0）

以上 5 项全部达成 = V2 验收通过。任何一项未达成，不得声称「模型可用」。

---

## 阶段总览

```
Phase 0 (Bug 修复)  ──▶  Phase 1 (数据基建)  ──▶  Phase 2 (训练升级)
                                                         │
Phase 3 (服务化)  ◀──────────────────────────────────────┘
      │
Phase 4 (自动化)  ──▶  Phase 5 (模型跃升，视硬件条件)
```

每个 Phase 有独立停止条件；Phase 之间有依赖关系，不可跳跃。

---

## Phase 0：Bug 修复（P0 — 阻塞后续所有工作）

> 预估工期：1-2 天 ｜ 依赖：无

### 0-1 修复成长闭环门控仲裁逻辑 🔴

**文件**：`scripts/run_growth_loop.py` 第 249-256 行

**现状**：exec_gate 判定 PROMOTE 时直接覆盖 final_decision，忽略了 regression 层的 HOLD。

**修复规范**：

```python
# 修复后：取二者更严格者
if exec_decision is not None:
    if exec_decision['decision'] == 'HOLD':
        final_decision = 'HOLD'
        hold_reasons.append(f"exec_gate: {exec_decision.get('reason', '')}")
    elif exec_decision['decision'] == 'PROMOTE' and final_decision == 'HOLD':
        pass  # regression 层已 HOLD，不覆盖
    elif exec_decision['decision'] == 'PROMOTE':
        final_decision = 'PROMOTE'
```

**验收**：单测覆盖「exec PROMOTE + regression HOLD → 最终 HOLD」场景。

### 0-2 修复 store.py 状态更新缺陷 🟡

**文件**：`src/growthfoundry/store.py`

**现状**：`put()` 使用 `INSERT OR IGNORE`，已存在候选的 state 字段无法更新。

**修复规范**：增加 `advance_state(source_id, new_state, reason)` 方法，使用 `UPDATE` 推进状态；`put()` 保持原有语义（仅首次入库）。上层 `builder.py` 中所有裸 SQL 改为调用 `advance_state()`。

**验收**：单测覆盖 put→advance_state→list_items 状态变更可见。

### 0-3 修复 test_core.py 导入路径 🟡

**文件**：`tests/test_core.py` 第 53 行

**修复**：在文件顶部增加 `sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))` 或改用相对导入。

**验收**：从任意目录执行 `python -m pytest tests/test_core.py` 通过。

### 0-4 修复数据集笔误 🟢

- `data/eval/coding_regression_fixed.jsonl` 第 4、7 题：`/n` → `\n`
- `scripts/generate_coding_candidates.py` 第 336 行 ce-020-a：while 题目配 for 答案 → 改为 while 实现

**验收**：`python scripts/audit_candidates.py` 全量通过；回归集 hash 更新后在 champion 证据中重新锚定。

### Phase 0 停止条件

- [ ] 上述 4 项全部修复
- [ ] `python -m pytest tests/ -v` 全量通过（从项目根目录和任意目录）
- [ ] 提交到独立分支 `fix/v2-bugs`，PR 描述附带每项修复的 diff 和测试证据

---

## Phase 1：数据基础建设（P0 — 最高优先级）

> 预估工期：1-2 周 ｜ 依赖：Phase 0 完成

### 1-1 批量编码任务生成器

**新建文件**：`scripts/generate_coding_v2.py`

**规范**：
- 基于**参数化模板 + 变量组合**批量生成 Python 编程任务
- 支持 5 种任务类型：`code_gen`（函数实现）、`debug`（bug 修复）、`refactor`（重构优化）、`explain`（代码解释）、`multi_step`（多步骤任务）
- 每种类型内置 ≥20 个模板，每模板 ≥5 种变量组合 → 单次运行 ≥500 条
- 所有生成的 code_gen/debug 任务必须附带 `test_hint`（≥3 个断言）
- 所有答案必须通过 `ast.parse` 语法检查
- 输出格式与现有 `coding_approved_v1.jsonl` schema 完全一致
- 自动去重：与现有 approved 池和 eval 集的函数名零重叠

**验收**：
- 生成 ≥500 条，`audit_candidates.py` 全量通过
- 新增的 test_hint 断言在沙箱中真实执行参考答案，100% PASS

### 1-2 执行验证过滤器

**新建文件**：`scripts/verify_candidates_exec.py`

**规范**：
- 读取生成的候选样本，对每条 code_gen/debug 任务：
  1. 在受限沙箱中执行 `reference_answer`
  2. 运行 `test_hint` 断言
  3. 参考答案执行失败的样本标记 `verified=false` 并剔除
- 输出已验证池 `data/seed/coding_verified_v2.jsonl`
- 记录验证报告（通过/失败/超时/语法错误各多少条）

**验收**：输出 ≥400 条 verified=true 的样本。

### 1-3 多轮对话样本构造

**新建文件**：`scripts/generate_multiturn.py`

**规范**：
- 构造编码辅助的多轮交互场景（2-4 轮）
- 场景类型：追问细节 → 完善实现、报错 → 调试 → 修复、需求变更 → 代码调整
- ≥200 条多轮样本，每条 messages 长度 4-8
- 格式兼容 chat template（user/assistant 交替）

**验收**：`dataset.py` 门控通过，`check_dataset.py` 报告无异常。

### 1-4 评测集扩充与固定

**修改文件**：`data/eval/coding_regression_fixed.jsonl`

**规范**：
- 从 coding_eval_v1.jsonl 的 50 题中精选 40 题 → 固定回归集（替换当前 10 题）
- 每题 ≥5 个断言（含正常值、边界值、异常值）
- 总断言数 ≥200 个
- 计算新 SHA-256 hash，更新 champion 基线证据

**新建文件**：`data/eval/coding_eval_v2.jsonl`
- 新增 50 题（与训练集和固定回归集零重叠）→ 总评测题库 100 题
- 用于 pass@k 和消融实验，不用于回归门

**验收**：
- 固定回归集 40 题 × ≥5 断言 = ≥200 断言
- v0 冠军在新回归集上跑一次基线（`eval_coding_exec.py`），记录通过率
- 评测集 v2 与所有训练数据函数名零重叠（`scan_eval_leakage` 通过）

### 1-5 合并训练数据集

**产出文件**：`data/seed/sft_examples_v4.jsonl`

**规范**：
- 合并来源：sft_examples.jsonl (20) + coding_verified_v2.jsonl (≥400) + multiturn (≥200)
- 总量 ≥ **620 条 train + ≥50 条 eval**
- 全量通过 `dataset.py` 门控 + `candidate_audit.py` 审核 + 去重
- 记录数据集 SHA-256 指纹

**验收**：`python scripts/check_dataset.py --input data/seed/sft_examples_v4.jsonl` 报告 ≥620 train / ≥50 eval / 0 duplicates。

### Phase 1 停止条件

- [ ] sft_examples_v4.jsonl ≥ 620 条 train + ≥ 50 条 eval
- [ ] 固定回归集 40 题 ≥ 200 断言
- [ ] v0 在新回归集上的基线证据已生成
- [ ] 所有样本通过审核 + 去重 + 执行验证
- [ ] 提交到独立分支 `feat/data-v2`

---

## Phase 2：训练与评估体系升级

> 预估工期：2 周 ｜ 依赖：Phase 1 完成

### 2-1 训练脚本升级

**修改文件**：`scripts/train_lora.py`

**新增能力**：
- `--lr-search`：自动扫描 learning rate [5e-5, 1e-4, 2e-4, 5e-4]，记录最优
- `--rank`：LoRA rank 参数化（默认 8，支持 4/8/16/32）
- `--alpha`：LoRA alpha 参数化（默认 rank*2）
- `--max-length`：从 384 提升默认值到 **512**
- `--early-stop`：基于 eval_loss 的 patience 早停（默认 patience=3）
- `--curriculum`：课程学习模式，先训简单样本（code_gen）→ 后训复杂样本（debug/multi_step）
- 训练结束自动输出训练曲线 PNG（matplotlib，保存到 outputs/）

**不改变**：
- 仍强制 CUDA（无 GPU 不虚报）
- 仍使用 `dataset.py` 门控
- 仍输出训练报告 JSON

**验收**：
- lr-search 在 v4 数据上跑完 4 组实验，记录最优 lr
- 早停在 eval_loss 连续 3 epoch 不下降时正确终止
- 训练曲线 PNG 可读

### 2-2 综合评估框架

**新建文件**：`scripts/eval_comprehensive.py`

**规范**：
- 在 100 题评测集上运行推理（greedy + temperature=0.6 各一次）
- 计算指标：
  - `pass@1`（greedy）和 `pass@5`（temperature 采样 5 次取最优）
  - 语法正确率
  - 执行通过率（沙箱真实执行）
  - 重复循环率
  - 任务相关性
- 输出综合评估报告 JSON + 人可读 Markdown 摘要
- 与冠军基线自动对比（若基线存在）

**验收**：v0 冠军的综合评估报告已生成，作为 V2 基线。

### 2-3 执行级门控接入新回归集

**修改文件**：`scripts/run_growth_loop.py`

**规范**：
- Step 3.5 执行门使用新的 40 题回归集
- 新增 Step 3.6：综合评估（`eval_comprehensive.py`），pass@1 ≥ 50% 为晋升必要条件
- 最终裁决 = min(exec_gate, regression_gate, comprehensive_gate)，取最严格

**验收**：在 v4 数据上完成一次完整的 `run_growth_loop.py --exec-policy reviewed` 全链路运行，输出 PROMOTE 或 HOLD 裁决。

### 2-4 首次冠军换代尝试

**目标**：使用 v4 数据集训练 v4 adapter，通过所有门控取代 v0。

**执行步骤**：
1. `python scripts/train_lora.py --dataset data/seed/sft_examples_v4.jsonl --output models/qwen3-0.6b-lora-v4 --lr-search --rank 16 --max-length 512 --early-stop`
2. `python scripts/run_growth_loop.py --candidate models/qwen3-0.6b-lora-v4 --exec-policy reviewed`
3. 若 PROMOTE 且 pass@1 ≥ 50% → 人工审核后更新 `data/champion.json`
4. 若 HOLD → 分析失败原因，记录到 `docs/TRAINING_RECORD_V4.md`，回到 Phase 1 补充数据

**验收**：
- 训练记录完整（lr/rank/epochs/loss 曲线/执行通过率）
- 若晋升：champion.json 指向 v4，旧基线存档
- 若未晋升：失败原因文档化，可回溯

### Phase 2 停止条件

- [ ] train_lora.py 支持 lr-search / rank / early-stop / curriculum
- [ ] eval_comprehensive.py 输出 pass@1 / pass@5 / 执行通过率
- [ ] 至少完成 1 次完整的 run_growth_loop 全链路运行
- [ ] v4 训练结果记录完整（无论 PROMOTE 还是 HOLD）
- [ ] 提交到独立分支 `feat/training-v2`

---

## Phase 3：服务化

> 预估工期：1-2 周 ｜ 依赖：Phase 2 完成（至少有一个通过回归门的冠军）

### 3-1 HTTP 推理服务

**新建文件**：
- `src/growthfoundry/server/__init__.py`
- `src/growthfoundry/server/app.py` — FastAPI 应用
- `src/growthfoundry/server/routes.py` — OpenAI 兼容路由
- `src/growthfoundry/server/streaming.py` — SSE 流式输出
- `scripts/serve.py` — 启动入口

**规范**：
- `POST /v1/chat/completions`：OpenAI 兼容格式（messages/temperature/max_tokens/stream）
- `GET /v1/models`：返回当前冠军信息
- `GET /health`：健康检查
- 自动加载 `data/champion.json` 指向的 adapter
- 基座兼容检查复用 `chat_local.py` 的 `adapter_base_matches()`
- 推理超时保护复用 `DeadlineStoppingCriteria`
- 默认绑定 `127.0.0.1:8080`

**新增依赖**：`pyproject.toml` 增加 `[project.optional-dependencies] serve = ["fastapi>=0.100", "uvicorn>=0.20", "sse-starlette>=1.6"]`

**验收**：
- `curl http://localhost:8080/v1/chat/completions -d '{"messages":[{"role":"user","content":"写一个冒泡排序"}]}'` 返回正确 JSON
- 流式模式 `stream=true` 逐 token 返回
- 无 GPU 时返回 503 而非崩溃

### 3-2 chat_local.py 多轮对话支持

**修改文件**：`scripts/chat_local.py`

**规范**：
- REPL 模式保留对话历史（最近 5 轮 user/assistant）
- `--history-len` 参数控制历史轮数
- `/clear` 命令清空历史
- `/info` 命令显示当前模型信息

**验收**：
- 连续提问 3 个相关问题，第 3 轮回答能引用前文信息
- `/clear` 后模型不再记得之前的对话

### 3-3 Gradio Web 界面

**新建文件**：`scripts/web_ui.py`

**规范**：
- 对话面板：多轮聊天，支持代码高亮
- 模型信息面板：当前冠军版本、基座、eval_loss、pass@1
- 训练历史面板：从 `data/model_history.jsonl` 读取趋势图
- 默认端口 7860

**新增依赖**：`pyproject.toml` 增加 `ui = ["gradio>=4.0"]`

**验收**：
- 浏览器访问 `http://localhost:7860` 可正常对话
- 模型信息面板显示正确的冠军数据

### Phase 3 停止条件

- [ ] HTTP API 通过 curl 手工测试（同步 + 流式）
- [ ] chat_local 多轮对话 3 轮连贯
- [ ] Gradio 界面可访问且功能正常
- [ ] 提交到独立分支 `feat/serving-v1`

---

## Phase 4：自动化与 CI/CD

> 预估工期：1 周 ｜ 依赖：Phase 0 完成（可与 Phase 1-3 并行）

### 4-1 GitHub Actions 测试流水线

**新建文件**：`.github/workflows/test.yml`

**规范**：
```yaml
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest  # 仅运行不依赖 GPU 的测试
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.11' }
      - run: pip install -e ".[smoke]"
      - run: python -m pytest tests/ -v --tb=short -k "not cuda and not gpu"
```

**验收**：PR 自动触发测试，badge 显示在 README。

### 4-2 经验检索模块

**新建文件**：`src/growthfoundry/experience_store.py`（替代现有 `experience.py` 的 stub）

**规范**：
- 结构化存储：SQLite 表（task_id, task_type, error_type, lesson, resolution, timestamp）
- 检索接口：`search_similar(task_type, error_description, top_k=5)` → 返回相关历史教训
- 失败样本导出：`export_negative_samples()` → 输出可用于 DPO 的偏好对数据
- 写入接口保持与现有 `record_experience()` 兼容

**验收**：
- 写入 10 条不同类型的经验，按 task_type 检索命中 ≥80%
- 导出的负样本格式与 DPO 训练脚本兼容

### 4-3 本地调度脚本

**新建文件**：`scripts/schedule_loop.py`

**规范**：
- 使用 Python `schedule` 库或 Windows Task Scheduler 注册
- 可配置：采集频率（默认每天 1 次）、训练频率（默认每周 1 次）、评估（训练后自动触发）
- 每次运行受 `.env` 中 `GF_MAX_CANDIDATES_PER_RUN` 和 `GF_MAX_RETRIES` 限制
- 运行日志追加到 `data/logs/schedule.log`

**验收**：手动触发一次完整循环（采集→评估→记录），日志正确写入。

### Phase 4 停止条件

- [ ] GitHub Actions 在 PR 上自动运行测试
- [ ] experience_store.py 检索功能可用
- [ ] schedule_loop.py 可手动触发一次完整循环
- [ ] 提交到独立分支 `feat/automation-v1`

---

## Phase 5：模型能力跃升（视硬件条件）

> 预估工期：2-4 周 ｜ 依赖：Phase 2 完成 + 硬件条件满足

### 路线选择（三选一，根据硬件决定）

#### 路线 A：0.6B 极限挖掘（当前硬件即可）

适用条件：不打算升级硬件

| 策略 | 文件 | 预期效果 |
|------|------|----------|
| LoRA rank 32 + alpha 64 | train_lora.py | 增加可学习参数 |
| 数据继续扩量到 2000+ | generate_coding_v2.py | 更多样化的训练信号 |
| DPO 偏好对齐 | 新建 scripts/train_dpo.py | 利用失败样本做负样本训练 |
| 课程学习 | train_lora.py --curriculum | 避免困难样本导致退化 |
| 长上下文训练 | --max-length 768 | 提升多轮对话能力 |

验收：pass@1 ≥ 50%（0.6B 的合理上限）

#### 路线 B：升级到 Qwen3-1.7B（需 8-12GB 显卡）

适用条件：升级到 RTX 3060 12GB 或云端 GPU

| 任务 | 文件 | 说明 |
|------|------|------|
| 注册 1.7B 基座 | model_registry.py | 添加 Qwen3-1.7B 规格 |
| QLoRA 4-bit 训练 | train_lora.py + bitsandbytes | 4-bit 量化节省显存 |
| 重新训练 adapter | — | 0.6B adapter 不可用于 1.7B |
| 重跑基线 | eval_comprehensive.py | eval_loss 跨基座不可比 |
| 新冠军注册 | champion.py | 完整走一遍晋升流程 |

验收：1.7B pass@1 ≥ 60%

#### 路线 C：API 蒸馏（需外部 API 预算）

适用条件：有 OpenAI/Claude API 预算

| 任务 | 文件 | 说明 |
|------|------|------|
| 蒸馏数据生成 | 新建 scripts/distill_from_api.py | 调用大模型生成高质量训练数据 |
| 人工 + 执行验证 | verify_candidates_exec.py | 过滤错误/幻觉答案 |
| 蒸馏数据训练 | train_lora.py | 在 0.6B 上利用蒸馏数据训练 |
| 合规标注 | dataset.py | 标注 `rights: distilled_with_permission` |

**合规要求**：
- 确认目标 API 服务条款允许输出用于训练
- 所有蒸馏数据标注来源和许可
- 人工审核 ≥10% 随机抽样

验收：蒸馏数据 ≥1000 条，训练后 pass@1 ≥ 55%

### Phase 5 停止条件

- [ ] 至少完成一条路线
- [ ] 新模型通过执行级回归门
- [ ] 训练记录文档化
- [ ] champion.json 更新（人工审核后）

---

## 非目标（V2 明确不做）

1. ❌ 无人监督无限自我训练循环
2. ❌ 自动付费/自动发布/自动变现
3. ❌ 未经许可的 API 蒸馏
4. ❌ 生产环境多用户并发服务
5. ❌ 移动端/小程序部署
6. ❌ 跨语言（非 Python）编码任务
7. ❌ 未实测即声称性能提升

---

## 分支策略

| Phase | 分支名 | 合并条件 |
|-------|--------|----------|
| 0 | `fix/v2-bugs` | 全量测试通过 → 合并 main |
| 1 | `feat/data-v2` | 数据集验证通过 → 合并 main |
| 2 | `feat/training-v2` | 至少 1 次完整闭环运行 → 合并 main |
| 3 | `feat/serving-v1` | API + UI 功能验证 → 合并 main |
| 4 | `feat/automation-v1` | CI + 调度功能验证 → 合并 main |
| 5 | `feat/model-upgrade` | 新冠军通过回归门 → 合并 main |

每个分支独立 PR，人工审核后合并。Agent 不并发修改同一文件。

---

## 资源预算约束

- **GPU 训练**：每次训练 ≤ 2 小时（6GB 卡约束）
- **外部 API**：默认 $0（路线 C 需人工批准预算）
- **存储**：模型权重 + 数据集 ≤ 5GB（本地 E 盘）
- **自动修复**：每个任务最多 3 次
- **自动发布**：永久禁用直到人工开放

---

## 本文档的使用规则

1. 所有 Agent 在开始工作前必须读取本文档
2. Phase 顺序不可跳跃（但 Phase 4 可与 1-3 并行）
3. 每个 Phase 完成后，在本文档对应的停止条件处打勾并附带证据引用
4. 发现本文档的方向需要修正时，提出 PR 修改本文档，不可静默偏离
5. 所有指标必须实测，不可估算或推断
