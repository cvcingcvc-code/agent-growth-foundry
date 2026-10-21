"""Conservative asset/usage gates, not a legal determination."""
from dataclasses import dataclass

ALLOW_FOR_REVIEW = {"MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "CC0-1.0"}
NEEDS_SPECIAL_REVIEW = {"GPL-3.0", "GPL-2.0", "AGPL-3.0", "LGPL-3.0", "CC-BY-4.0", "MPL-2.0"}
DENY_COMMERCIAL = {"CC-BY-NC-4.0", "CC-BY-NC-SA-4.0", "NO-LICENSE", "UNKNOWN", "PROPRIETARY"}

@dataclass(frozen=True)
class Decision:
    status: str
    reason: str


def assess_license(license_id: str, *, asset_rights_verified: bool = False) -> Decision:
    """No automatic approval for commercial release, even for permissive licenses."""
    key = str(license_id or "UNKNOWN").strip()
    if key in DENY_COMMERCIAL or not key:
        return Decision("BLOCKED", f"License {key or 'UNKNOWN'} cannot enter commercial output by default")
    if key in NEEDS_SPECIAL_REVIEW:
        return Decision("REVIEW", f"License {key} requires special obligations review")
    if key in ALLOW_FOR_REVIEW:
        if not asset_rights_verified:
            return Decision("REVIEW", "Repo license alone does not clear dependencies, images or datasets")
        return Decision("REVIEW", "Eligible candidate, requires human release approval")
    return Decision("REVIEW", f"Unknown/non-standard license {key}; do not reuse until verified")
