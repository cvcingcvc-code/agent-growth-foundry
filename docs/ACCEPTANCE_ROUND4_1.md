# Round 4.1 验收加固报告 — 安全执行环境 + 执行级晋升门控

- 日期：2026-10-22
- 分支：`feat/local-model-usage-v1`（基于 abfdcaa 增量开发）
- 执行环境：Windows 11 / NVIDIA GTX 1660 Ti 6GB / Python 3.13（smoke venv）+ Python train venv（torch 2.14.1+cu126 / transformers 5.20.2 / peft 0.21.2）
- 结论速览：**冠军仍是 v0**（eval_loss 5.197，`data/champion.json` 未动）；全部停止条件达成；等待人工验收。

## 1. 任务总览（Round 4.1 规范 → 交付对照）

| 任务 | 要求 | 交付状态 |
|---|---|---|
| Task 1 (P0) | 受限运行器，未审查代码默认不执行，未真正隔离不得声明 SANDBOX_SECURE_PASS | 完成（见 §2） |
| Task 2 (P0) | 固定 10 条回归集 + 执行级晋升门控接入成长闭环 | 完成（见 §3/§4） |
| Task 3 (P1) | CLI 超时真实中止 + LoRA 基座兼容检查 + 统一重复检测 + 冠军证据核验防绕过 | 完成（见 §5） |
| Task 4 | 无 GPU 单测不退化 + 真实权重回归 + 防御性验证 | 完成（见 §6/§7） |
| Task 5 | 保护 main、独立分支推送、中文验收报告 | 完成（本报告） |

## 2. Task 1 — 受限运行器（sandbox_runner.py）REAL

新建 `src/growthfoundry/sandbox_runner.py`，三层隔离：

1. **Python import 守卫**（meta_path finder）：模型生成的代码在受限运行时
   禁止导入 socket/ssl/subprocess/ctypes/urllib/http/ftplib/telnetlib/smtplib/asyncio
   等 15 个网络/进程逃逸面模块；同时清理 sys.modules 中已预加载的模块，
   防止 `import x as y` 绕过。守卫在受控 shell 中先于代码执行注册。
2. **Windows Job Object**（ctypes 直调 kernel32）：
   - `JobObjectExtendedLimitInformation` 内存限制（默认 512MB）：实测 300MB
     增量分配在 64MB 限制下 0.8s 内 MemoryError；
   - job user-time 限制：超限终止码 0xC0000044（STATUS_COMMITMENT_LIMIT），
     归类为 `KILLED_BY_LIMIT`（job_object_limit）；
   - `KILL_ON_JOB_CLOSE`：无论正常/超时/异常退出，进程树全部终止。
3. **wall-clock 超时**：外层 subprocess.run 兜底。

诚实分级（写死在 `security_report()`）：
- `verdict = RESTRICTED_RUNNER_PARTIAL_NOT_SECURE`
- `sandbox_secure_pass = False`（永不声明 SANDBOX_SECURE_PASS）
- `FILESYSTEM_NOT_ISOLATED`（文件系统未隔离，如实标注）

执行策略三级（`scripts/coding_pipeline.py --exec-policy`）：
- `blocked`（**默认**）：不执行任何模型生成的代码；
- `reviewed`：经人工标记后走受限运行器；
- `harness`：裸子进程自检路径，仅用于已知内容的流水线自测，绝不用于未审查模型输出。

测试：`tests/test_sandbox_runner.py` 13/13（两轮验证稳定），含内存限制真实生效、
job-time 终止、kill-on-close 进程树清理、blocked 默认不执行。

## 3. Task 2 — 固定回归集（coding_regression_fixed.jsonl）REAL

`data/eval/coding_regression_fixed.jsonl`：10 条固定任务（6 code_gen + 4 debug），
共 48 个断言，覆盖正常/边界/异常场景（空串、负数、相等、1900/400 闰年、
除零、空列表、递归终止等）。该文件是跨版本可比性的锚：
- 每次评估记录 `test_hint_hash = sha256(全部 test_hint)`，晋升门据此校验
  候选与冠军用的是同一套任务与断言；
