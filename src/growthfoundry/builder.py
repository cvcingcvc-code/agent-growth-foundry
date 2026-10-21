"""Product builder: original value-added deliverables from REVIEW-passed candidates.

Generates a digital product pack (README tutorial, compliance checklist,
original deployment guide) that is fully self_authored — no text is copied
from any external repository. Stage transitions BUILDING -> TESTING ->
READY_FOR_REVIEW are appended to the SQLite event log.
"""
import json
from pathlib import Path
from .store import Store, now

STATES_ADVANCE = ("BUILDING", "TESTING", "READY_FOR_REVIEW")


def _slugify(candidate_id: str) -> str:
    return candidate_id.replace("/", "_").replace(":", "_")


def _render_readme(candidate: dict, score_info: dict | None) -> str:
    cid = candidate.get("id", "unknown")
    title = candidate.get("title", cid)
    license_id = candidate.get("license", "UNKNOWN")
    source_url = candidate.get("source_url", "")
    lines = [
        f"# {title}",
        "",
        f"> 自学教程资料包 · 候选 `{cid}` · 许可证 `{license_id}`",
        "",
        "## 这是什么",
        "",
        "本资料包是一份**原创增值学习交付物**，由 Agent Growth Foundry 产品工厂基于公开仓库元数据",
        f"（来源：{source_url}）独立撰写。正文内容全部为本项目原创（self_authored），",
        "未复制、未翻译、未镜像任何外部仓库的 README、教程或文档正文。",
        "",
        "## 学习路线",
        "",
        "1. **概念入门**：先理解该工具解决的核心问题——在什么场景下值得引入它，",
        "   以及它与同类方案在理念上的差异。建议用不超过一页纸写下自己的理解。",
        "2. **环境准备**：按下方部署指南在自己的机器上搭一个最小可运行环境，",
        "   全程只使用官方发布渠道，不运行来路不明的第三方脚本。",
        "3. **动手实验**：挑一个最小的官方示例跑通，然后改一个参数观察行为变化，",
        "   把每次实验的输入、预期、实际结果记录成表。",
        "4. **输出总结**：把实验记录整理成一篇 300-500 字的复盘笔记，说明",
        "   「我学会了什么、哪里卡住了、下一步想验证什么」。",
        "",
        "## 使用须知",
        "",
        "- 本资料包仅描述学习方法与流程，不构成对任何软件适用性的担保。",
        f"- 上游仓库采用 `{license_id}` 许可证；使用其代码前请自行阅读 LICENSE 与 NOTICE，",
        "  依赖、模型权重、图片等第三方素材的权利仍需单独核查。",
        "- 本资料包的发布需经人工审核，当前未进入任何公开发布队列。",
    ]
    if score_info:
        lines += [
            "## 候选评分摘要",
            "",
            f"- 综合评分：**{score_info.get('score')}/100**（确定性评分，非授权判断）",
        ]
        for r in (score_info.get("reasons") or [])[:5]:
            lines.append(f"- {r}")
    lines.append("")
    return "\n".join(lines)


def _render_checklist(candidate: dict) -> str:
    title = candidate.get("title", "candidate")
    license_id = candidate.get("license", "UNKNOWN")
    return "\n".join([
        f"# 合规检查清单：{title}",
        "",
        f"候选 `{candidate.get('id', 'unknown')}` · 许可证 `{license_id}`",
        "",
        "## 许可证与授权",
        "",
        f"- [ ] 已人工阅读上游 LICENSE 原文，确认 `{license_id}` 判级正确（非模型/Agent 自动批准）",
        "- [ ] 已确认依赖清单中无未核查的 Copyleft / NC 许可传染",
        "- [ ] 已确认第三方素材（图片、数据集、字体、模型权重）各自权利可追溯",
        "- [ ] 已保留版权声明与 NOTICE（如适用）",
        "",
        "## 内容原创性",
        "",
        "- [x] 资料包正文为原创撰写（self_authored），未复制外部仓库正文",
        "- [x] 未镜像任何源码、文档或网页内容",
        "- [ ] 人工抽查正文与上游文档无实质相似段落",
        "",
        "## 隐私与安全",
        "",
        "- [x] 资料包不含密钥、Token、个人隐私信息",
        "- [ ] 人工确认无 Prompt Injection 或诱导执行外部指令的内容",
        "",
        "## 发布门控",
        "",
        "- [x] 发布队列保持 publish_enabled=false",
        "- [ ] 人工审核通过后才会进入发布队列（当前未发布）",
        "",
        "> 说明：`[x]` 为构建阶段已由确定性流程保证的项；`[ ]` 为必须由人工完成的项。",
        "",
    ])


