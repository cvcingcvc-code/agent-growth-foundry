"""Offline smoke run using explicitly fake candidate inputs."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from growthfoundry.pipeline import run_candidates

p = argparse.ArgumentParser()
p.add_argument("--input", default="data/seed/candidates.jsonl")
p.add_argument("--db", default="data/state.db")
p.add_argument("--report", default="data/reports/intake.json")
a = p.parse_args()
print(json.dumps(run_candidates(Path(a.input), Path(a.db), Path(a.report)), ensure_ascii=False, indent=2))
