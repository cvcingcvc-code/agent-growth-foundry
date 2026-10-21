"""Conservative metadata-only GitHub REST collector.

No arbitrary repository code execution and no content mirroring.
External API calls only after explicit local invocation.
"""
import json
import os
import re
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

REPO_RE = re.compile(r'^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$')


def get_repo_metadata(slug: str, token: str | None = None) -> dict:
    if not REPO_RE.fullmatch(slug):
        raise ValueError('Expected owner/repo GitHub identifier')
    headers = {'User-Agent':'agent-growth-foundry/0.1', 'Accept':'application/vnd.github+json',
               'X-GitHub-Api-Version':'2022-11-28'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    req = Request(f'https://api.github.com/repos/{slug}', headers=headers)
    try:
        with urlopen(req, timeout=12) as res:
            obj = json.load(res)
    except HTTPError as ex:
        raise RuntimeError(f'GitHub API HTTP {ex.code}; obey limits, do not retry indefinitely') from ex
    except URLError as ex:
        raise RuntimeError(f'GitHub API not reachable: {ex.reason}') from ex
    if obj.get('full_name') != slug:
        raise ValueError('Repository identity mismatch; check moved/renamed repositories manually')
    license_obj = obj.get('license') or {}
    spdx = license_obj.get('spdx_id') or 'UNKNOWN'
    return {'id':f'gh:{slug}', 'title':obj.get('description') or slug,
            'license':spdx, 'source_url':obj['html_url'], 'assets_checked':False,
            'metadata':{'stars':obj.get('stargazers_count'), 'updated_at':obj.get('updated_at'),
                        'pushed_at':obj.get('pushed_at'), 'fork':obj.get('fork'), 'archived':obj.get('archived')},
            'collection_scope':'metadata_only'}
