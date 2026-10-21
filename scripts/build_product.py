"""Build original product packs for REVIEW-passed candidates from an intake JSONL."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from growthfoundry.builder import build_candidates
from growthfoundry.score import score_candidate

p = argparse.ArgumentParser()
p.add_argument("--input", default="data/inbox/github_candidates.jsonl", help="intake candidates JSONL")
p.add_argument("--db", default="data/state.db")
p.add_argument("--output-root", default="outputs/product_packs")
p.add_argument("--report", default="data/reports/product_build.json")
a = p.parse_args()

candidates = []
for n, line in enumerate(Path(a.input).read_text(encoding="utf-8").splitlines(), 1):
    if not line.strip():
        continue
    item = json.loads(line)
    score_info = score_candidate(item)
    score_map = {item["id"]: score_info}
    candidates.append((item, score_map))

results = []
for item, score_map in candidates:
    outcome = build_candidates([item], Path(a.db), Path(a.output_root), score_map)
    if outcome["built"]:
        res = outcome["built"][0]
        res["score"] = score_map[item["id"]]["score"]
        results.append(res)
    for skipped in outcome["skipped"]:
        results.append(skipped)

report = {"count": len(results), "items": results, "publish_enabled": False,
          "self_authored": True}
out = Path(a.report)
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(report, ensure_ascii=False, indent=2))