- 文件变更 → hash 变更 → 条件不一致 → HOLD（防"换题再比"绕过）。

## 4. 执行级晋升门控（exec_gate.py）REAL + 真实运行证据

`src/growthfoundry/exec_gate.py` 四条判定规则（严格、无绕过口）：
1. 候选或冠军任一侧执行证据缺失（未执行/BLOCKED）→ **HOLD**；
2. 基座/test_hint_hash/提示模板/采样模式/max_new_tokens 任一不一致 → **HOLD**；
3. 候选引入新退化（冠军过、候选挂）→ **HOLD**；
4. 候选达标（pass_rate ≥ 0.6 且无新退化）→ **PROMOTE 建议**
   （`pending_human_review=True`，`champion_changed=False`，永不自动晋升）。

真实运行（GPU，真实权重，相同条件，exec-policy=reviewed 受限运行器）：

| 项 | v0（冠军基线） | v3b（候选） |
|---|---|---|
| 通过 | **9/10**（pass_rate 0.9） | **8/10**（0.8） |
| 真实执行 | 10/10 | 10/10 |
| 失败 | coding-eval-006 wrong_result | coding-eval-001 + 006 wrong_result |
| 采样 | greedy / 300 tokens / timeout-gen 120s / timeout-exec 15s | 同左（hash 一致） |
| 用时 | 1m47s | 1m31s |

判定（`outputs/exec_gate_v3b_vs_v0.json`，REAL 证据）：
- **HOLD：新关键逻辑退化 1 项 — coding-eval-001**（is_palindrome 丢 `[::-1]`，
  `s.lower() == s.lower()` 恒真；与 round-4 发现一致，跨轮可复现）
- 数据集 SHA-256 两侧一致（可比性成立）。

v0 基线产物：`outputs/coding_exec_champion_baseline.json`（此后每轮候选都
必须与之同条件对比）。旧 4 任务对比证据 `outputs/execution_comparison_v0_vs_v3b.json`
保留不动，作为 round-4 历史证据。

## 5. Task 3 — CLI 与指标修复 REAL（代码层）+ REAL（GPU 验证）

### 5.1 chat_local.py 超时真实中止
旧实现 daemon 线程超时后推理仍在后台占 GPU。新实现：
- 注册 `DeadlineStoppingCriteria`（StoppingCriteria）到 `model.generate()`，
  生成循环每个 decode step 检查 deadline，到点即停（transformers 5.20.2
  实测签名 `(input_ids, scores, **kwargs) -> BoolTensor`）；
- 线程 join 宽限 15s；宽限期内未停（极老版本 transformers）→ 诚实报告
  "推理可能仍在后台进行"，不假装已中止；
- **GPU 实测**（REAL）：`--timeout-sec 6 --max-new-tokens 8000` 生成 6.1s 被
  criteria 中止，输出"生成超时（>=6s），已通过 stopping-criteria 中止本轮；
  以下为截断的部分回答"，且 `nvidia-smi` 确认无残留 GPU 进程；
  正常路径（32 tokens）不受影响。

### 5.2 LoRA 基座兼容检查
新增 `adapter_base_matches()`：读 `adapter_config.json` 的
`base_model`/`base_model_name_or_path`/`_name_or_path`，与待加载基座精确
比对（反斜杠/尾斜杠归一化）；来源不明默认不兼容。`load_model_and_tokenizer`
在 `PeftModel.from_pretrained` **之前**调用，不兼容 → `SystemExit('BLOCKED: LoRA 基座不兼容 …')`。
- **GPU 实测**（REAL）：真实 v0 config ↔ Qwen3-0.6B 匹配通过（正常加载推理）；
  同一 config ↔ Qwen3-8B 拒绝挂载并给出明确原因。

