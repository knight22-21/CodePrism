"""CVE checker — queries the OSV API for known vulnerabilities in PyPI packages."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field

_OSV_QUERY_URL = "https://api.osv.dev/v1/query"
_TIMEOUT = 5  # seconds


@dataclass
class CVEResult:
    package: str
    version: str
    cve_ids: list[str] = field(default_factory=list)
    severity: str = "UNKNOWN"   # LOW | MEDIUM | HIGH | CRITICAL | UNKNOWN
    summary: str = ""


def check_package(package: str, version: str = "") -> CVEResult:
    """
    Query the OSV API for known vulnerabilities in a PyPI package.

    Returns a CVEResult with severity CRITICAL/HIGH/MEDIUM/LOW/UNKNOWN.
    Falls back gracefully (returns UNKNOWN) if the network call fails.
    """
    payload = json.dumps(
        {"package": {"name": package, "ecosystem": "PyPI"}}
    ).encode()

    req = urllib.request.Request(
        _OSV_QUERY_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            data = json.loads(resp.read())
    except (urllib.error.URLError, OSError, json.JSONDecodeError):
        return CVEResult(package=package, version=version)

    vulns = data.get("vulns", [])
    if not vulns:
        return CVEResult(package=package, version=version, severity="PASS")

    cve_ids: list[str] = []
    worst = "LOW"
    _order = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}

    for vuln in vulns:
        for alias in vuln.get("aliases", []):
            if alias.startswith("CVE-"):
                cve_ids.append(alias)
        for sev in vuln.get("severity", []):
            lvl = sev.get("score", "").upper()
            if _order.get(lvl, 0) > _order.get(worst, 0):
                worst = lvl

    summary = f"{len(vulns)} known vulnerabilities for {package}"
    return CVEResult(
        package=package,
        version=version,
        cve_ids=cve_ids[:10],
        severity=worst,
        summary=summary,
    )


def check_requirements(requirements_content: str) -> list[CVEResult]:
    """
    Parse a requirements.txt blob and run CVE checks on each package.

    Skips comment lines, blank lines, and URL-based requirements.
    Returns only packages that have known vulnerabilities (severity != PASS).
    """
    results: list[CVEResult] = []
    for raw_line in requirements_content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith("-") or "://" in line:
            continue
        # Strip extras and version specifiers: requests[security]>=2.28 → requests, 2.28
        pkg = line.split("[")[0].split(">=")[0].split("<=")[0].split("==")[0]
        pkg = pkg.split("!=")[0].split("~=")[0].strip()
        if not pkg:
            continue
        result = check_package(pkg)
        if result.severity not in ("PASS", "UNKNOWN"):
            results.append(result)
    return results
