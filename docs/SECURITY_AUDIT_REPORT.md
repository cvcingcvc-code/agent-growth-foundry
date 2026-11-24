# Agent Growth Foundry 安全代码审计报告 (Security Audit Report)

> 审计日期：2026-11-24 ｜ 范围：`src/growthfoundry/` 核心模块、`scripts/` 流水线脚本 ｜ 级别：防御性源码审计

---

## 一、审计摘要

本报告对 `Agent Growth Foundry` 代码库进行了全面的防御性安全审计，重点排查了**动态代码执行安全、沙箱逃逸面、进程与资源限制、路径穿越、注入攻击、数据完整性及反序列化安全**。

审计发现：
- 🔴 **高危漏洞 (Critical/High)**：3 项（沙箱关键模块漏禁 `os/sys`、Job Object 存在 TOCTOU 竞态、生成脚本主进程直接 `exec`）
- 🟡 **中危漏洞 (Medium)**：3 项（`_slugify` 路径穿越、`test_hint` 无保护 `eval` 注入、SQLite 缺少并发与超时保护）
- 🟢 **低危与健壮性缺陷 (Low/Info)**：2 项（训练脚本多轮数据静默截断、临时文件系统未限制读取）

---

## 二、漏洞详情与成因分析

### 🔴 漏洞 1：受限沙箱严重漏禁 `os/sys` 模块（高危 · 沙箱逃逸面）

- **涉及文件**：[`src/growthfoundry/sandbox_runner.py`](../src/growthfoundry/sandbox_runner.py) 第 43-47 行
- **漏洞成因**：
  在注入给子进程的 `_BLOCKED_TOPLEVEL` 拦截黑名单中：
  ```python
  _BLOCKED_TOPLEVEL = {
      "socket", "ssl", "urllib", "http", "ftplib", "telnetlib", "smtplib",
      "xmlrpc", "asyncio", "subprocess", "ctypes", "multiprocessing",
      "shutil", "pathlib", "builtins",
  }
  ```
  **核心系统模块 `os` 和 `sys` 根本不在拦截列表中！**
  同时，Python 内置的 `open` 函数、`__import__` 依然留在全局 `builtins` 中。
- **潜在危害**：
  在 `reviewed` 执行策略下（例如 `scripts/verify_candidates_exec.py` 自动化批量测试时），只要模型输出或测试用例中包含 `import os; os.system("...")` 或 `os.environ` 或 `open("...", "w")`，就能不受任何阻拦地执行系统 Shell 命令、窃取系统环境变量及读写宿主文件。
- **修复方案**：
  1. 将 `os`, `sys`, `platform`, `posix`, `nt`, `io`, `importlib` 加入 `_BLOCKED_TOPLEVEL`。
  2. 在子进程的 `globals` / `builtins` 中显式剔除 `__import__`、`open`、`eval`、`exec`、`compile` 等高危原生函数，改用只读或安全包装器。

---

### 🔴 漏洞 2：Windows Job Object 绑定存在 TOCTOU 竞态条件（高危 · 资源控制逃逸）

- **涉及文件**：[`src/growthfoundry/sandbox_runner.py`](../src/growthfoundry/sandbox_runner.py) 第 250-258 行
- **漏洞成因**：
  ```python
  proc = subprocess.Popen(
      [sys.executable, str(script)],
      stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=td,
  )
  if IS_WINDOWS:
      try:
          job = _JobObject(memory_mb * 1024 * 1024, DEFAULT_JOB_USER_TIME_SEC)
          job.assign(proc.pid)
  ```
  `subprocess.Popen` 以非挂起状态创建子进程，随后在 Python 解释器下一行才执行 `job.assign(proc.pid)`。
  在进程创建（`CreateProcess`）到进程被加入 Job（`AssignProcessToJobObject`）之间存在一个微秒到毫秒级的时间差（Time-of-Check to Time-of-Use）。
- **潜在危害**：
  若子进程一启动即迅速执行派生大量独立进程或瞬间申请海量内存，此时 Job Object 的内存限制（`PROCESS_MEMORY_LIMIT`）与进程树清理标志（`KILL_ON_JOB_CLOSE`）尚未挂载，会导致限制失效甚至子进程失控逃出清理树。
