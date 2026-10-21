"""Conservative metadata-only GitHub REST collector.

No arbitrary repository code execution and no content mirroring.
External API calls only after explicit local invocation.
"""
import json
import os
import re
import time
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

REPO_RE = re.compile(r'^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$')
MAX_RETRIES = 3  # hard cap; never loop indefinitely


def _headers(token: str | None = None, etag: str | None = None) -> dict:
    headers = {'User-Agent':'agent-growth-foundry/0.1', 'Accept':'application/vnd.github+json',
               'X-GitHub-Api-Version':'2022-11-28'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    if etag:
        headers['If-None-Match'] = etag
    return headers


def _parse(obj: dict, slug: str) -> dict:
    if obj.get('full_name') != slug:
        raise ValueError('Repository identity mismatch; check moved/renamed repositories manually')
    license_obj = obj.get('license') or {}
    spdx = license_obj.get('spdx_id') or 'UNKNOWN'
    return {'id':f'gh:{slug}', 'title':obj.get('description') or slug,
            'license':spdx, 'source_url':obj['html_url'], 'assets_checked':False,
            'metadata':{'stars':obj.get('stargazers_count'), 'updated_at':obj.get('updated_at'),
                        'pushed_at':obj.get('pushed_at'), 'fork':obj.get('fork'), 'archived':obj.get('archived')},
            'collection_scope':'metadata_only'}


def _load_cache(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding='utf-8'))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_cache(path: Path, cache: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding='utf-8')


def get_repo_metadata_cached(slug: str, token: str | None = None,
                             cache_path: str | Path | None = None,
                             retries: int = MAX_RETRIES) -> dict:
    """Metadata-only fetch with ETag/If-None-Match conditional requests and
    bounded backoff on HTTP 429 / 5xx. Cache stores {slug: {etag, item}}.

    Metadata-only boundary unchanged: no source code or content is downloaded.
    """
    if not REPO_RE.fullmatch(slug):
        raise ValueError('Expected owner/repo GitHub identifier')
    if retries < 0 or retries > MAX_RETRIES:
        raise ValueError(f'retries must be within 0..{MAX_RETRIES}')
    backoff = 2.0
    etag = None
    cached = None
    if cache_path is not None:
        cached = _load_cache(Path(cache_path)).get(slug)
        if cached:
            etag = cached.get('etag')
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        req = Request(f'https://api.github.com/repos/{slug}',
                      headers=_headers(token, etag))
        try:
            with urlopen(req, timeout=12) as res:
                if res.status == 304 and cached:
                    return dict(cached['item'])
                obj = json.load(res)
                item = _parse(obj, slug)
                if cache_path is not None and res.headers.get('ETag'):
                    cache = _load_cache(Path(cache_path))
                    cache[slug] = {'etag':res.headers['ETag'], 'item':item}
                    _save_cache(Path(cache_path), cache)
                return item
        except HTTPError as ex:
            if ex.code == 304 and cached:
                return dict(cached['item'])
            # 429 rate limit or transient 5xx: bounded backoff then retry
            if ex.code == 429 or ex.code >= 500:
                last_error = RuntimeError(f'GitHub API HTTP {ex.code}; retry {attempt+1}/{retries}')
                if attempt < retries:
                    time.sleep(backoff)
                    backoff = min(backoff * 2, 8.0)
                    continue
            raise RuntimeError(f'GitHub API HTTP {ex.code}; obey limits, do not retry indefinitely') from ex
        except URLError as ex:
            raise RuntimeError(f'GitHub API not reachable: {ex.reason}') from ex
    raise RuntimeError(f'GitHub API retries exhausted: {last_error}')


def get_repo_metadata(slug: str, token: str | None = None) -> dict:
    if not REPO_RE.fullmatch(slug):
        raise ValueError('Expected owner/repo GitHub identifier')
    headers = _headers(token)
    req = Request(f'https://api.github.com/repos/{slug}', headers=headers)
    try:
        with urlopen(req, timeout=12) as res:
            obj = json.load(res)
    except HTTPError as ex:
        raise RuntimeError(f'GitHub API HTTP {ex.code}; obey limits, do not retry indefinitely') from ex
    except URLError as ex:
        raise RuntimeError(f'GitHub API not reachable: {ex.reason}') from ex
    return _parse(obj, slug)
