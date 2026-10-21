"""Deterministic candidate scoring. Pure function, no I/O, fully testable.

Score 0-100 from metadata only: stars, recent push, license grade,
with archived/fork penalties. Output includes human-readable reasons.
License grading mirrors policy.py groupings; scoring never approves
a license, it only ranks candidates that already passed the gate.
"""
from datetime import datetime, timezone

LICENSE_SCORE = {
    "MIT": 25, "Apache-2.0": 25, "BSD-2-Clause": 25, "BSD-3-Clause": 25,
    "CC0-1.0": 20,
    "GPL-3.0": 10, "GPL-2.0": 10, "AGPL-3.0": 10, "LGPL-3.0": 10,
    "CC-BY-4.0": 10, "MPL-2.0": 10,
    "UNKNOWN": 0, "NO-LICENSE": 0, "PROPRIETARY": 0,
    "CC-BY-NC-4.0": 0, "CC-BY-NC-SA-4.0": 0,
}
PERMISSIVE = set(LICENSE_SCORE) - {"UNKNOWN", "NO-LICENSE", "PROPRIETARY",
                                    "CC-BY-NC-4.0", "CC-BY-NC-SA-4.0"}

RECENT_PUSH_DAYS = 180      # pushed within half a year counts as active
STALE_PUSH_DAYS = 730       # older than two years is stale
STARS_FULL = 50000          # stars at/above this get the full 40
MAX_STARS = 40
MAX_RECENT = 25
MAX_LICENSE = 25
PENALTY_ARCHIVED = -30
PENALTY_FORK = -20


def _days_since(iso: str | None, ref: datetime | None = None) -> float | None:
    if not iso:
        return None
    ref = ref or datetime.now(timezone.utc)
    try:
        ts = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return max((ref - ts).total_seconds() / 86400.0, 0.0)


def score_candidate(candidate: dict, *, now: datetime | None = None) -> dict:
    """Return {'score': 0-100, 'reasons': [...], 'breakdown': {...}}.

    Accepts either a collector item (license/metadata nested) or a flat
    dict with stars/license/pushed_at/archived/fork keys.
    """
    meta = candidate.get("metadata") or {}
    stars = meta.get("stars", candidate.get("stars", 0)) or 0
    license_id = str(candidate.get("license") or "UNKNOWN")
    pushed_at = meta.get("pushed_at") or candidate.get("pushed_at")
    archived = bool(meta.get("archived", candidate.get("archived", False)))
    fork = bool(meta.get("fork", candidate.get("fork", False)))

    reasons: list[str] = []
    breakdown: dict[str, float] = {}

    # stars: logarithmic-ish capped tier (simple, deterministic)
    star_pts = min(float(stars) / STARS_FULL, 1.0) * MAX_STARS
    breakdown["stars"] = round(star_pts, 1)
    reasons.append(f"stars={stars}: +{star_pts:.1f} (cap {MAX_STARS} at {STARS_FULL})")

    # recent push activity
    days = _days_since(pushed_at, now)
    if days is None:
        recent_pts = 0.0
        reasons.append("pushed_at missing/unparsable: +0 activity score")
    elif days <= RECENT_PUSH_DAYS:
        recent_pts = MAX_RECENT
        reasons.append(f"pushed {int(days)}d ago: active, +{MAX_RECENT}")
    elif days <= STALE_PUSH_DAYS:
        # linear decay between 180d and 730d
        frac = 1.0 - (days - RECENT_PUSH_DAYS) / (STALE_PUSH_DAYS - RECENT_PUSH_DAYS)
        recent_pts = round(MAX_RECENT * frac, 1)
        reasons.append(f"pushed {int(days)}d ago: decaying activity, +{recent_pts}")
    else:
        recent_pts = 0.0
        reasons.append(f"pushed {int(days)}d ago: stale, +0")

    # license grade
    lic_pts = float(LICENSE_SCORE.get(license_id, 0))
    breakdown["license"] = lic_pts
    if license_id in PERMISSIVE:
        reasons.append(f"license {license_id}: permissive, +{lic_pts}")
    else:
        reasons.append(f"license {license_id}: not permissive, +{lic_pts}")

    breakdown["activity"] = recent_pts
    breakdown.update({"archived_penalty": 0.0, "fork_penalty": 0.0})

    total = star_pts + recent_pts + lic_pts
    if archived:
        total += PENALTY_ARCHIVED
        breakdown["archived_penalty"] = PENALTY_ARCHIVED
        reasons.append(f"archived repo: {PENALTY_ARCHIVED}")
    if fork:
        total += PENALTY_FORK
        breakdown["fork_penalty"] = PENALTY_FORK
        reasons.append(f"fork repo: {PENALTY_FORK}")

    score = int(max(0, min(100, round(total))))
    breakdown["total"] = score
    return {"score": score, "reasons": reasons, "breakdown": breakdown}


def rank_candidates(candidates: list[dict], *, now: datetime | None = None) -> list[dict]:
    """Return candidates sorted by score desc, each annotated with score fields."""
    ranked = [dict(c, **score_candidate(c, now=now)) for c in candidates]
    ranked.sort(key=lambda r: (-r["score"], r["id"]))
    return ranked