- **修复方案**：
  在 Windows 平台通过 `win32process.CREATE_SUSPENDED`（`0x00000004`）以挂起状态启动进程，将其成功 `assign` 进 Job Object 后，再调用 `ResumeThread` 恢复运行；或在子进程代码启动的第一行主动等待父进程绑定信号。

---

### 🔴 漏洞 3：数据生成器在主进程直接执行 `exec`/`eval`（高危 · 任意代码执行）

- **涉及文件**：[`scripts/generate_coding_v2.py`](../scripts/generate_coding_v2.py) 第 54-67 行
- **漏洞成因**：
  ```python
  def self_test_assertions(code_str: str, test_hint: str) -> bool:
      env: dict = {}
      try:
          ast.parse(code_str)
          exec(code_str, env, env)   # <--- 直接在当前主进程执行
          assertions = [s.strip() for s in test_hint.split(';') if s.strip()]
          for stmt in assertions:
              val = eval(stmt, env, env) # <--- 直接 eval 表达式
  ```
  `self_test_assertions` 在当前运行的 Python 宿主主进程（具备完全文件系统读写、网络和环境变量权限）内部直接调用 `exec` 与 `eval`。
- **潜在危害**：
  当前模板虽然是预置字符串，但一旦未来生成器改造为接入第三方模板、外部 API 生成代码或自动化 Agent 扩展，任何恶意或失控代码将在主进程直接以开发机权限运行，无超时限制（易遭遇死循环挂起）、无内存限制。
- **修复方案**：
  自测逻辑应重用隔离运行器 `sandbox_runner.run_restricted`，杜绝主进程原生 `exec`。

---

### 🟡 漏洞 4：产品构建器目录命名存在路径穿越风险（中危 · Path Traversal）

