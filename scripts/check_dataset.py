"""Fail closed on provenance/approval/split issues."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from growthfoundry.dataset import read_approved

p = argparse.ArgumentParser()
p.add_argument('--input', default='data/seed/sft_examples.jsonl')
a = p.parse_args()
try:
    groups = read_approved(a.input)
    print(json.dumps({'status':'PASS','train':len(groups['train']),'eval':len(groups['eval']),'caveat':'Approval flag comes from dataset author; production requires documented human review.'},ensure_ascii=False,indent=2))
except ValueError as e:
    print(f'BLOCKED: {e}', file=sys.stderr)
    raise SystemExit(2)
