# GitHub Issues 待办清单

## V1 遗留项

- [ ] A-01：连接现有 GitHub 资料采集项目的实际数据源，先确认路径/存储格式，禁止清库重爬。
- [x] A-02：支持 GitHub GraphQL/REST API 增量发现与分页、限速、缓存、网络错误重试；安全采集只保存必要元数据。（REST 部分已实现：ETag/If-None-Match 缓存 + 429/5xx 有界退避重试（最多 3 次），CLI `--cache`；见 src/growthfoundry/github_collector.py，真实运行证据见 docs/PRODUCT_FACTORY_STATUS.md。GraphQL/分页未实现，该项保持开放）
- [ ] A-03：许可证复核、第三方资源许可、归属记录、产品质量判定。（部分进展：确定性候选评分 src/growthfoundry/score.py 已实现；许可证复核仍为规则门控，需人工）
- [x] A-04：交付物 Build + QA + 人工发布队列，至少 1 个真实产品闭环。（builder 已实现；1 个真实闭环已跑通，状态推进 BUILDING→TESTING→READY_FOR_REVIEW；发布队列保持 publish_enabled=false，发布仍需人工审核；见 docs/PRODUCT_FACTORY_STATUS.md）
- [x] B-01：CPU 模型训练 Smoke checkpoint / reload / eval；观察真实报告。（2026-10-21 真实执行：8 epochs，loss 1.159→1.102，acc 2/9→3/9，checkpoint reload PASS；见 docs/SESSION_STATUS_2026-10-21.md）
- [x] B-02：Windows GPU 上跑 Qwen3-0.6B 第一轮 LoRA；记录硬件、版本、损失、对照测试。（2026-10-21 真实完成：GTX 1660 Ti，v0 train_loss 5.438/eval_loss 5.197，adapter 本地保存；见 docs/TRAINING_RECORD_2026-10-21.md）
- [ ] B-03：收集 >100 条高质量自有/获授权、可审核的训练数据；清洗、去重、按主题拆分训练与评测。（部分进展：v1 数据集 32 train + 4 eval self_authored 已入库并训练；第二轮发现 sft-019/020 退化样本，v1 未通过晋升；见 docs/TRAINING_RECORD_ROUND2_2026-10-21.md）
- [x] B-04：建立基础模型和适配器的盲测基线，并对错误样本进行复盘。（2026-10-21 完成：eval_lora.py 基座/v0/v1/v2 对比 + regression.py 自动退化检测（重复循环/低重叠）+ round-2/3 失败样本复盘；见 docs/TRAINING_RECORD_ROUND2/ROUND3）
- [ ] SEC-01：使用隔离执行、安全限额、敏感信息过滤、Prompt Injection 防御、审计日志。（部分进展：sandbox_runner.py 实现三层受限隔离，exec_gate.py 实现执行级门控；文件系统隔离和 Prompt Injection 防御仍未完成）

---

## V2 开发清单（按 docs/DEVELOPMENT_PLAN_V2.md 冻结方向）

### Phase 0：Bug 修复（P0 阻塞项）

- [x] V2-0-1：修复 run_growth_loop.py 门控仲裁覆盖逻辑（exec PROMOTE 不应覆盖 regression HOLD；已修复）
- [x] V2-0-2：修复 store.py `INSERT OR IGNORE` 状态更新缺陷，增加 `advance_state()` 方法（builder.py 同步调用；test_core.py 增加单测覆盖）
- [x] V2-0-3：修复 test_core.py 导入路径问题（非根目录 pytest 可运行；已修复）
- [x] V2-0-4：修复 coding_regression_fixed.jsonl 第 4/7 题 `/n` 笔误 + generate_coding_candidates.py ce-020-a 题目答案不匹配（已修复并重新审核）

### Phase 1：数据基础建设（P0 最高优先级）

- [ ] V2-1-1：新建 scripts/generate_coding_v2.py 参数化模板生成器（≥500 条编码任务）
- [ ] V2-1-2：新建 scripts/verify_candidates_exec.py 执行验证过滤器（≥400 条通过验证）
- [ ] V2-1-3：新建 scripts/generate_multiturn.py 多轮对话样本构造器（≥200 条）
- [ ] V2-1-4：扩充固定回归集到 40 题 ≥200 断言 + 新建 coding_eval_v2.jsonl 50 题
- [ ] V2-1-5：合并输出 sft_examples_v4.jsonl（≥620 train + ≥50 eval）

### Phase 2：训练与评估升级

- [ ] V2-2-1：train_lora.py 增加 lr-search / rank / alpha / early-stop / curriculum / 训练曲线
- [ ] V2-2-2：新建 scripts/eval_comprehensive.py 综合评估（pass@1 / pass@5 / 执行通过率）
- [ ] V2-2-3：run_growth_loop.py 接入新回归集 + 综合评估门控
- [ ] V2-2-4：首次冠军换代尝试（v4 训练 → 全链路评估 → PROMOTE 或 HOLD 记录）

### Phase 3：服务化

- [ ] V2-3-1：新建 src/growthfoundry/server/ FastAPI 推理服务（OpenAI 兼容）
- [ ] V2-3-2：chat_local.py 多轮对话支持（保留 5 轮历史）
- [ ] V2-3-3：新建 scripts/web_ui.py Gradio Web 界面

### Phase 4：自动化与 CI/CD

- [ ] V2-4-1：新建 .github/workflows/test.yml 自动测试流水线
- [ ] V2-4-2：新建 src/growthfoundry/experience_store.py 经验检索模块（替代 experience.py stub）
- [ ] V2-4-3：新建 scripts/schedule_loop.py 本地调度脚本

### Phase 5：模型能力跃升（视硬件条件选择路线）

- [ ] V2-5-A：路线 A — 0.6B 极限挖掘（rank 32 + DPO + 2000+ 数据）
- [ ] V2-5-B：路线 B — 升级 Qwen3-1.7B（需 12GB 显卡或云端 GPU）
- [ ] V2-5-C：路线 C — API 蒸馏（需外部 API 预算授权）