### 5.3 统一重复检测（code_metrics 为唯一权威实现）
- `code_metrics.has_repetition_loop` 重定义为统一入口：**句子级循环**
  （。！？!?；; 与换行分隔，同句 ≥2 次，最小句长 5）+ **连续重复代码行**
  （≥3 行）双信号，按答案形态自动分流（代码答案只查代码信号 + 围栏外 prose）；
- 删除 2-gram 词频检测（变量名/主题词误报源头）；
- `candidate_audit.has_sentence_loop`/`has_consecutive_dup_lines` 改为从
  code_metrics 导入（消除双实现）；
- `regression.check_repetition` 委托 code_metrics（第四处旧 2-gram 实现一并统一）；
- `coding_pipeline.py`/`eval_coding_exec.py` 已是同一规则（round-4.1 早前统一）。
- 验证（REAL）：sft-020 短语循环（"需手动重置" ×3）恢复检出；主题词
  （"评测集" ×4）不误报；变量名复用不误报；测试全过。

### 5.4 冠军比较证据核验防绕过
`champion_comparison_ready()` 加固（新增两个可选参数，默认收紧）：
- 证据文件必须是合法 JSON 且含非空 `items` 列表——空文件/`{}`/表面-only
  证据不再能通过（旧版只查文件存在）；
- 样本数下限（默认 ≥2，可传 expected_samples）；
- 可传 `expected_dataset_sha256`：冠军证据的 `dataset_fingerprint.sha256`
  必须与候选运行的数据集一致——**不同数据集不能再绕过回归门**。
- 配套：`eval_lora.py` 输出现在带 `dataset_fingerprint`；
  `run_growth_loop.py` Step 4 传入真实数据集 SHA-256。
- 验证（REAL）：4 场景全 HOLD——旧格式证据（无指纹）对不上的哈希、
  无冠军、证据缺失、非证据文件（含 round-4 对比 JSON）全部拒绝。

## 6. Task 4 — 测试与回归验证 REAL

无 GPU 全量单测（12 文件逐个直跑，`E:/AI_Lab/agf-venv` smoke venv）：

| 文件 | 数 | 结果 |
|---|---|---|
| test_core.py | 3 | OK |
| test_factory.py | 11 | OK |
| test_code_metrics.py | 16 | OK |
| test_candidate_audit.py | 22 | OK |
| test_regression.py | 11 | OK |
| test_champion.py | 19 | OK（新增 6 个防绕过用例） |
| test_chat_local.py | 12 | OK（新增 4 个基座匹配用例） |
| test_model_registry.py | 10 | OK |
| test_sandbox_runner.py | 13 | OK（round-4.1 Task 1 新建） |
| test_exec_gate.py | 16 | OK（round-4.1 Task 2 新建） |
| test_coding_pipeline.py | 10 | OK |
| test_coding_pipeline_process.py | 7 | OK（改为 harness 策略 + 新增 blocked 默认用例） |
| **合计** | **150** | **150/150 OK，历史 110 项零退化** |

（round-4 时点 110 → 现 150：新增 40 项全部针对本轮加固面。）

真实权重验证（GPU，REAL）：
- v0 与 v3b 固定回归集同条件对比（§4 表格）；
- 超时真实中止 + 无残留 GPU 进程（§5.1）；
- 基座兼容检查真实拒绝跨基座挂载（§5.2）；
- 旧证据样本过新统一判据：退化模式与 round-4 记录逐条一致
  （sft-017/019/020 deg，sft-018 ok），重复误报 0（§5.3）。

防御行为终验（REAL，纯判定层）：
- 候选 10/10 完美表现 → PROMOTE 但 `pending_human_review=True`、
  `champion_changed=False`（永不自动晋升）；
- 候选 BLOCKED/证据缺失 → HOLD；
- 条件不一致（换基座/换题/换采样/换模板任一）→ HOLD。

## 7. REAL / MOCK / BLOCKED / NOT_TESTED 明细

