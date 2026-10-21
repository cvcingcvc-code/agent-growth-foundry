"""Explicitly invoked GitHub metadata collection; no infinite unattended loop."""
import argparse
import json
import os
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from growthfoundry.github_collector import get_repo_metadata
p=argparse.ArgumentParser()
p.add_argument('--repo', action='append', required=True, help='owner/repo; may repeat, up to 10')
p.add_argument('--output', default='data/inbox/github_candidates.jsonl')
a=p.parse_args()
repos=list(dict.fromkeys(a.repo))
if len(repos)>10: p.error('Maximum 10 repositories per explicit invocation')
items=[]
for repo in repos:
    items.append(get_repo_metadata(repo, os.environ.get('GITHUB_TOKEN') or None))
out=Path(a.output)
out.parent.mkdir(parents=True,exist_ok=True)
with out.open('w',encoding='utf-8') as f:
    for item in items: f.write(json.dumps(item,ensure_ascii=False)+'\n')
print(json.dumps({'collected':len(items),'output':str(out),'note':'Metadata only; LICENSE and dependencies not cleared.'},ensure_ascii=False))