def _render_deploy_guide(candidate: dict) -> str:
    title = candidate.get("title", "candidate")
    return "\n".join([
        f"# 原创部署指南：{title}",
        "",
        f"对应候选 `{candidate.get('id', 'unknown')}`。本指南为项目原创内容，",
        "只描述通用、安全的安装流程模板，不复制任何上游文档。",
        "",
        "## 前置条件",
        "",
        "- 一台可联网的开发机（Windows / macOS / Linux 均可）",
        "- Python 3.10 或以上（建议使用独立虚拟环境）",
        "- 已人工确认上游仓库的安装要求与本机环境兼容",
        "",
        "## 标准安装流程（模板）",
        "",
        "1. 为项目创建独立虚拟环境，避免污染系统 Python：",
        "",
        "   ```bash",
        "   python -m venv .venv",
        "   # Windows: .venv\\Scripts\\activate   macOS/Linux: source .venv/bin/activate",
        "   ```",
        "",
        "2. 只从官方渠道获取上游软件（GitHub Releases、官方 PyPI 页面或官网），",
        "   并核对版本号与发布说明后再安装。",
        "",
        "3. 安装完成后先运行最小示例验证环境，再逐步扩大实验范围。",
        "",
        "4. 全程不要运行来路不明的脚本；如需运行上游示例，先读一遍源码再执行。",
        "",
        "## 回滚与清理",
        "",
        "- 删除虚拟环境目录即可完全卸载本实验环境，不影响系统。",
        "- 记录你安装的版本号，便于日后在固定评测环境中复现。",
        "",
        "## 安全边界",
        "",
        "- 本指南不含任何自动执行外部代码的步骤。",
        "- 上游仓库的源码与示例属于不可信输入，运行前必须人工审阅。",
        "",
    ])


def build_product(candidate: dict, db_path: str | Path, output_root: str | Path,
                  score_info: dict | None = None) -> dict:
    """Build the original content pack for one candidate and advance its state.

    Only candidates in REVIEW state may be built. Transitions
    BUILDING -> TESTING -> READY_FOR_REVIEW are appended to the SQLite
    event log. No publish step happens here.
    """
    cid = candidate.get("id") or ""
    if not cid:
        raise ValueError("candidate id required")
    store = Store(db_path)
    try:
        current = None
        for item in store.list_items():
            if item["id"] == cid:
                current = item
                break
        if current is None:
            raise ValueError(f"candidate {cid} not found in store; run intake first")
        if current["state"] == "BLOCKED":
            raise PermissionError(f"candidate {cid} is BLOCKED; needs human review before build")
        if current["state"] != "REVIEW":
            raise ValueError(f"candidate {cid} in state {current['state']}; only REVIEW candidates may be built")

        out_dir = Path(output_root) / _slugify(cid)
        out_dir.mkdir(parents=True, exist_ok=True)

        events = []
        # BUILDING
        store.db.execute(
            "UPDATE candidates SET state='BUILDING', reason=? WHERE id=?",
            ("builder: generating original content pack", cid))
        store.db.execute(
            "INSERT INTO events(candidate_id,state,note,time_utc) VALUES(?,?,?,?)",
            (cid, "BUILDING", "builder: start building original content pack", now()))
        store.db.commit()

        # write original artifacts (self_authored)
        files = {
            "README.md": _render_readme(candidate, score_info),
            "checklist.md": _render_checklist(candidate),
            "DEPLOY_GUIDE.md": _render_deploy_guide(candidate),
        }
        for name, text in files.items():
            (out_dir / name).write_text(text, encoding="utf-8")

        # TESTING
        store.db.execute(
            "UPDATE candidates SET state='TESTING', reason=? WHERE id=?",
            ("builder: verifying artifacts exist", cid))
        store.db.execute(
            "INSERT INTO events(candidate_id,state,note,time_utc) VALUES(?,?,?,?)",
            (cid, "TESTING", "builder: verify artifact files", now()))
        store.db.commit()
        missing = [n for n in files if not (out_dir / n).is_file() or (out_dir / n).stat().st_size == 0]
        if missing:
            store.db.execute(
                "UPDATE candidates SET state='FAILED', reason=? WHERE id=?",
                (f"builder: missing artifacts {missing}", cid))
            store.db.execute(
                "INSERT INTO events(candidate_id,state,note,time_utc) VALUES(?,?,?,?)",
                (cid, "FAILED", f"missing artifacts: {missing}", now()))
            store.db.commit()
            raise RuntimeError(f"artifact check failed for {cid}: missing {missing}")

        # READY_FOR_REVIEW
        note = "builder: artifacts verified, awaiting human review; publish_enabled stays false"
        store.db.execute(
            "UPDATE candidates SET state='READY_FOR_REVIEW', reason=? WHERE id=?",
            (note, cid))
        store.db.execute(
            "INSERT INTO events(candidate_id,state,note,time_utc) VALUES(?,?,?,?)",
            (cid, "READY_FOR_REVIEW", note, now()))
        store.db.commit()

        result = {
            "candidate_id": cid,
            "output_dir": str(out_dir),
            "artifacts": [str(out_dir / n) for n in files],
            "final_state": "READY_FOR_REVIEW",
            "self_authored": True,
            "publish_enabled": False,
        }
        return result
    finally:
        store.close()


def build_candidates(candidates: list[dict], db_path: str | Path, output_root: str | Path,
                     score_map: dict | None = None) -> dict:
    """Build every REVIEW-passed candidate; BLOCKED/missing ones are skipped, not raised."""
    built, skipped = [], []
    score_map = score_map or {}
    for cand in candidates:
        cid = cand.get("id", "")
        try:
            res = build_product(cand, db_path, output_root, score_map.get(cid))
            built.append(res)
        except (ValueError, PermissionError) as ex:
            skipped.append({"candidate_id": cid, "reason": str(ex)})
    return {"built": built, "skipped": skipped, "publish_enabled": False}