| 项 | 级别 | 说明 |
|---|---|---|
| sandbox_runner 三层隔离 | REAL | Job Object/内存/job-time/kill-tree 实测生效；文件系统未隔离如实标注 NOT secure |
| 固定 10 条回归集 48 断言 | REAL | 文件入库，hash 锚定 |
| v0 基线 9/10、v3b 8/10 | REAL | 真实 GPU 权重 + 受限运行器真实执行，产物在 outputs/ |
| v3b HOLD（eval-001 新退化） | REAL | exec_gate 判定 + per-task 证据 |
| 超时真实中止 | REAL | GPU 实测 criteria 中止 + 无残留进程 |
| 基座兼容检查 | REAL | 真实 config 匹配/拒绝均实测 |
| 统一重复检测 | REAL | 代码 + 判定行为实测，测试全过 |
| 证据核验防绕过 | REAL | 4 场景 HOLD 实测 |
| run_growth_loop 全链路（训练→评估→执行门） | NOT_TESTED | 本轮未训练新候选（无新训练运行）；编排层 dry-run 数据门 PASS |
| 跨基座挂载的 PeftModel.from_pretrained 实抛 | NOT_TESTED | BLOCKED 在加载前拦截（单测覆盖逻辑层）；未实际让 PEFT 尝试挂载 |
| GraphQL 分页（A-02） | NOT_TESTED | 遗留项，未在本轮范围 |
| 数据扩量 100→300+ | NOT_TESTED | 遗留项，未在本轮范围 |
| MOCK | （无） | 本轮无 mock 冒充真实项 |

## 8. 停止条件核对（规范原文）

1. ✅ 安全执行路径验证通过（reviewed 策略真实执行 20 次：v0 10 + v3b 10；
   blocked 默认不执行；未声明 SANDBOX_SECURE_PASS）；
2. ✅ 真实编码断言进晋升门（48 断言 + 4 条判定规则，test_hint_hash 锚定）；
3. ✅ v0 对比可复现（9/10 vs 8/10，eval-001 新退化与 round-4 一致，证据 JSON 落盘）；
4. ✅ 所有必要测试通过（150/150，历史项零退化）；
5. ✅ 冠军仍是 v0（`data/champion.json` 未动，eval_loss 5.197）。

## 9. 文件清单（本轮改动）

新增：
- `src/growthfoundry/sandbox_runner.py` — 受限运行器
- `src/growthfoundry/exec_gate.py` — 执行级晋升门
- `data/eval/coding_regression_fixed.jsonl` — 固定回归集
- `scripts/eval_coding_exec.py` — 真实执行评估器
- `tests/test_sandbox_runner.py`、`tests/test_exec_gate.py`
- `outputs/coding_exec_champion_baseline.json`（v0 基线证据）
- `outputs/coding_exec_v3b.json`、`outputs/exec_gate_v3b_vs_v0.json`

修改：
- `scripts/chat_local.py` — 超时真实中止 + 基座兼容检查
- `scripts/coding_pipeline.py` — exec-policy 三级
- `scripts/eval_lora.py` — 输出数据集指纹
- `scripts/run_growth_loop.py` — Step 3.5 执行门 + 防绕过核验接入
- `src/growthfoundry/code_metrics.py` — 统一重复判据（权威实现）
- `src/growthfoundry/candidate_audit.py` — 委托统一实现
- `src/growthfoundry/regression.py` — 委托统一实现
- `src/growthfoundry/champion.py` — 证据核验加固
- `tests/test_champion.py`、`tests/test_chat_local.py`、`tests/test_coding_pipeline_process.py`

未动：`data/champion.json`（冠军 v0）、main 分支、模型权重（models/ 已 gitignore）。

## 10. 等待人工验收

- 分支 `feat/local-model-usage-v1`（提交见 git log），验收通过后由人工合并 main；
- 下轮候选训练建议直接用 `scripts/run_growth_loop.py --exec-policy reviewed`
  全链路（本轮 NOT_TESTED 项），冠军基线已就绪；
- 遗留：A-02 GraphQL 分页、数据 100→300+ 扩量、50 条编码任务池扩充。