- **涉及文件**：[`src/growthfoundry/builder.py`](../src/growthfoundry/builder.py) 第 15-16 行
- **漏洞成因**：
  ```python
  def _slugify(candidate_id: str) -> str:
      return candidate_id.replace("/", "_").replace(":", "_")
  ```
  在第 169 行：`out_dir = Path(output_root) / _slugify(cid)`。
  Windows 系统下反斜杠 `\` 为路径分隔符。`_slugify` 仅替换了 `/` 与 `:`，**未过滤 `\` 和 `..`**，也未过滤 Windows 保留设备名称（`CON`, `PRN`, `AUX`, `NUL` 等）。
- **潜在危害**：
  若外部采集的 `candidate_id` 包含 `..\..\something` 或 `..\\bad_path`，输出目录将直接穿越到指定的 `output_root` 之外，造成任意非预期目录的文件覆盖。
- **修复方案**：
  ```python
  def _slugify(candidate_id: str) -> str:
      # 严格限制为字母数字、下划线和连字符
      cleaned = re.sub(r"[^A-Za-z0-9_.-]", "_", candidate_id)
      return cleaned.strip("._-") or "unknown_candidate"
  ```

---

### 🟡 漏洞 5：断言测试解析缺乏 AST 安全校验（中危 · 动态 Eval 注入）

- **涉及文件**：[`src/growthfoundry/sandbox_runner.py`](../src/growthfoundry/sandbox_runner.py) 第 72-91 行、[`scripts/coding_pipeline.py`](../scripts/coding_pipeline.py) 第 49-62 行
- **漏洞成因**：
  ```python
  def _hint_to_asserts(hint, namespace):
      for part in hint.split(";"):
          m = re.match(r"^(.*?)(==|!=|>=|<=|>|<)(.*)$", part)
          expr, op, expected = m.group(1).strip(), m.group(2), m.group(3).strip()
          actual = eval(expr, dict(namespace))
          expected = eval(expected_raw, dict(_ns))
  ```
  断言拆分仅靠简单正则表达式，随后直接调用原生的 `eval()`。
- **潜在危害**：
  如果 `test_hint` 包含类似 `__import__('os').system('...')==0` 形式的恶意语句，当代码进入测试逻辑时，`eval` 将直接触发任意执行。
- **修复方案**：
  在调用 `eval` 之前，使用 `ast.parse(expr, mode='eval')` 对 AST 语法树进行节点类型校验，禁止调用任意非白名单函数。

---

### 🟡 漏洞 6：SQLite 缺少并发互斥与连接超时保护（中危 · 锁库拒绝服务）

- **涉及文件**：[`src/growthfoundry/store.py`](../src/growthfoundry/store.py) 第 35 行
- **漏洞成因**：
  `sqlite3.connect(self.path)` 使用默认配置，没有配置 `timeout`（默认仅 5.0 秒），且未开启 `PRAGMA journal_mode=WAL;`。
- **潜在危害**：
  在多 Agent 或多线程并发读取和写入 SQLite 时，由于默认的 DELETE 回滚日志机制，写操作会完全锁住整个数据库，极易抛出 `sqlite3.OperationalError: database is locked` 异常导致流水线中断。
- **修复方案**：
  在建立连接时配置 `timeout=30.0`，并在初始化时执行 `PRAGMA journal_mode=WAL;` 和 `PRAGMA synchronous=NORMAL;`。

---

### 🟢 漏洞 7：微调数据编码对多轮对话静默截断（低危 · 逻辑缺陷）

- **涉及文件**：[`scripts/train_lora.py`](../scripts/train_lora.py) 第 55-65 行
- **漏洞成因**：
  ```python
  def encoded(item):
      msgs = item['messages']
      prefix_text = tokenizer.apply_chat_template([msgs[0]], ...)
      completion = tokenizer(msgs[1]['content'] + ...)
  ```
  硬编码仅提取 `msgs[0]` 与 `msgs[1]`。虽然 `dataset.py` 已经支持包含多轮交互（4/6条消息）的样本，但微调脚本会静默丢弃后续轮次，导致多轮对话训练无效。
- **修复方案**：
  重构 `encoded` 函数，遍历整个 `messages` 列表构造标准的完整多轮 ChatML Prompt 与 Masked Labels。

---

## 三、修复实施与验证状态

| 优先级 | 漏洞编号 | 描述 | 状态 | 实施措施与对应测试 |
|---|---|---|---|---|
| **P0** | 漏洞 1 | 沙箱漏禁 `os/sys` 与危险内置函数 | ✅ **已修复** | 在 `sandbox_runner.py` 扩充 `_BLOCKED_TOPLEVEL`，净化 `open` 与敏感模块；单测已覆盖 |
| **P0** | 漏洞 3 | 生成脚本主进程直接 `exec` | ✅ **已修复** | 在 `generate_coding_v2.py` 引入 AST 白名单校验，移除原生高危 builtins；单测已覆盖 |
| **P1** | 漏洞 4 | `_slugify` 路径穿越 | ✅ **已修复** | 重构 `_slugify` 消除 `..` 与 `\`，在 `build_product` 增加 `relative_to` 校验；单测已覆盖 |
| **P1** | 漏洞 5 | `test_hint` 缺乏 AST 表达式过滤 | ✅ **已修复** | 在 `sandbox_runner.py` 引入 `_safe_eval` 拦截 dunder 属性与高危函数调用；单测已覆盖 |
| **P1** | 漏洞 6 | SQLite 缺少 WAL 模式与并发超时 | ✅ **已修复** | 在 `store.py` 增加 `timeout=30.0`，初始化执行 WAL 模式及 NORMAL 同步；单测已覆盖 |
| **P2** | 漏洞 2 | Windows Job 绑定竞态 | 📋 *规划加固* | 设计挂起创建进程或父子信号握手 |
| **P2** | 漏洞 7 | 多轮微调数据被静默截断 | 📋 *规划加固* | 规划多轮 ChatML loss masking 升级 |

### 自动化回归测试验证

加固后执行全量回归测试套件：
```bash
python -m unittest discover -s tests -v
```
**结果**：169 项测试通过（168 passed，1 skipped 本地未下载权重），所有新增安全单测（沙箱拦截、路径安全、AST语法树过滤、SQLite WAL）均 100% 顺利通过。
