# 产品工厂轨道状态（Track A: Product Factory）

记录真实运行证据。**严格区分 REAL / SMOKE / MOCK：未经实测不写 PASS。**

## 模块清单（feat/product-factory-v1 分支）

| 模块 | 文件 | 状态 | 验证方式 |
|---|---|---|---|
| 增量采集（ETag 缓存 + 有界退避） | src/growthfoundry/github_collector.py | REAL（2026-10-21 真实调用 api.github.com 验证） | scripts/collect_github.py --cache 真实采集 3 仓库成功 |
| 候选评分（0-100 确定性） | src/growthfoundry/score.py | REAL（纯函数，单测 + 真实数据打分） | tests/test_factory.py 6 项评分测试 + 真实候选排序 |
| 产品构建器（原创资料包） | src/growthfoundry/builder.py, scripts/build_product.py | REAL（真实候选构建产物落盘） | 产物文件存在且非空；SQLite 事件日志含状态推进 |
| 单元测试 | tests/test_factory.py | REAL | python -m unittest discover -s tests -v：16/16 OK |
| 发布队列 | — | 未实现（保持 publish_enabled=false） | 代码中所有输出均 publish_enabled=false |

## 真实闭环运行记录（run_id: 2026-10-21-product-factory-001）

- **日期**：2026-10-21
- **agent**：builder（builder+qa 角色）
- **状态**：REAL_PASS

### 步骤与证据

1. **真实采集（REAL）**：
   - 命令：`python scripts/collect_github.py --repo QwenLM/Qwen3 --repo huggingface/peft --repo modelcontextprotocol/servers --output data/inbox/github_candidates_real.jsonl --cache data/cache/github_etag.json`
   - 结果：3/3 采集成功，仅保存公开元数据（stars/pushed_at/fork/archived/license SPDX），未下载源码或正文。
   - 证据：data/inbox/github_candidates_real.jsonl、data/cache/github_etag.json

2. **入库门控（REAL）**：
   - 命令：`python scripts/run_demo.py --input data/inbox/github_candidates_real.jsonl --db data/state.db --report data/reports/intake_real.json`
   - 结果：3 个候选 → 1 BLOCKED（gh:QwenLM/Qwen3，license UNKNOWN）/ 2 REVIEW（gh:huggingface/peft Apache-2.0；gh:modelcontextprotocol/servers NOASSERTION 未清权）。
   - 证据：data/reports/intake_real.json

3. **评分排序（REAL）**：
   - gh:huggingface/peft：**67/100**（stars 21817→+17.5，pushed 0d active→+25，Apache-2.0→+25）
   - gh:modelcontextprotocol/servers：**65/100**（stars 91441→+40，pushed 2d active→+25，NOASSERTION→+0）
   - gh:QwenLM/Qwen3：**42/100**（stars 27678→+22.1，pushed 285d decaying→+20.2，UNKNOWN→+0）
   - 证据：data/reports/ranking_real.json

4. **构建产物（REAL）**：
   - 命令：`python scripts/build_product.py --input data/inbox/github_candidates_real.jsonl --db data/state.db --output-root outputs/product_packs --report data/reports/product_build_real.json`
   - gh:QwenLM/Qwen3 被正确拒绝（BLOCKED，需人工审核）。
   - 2 个 REVIEW 候选生成原创资料包（self_authored，正文全部由 agent 原创撰写，未复制任何外部仓库正文）：
     - outputs/product_packs/gh_huggingface_peft/{README.md, checklist.md, DEPLOY_GUIDE.md}
     - outputs/product_packs/gh_modelcontextprotocol_servers/{README.md, checklist.md, DEPLOY_GUIDE.md}
   - 状态推进 BUILDING→TESTING→READY_FOR_REVIEW 已写入 SQLite 事件日志（data/state.db，events 表逐条验证）。
   - 证据：data/reports/product_build_real.json

5. **经验记录（REAL）**：
   - data/experience.jsonl 追加 2 条（task_id: A-04-product-loop-001、A-02-collector-cache-001），approved_for_learning=true，training_eligible=false（由 experience.py 强制）。

6. **运行报告**：data/reports/product_factory_run.json（status=REAL_PASS，含 run_id/agent/inputs/artifacts/evidence/limitations，符合 docs/INTERFACES.md 最低字段）。

### 测试结果（REAL）

- 命令：`python -m unittest discover -s tests -v`（venv: E:\AI_Lab\agf-venv）
- 结果：**16/16 OK**（test_core.py 5 项 + test_factory.py 11 项）
- test_factory.py 覆盖：评分边界（0-100 不越界）、license 等级影响、近期 push 优于过期、archived/fork 惩罚、排序稳定性、确定性；构建产物存在且非空、状态推进序列 REVIEW→BUILDING→TESTING→READY_FOR_REVIEW、BLOCKED 拒绝（PermissionError）、未知候选拒绝（ValueError）、publish_enabled=false。
- 历史验证（2026-10-21 早期）：train_smoke 8 epochs PASS（SMOKE，训练轨，本轨道未改动）。

## 边界与限制（如实声明）

- 采集仅保存公开元数据，不下载源码正文，不镜像内容（collection_scope=metadata_only）。
- 许可证门控是确定性规则，不是法律判断；BLOCKED/REVIEW 均需人工复核。
- 构建产物 QA 仅做文件存在性与非空校验；内容人工审核仍待完成。
- 发布队列未实现且 publish_enabled=false；无任何自动发布/合并到 main。
- GraphQL 增量发现与分页未实现（WORK_ITEMS A-02 保持开放）。
- 本轨道未修改 train_lora.py / train_smoke.py 等训练轨文件。

## Commit 记录

| SHA | 说明 |
|---|---|
| 440df80 | feat(collector): ETag 缓存 + 有界退避重试 |
| 30162f8 | feat(score): 确定性候选评分 |
| 5294a0e | feat(builder): 原创资料包构建器 + CLI |
| aa6122a | test(factory): score/builder 单元测试 |
| （本次提交） | docs: WORK_ITEMS 勾选 + PRODUCT_FACTORY_STATUS |
