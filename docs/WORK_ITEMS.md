# GitHub Issues 初始化待办

- [ ] A-01：连接现有 GitHub 资料采集项目的实际数据源，先确认路径/存储格式，禁止清库重爬。
- [x] A-02：支持 GitHub GraphQL/REST API 增量发现与分页、限速、缓存、网络错误重试；安全采集只保存必要元数据。（REST 部分已实现：ETag/If-None-Match 缓存 + 429/5xx 有界退避重试（最多 3 次），CLI `--cache`；见 src/growthfoundry/github_collector.py，真实运行证据见 docs/PRODUCT_FACTORY_STATUS.md。GraphQL/分页未实现，该项保持开放）
- [ ] A-03：许可证复核、第三方资源许可、归属记录、产品质量判定。（部分进展：确定性候选评分 src/growthfoundry/score.py 已实现；许可证复核仍为规则门控，需人工）
- [x] A-04：交付物 Build + QA + 人工发布队列，至少 1 个真实产品闭环。（builder 已实现；1 个真实闭环已跑通，状态推进 BUILDING→TESTING→READY_FOR_REVIEW；发布队列保持 publish_enabled=false，发布仍需人工审核；见 docs/PRODUCT_FACTORY_STATUS.md）
- [x] B-01：CPU 模型训练 Smoke checkpoint / reload / eval；观察真实报告。（2026-10-21 真实执行：8 epochs，loss 1.159→1.102，acc 2/9→3/9，checkpoint reload PASS；见 docs/SESSION_STATUS_2026-10-21.md）
- [x] B-02：Windows GPU 上跑 Qwen3-0.6B 第一轮 LoRA；记录硬件、版本、损失、对照测试。（2026-10-21 真实完成：GTX 1660 Ti，v0 train_loss 5.438/eval_loss 5.197，adapter 本地保存；见 docs/TRAINING_RECORD_2026-10-21.md）
- [ ] B-03：收集 >100 条高质量自有/获授权、可审核的训练数据；清洗、去重、按主题拆分训练与评测。（部分进展：v1 数据集 32 train + 4 eval self_authored 已入库并训练；第二轮发现 sft-019/020 退化样本，v1 未通过晋升；见 docs/TRAINING_RECORD_ROUND2_2026-10-21.md）
- [x] B-04：建立基础模型和适配器的盲测基线，并对错误样本进行复盘。（2026-10-21 完成：eval_lora.py 基座/v0/v1/v2 对比 + regression.py 自动退化检测（重复循环/低重叠）+ round-2/3 失败样本复盘；见 docs/TRAINING_RECORD_ROUND2/ROUND3）
- [ ] SEC-01：使用隔离执行、安全限额、敏感信息过滤、Prompt Injection 防御、审计日志。
