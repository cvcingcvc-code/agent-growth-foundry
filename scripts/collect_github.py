"""Explicitly invoked GitHub metadata collection; no infinite unattended loop."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from growthfoundry.config import get_config
from growthfoundry.github_collector import get_repo_metadata, get_repo_metadata_cached

cfg = get_config()

p = argparse.ArgumentParser()
p.add_argument('--repo', action='append', required=True,
               help='owner/repo; may repeat, up to GF_MAX_CANDIDATES_PER_RUN')
p.add_argument('--output', default='data/inbox/github_candidates.jsonl')
p.add_argument('--cache', default=None,
               help='optional path to ETag cache JSON; enables conditional requests')
a = p.parse_args()

repos = list(dict.fromkeys(a.repo))
max_per_run = max(cfg.max_candidates_per_run, 1)  # always allow at least 1
if len(repos) > max_per_run:
    p.error(f'Maximum {max_per_run} repositories per explicit invocation '
            f'(set GF_MAX_CANDIDATES_PER_RUN to change)')

token = cfg.github_token or None
items = []
for repo in repos:
    if a.cache:
        items.append(get_repo_metadata_cached(repo, token, a.cache))
    else:
        items.append(get_repo_metadata(repo, token))

out = Path(a.output)
out.parent.mkdir(parents=True, exist_ok=True)
with out.open('w', encoding='utf-8') as f:
    for item in items:
        f.write(json.dumps(item, ensure_ascii=False) + '\n')
print(json.dumps({
    'collected': len(items), 'output': str(out),
    'cache': a.cache or 'disabled',
    'note': 'Metadata only; LICENSE and dependencies not cleared.',
}, ensure_ascii=False))
