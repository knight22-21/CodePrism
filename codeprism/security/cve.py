"""CVE checker — queries the OSV API for known vulnerabilities in PyPI packages."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

_OSV_QUERY_URL = "https://api.osv.dev/v1/query"
_TIMEOUT = 5  # seconds

# Regex to capture package name, optional extras, and exact pin (== or ===)
_EXACT_PIN_RE = re.compile(
    r"^([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[^\]]*\])?\s*(?:===|==)\s*([A-Za-z0-9._+-]+)$"
)


@dataclass
class CVEResult:
    package: str
    version: str
    cve_ids: list[str] = field(default_factory=list)
    severity: str = "UNKNOWN"  # LOW | MEDIUM | HIGH | CRITICAL | UNKNOWN
    summary: str = ""


def check_package(package: str, version: str = "") -> CVEResult:
    """
    Query the OSV API for known vulnerabilities in a PyPI package.

    Returns a CVEResult with severity CRITICAL/HIGH/MEDIUM/LOW/UNKNOWN.
    Falls back gracefully (returns UNKNOWN) if the network call fails.
    """
    clean_package = package.strip()
    clean_version = version.strip()

    query: dict[str, Any] = {"package": {"name": clean_package, "ecosystem": "PyPI"}}
    if clean_version:
        query["version"] = clean_version
    payload = json.dumps(query).encode()

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
        return CVEResult(package=clean_package, version=clean_version)

    vulns = data.get("vulns", [])
    if not vulns:
        return CVEResult(package=clean_package, version=clean_version, severity="PASS")

    cve_ids: list[str] = []
    worst = "LOW"
    _order = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}

    for vuln in vulns:
        for alias in vuln.get("aliases", []):
            if alias.startswith("CVE-"):
                cve_ids.append(alias)
        # database_specific.severity holds a plain word (CRITICAL/HIGH/MEDIUM/LOW).
        # severity[].score is a CVSS vector string — not usable for severity ranking.
        db_sev = vuln.get("database_specific", {}).get("severity", "").upper()
        if db_sev in _order and _order[db_sev] > _order.get(worst, 0):
            worst = db_sev

    summary = f"{len(vulns)} known vulnerabilities for {clean_package}"
    return CVEResult(
        package=clean_package,
        version=clean_version,
        cve_ids=cve_ids[:10],
        severity=worst,
        summary=summary,
    )


def check_requirements(requirements_content: str) -> list[CVEResult]:
    """
    Parse a requirements.txt blob and run CVE checks on each package.

    Skips comment lines, blank lines, and URL-based requirements.
    Extracts exact pinned versions (== and ===) to query version-specific CVEs.
    Returns only packages that have known vulnerabilities (severity != PASS).
    """
    results: list[CVEResult] = []
    for raw_line in requirements_content.splitlines():
        line = raw_line.strip()
        if (
            not line
            or line.startswith("#")
            or line.startswith("-")
            or "://" in line
            or line.startswith(".")
        ):
            continue

        clean = line.split("#", 1)[0].strip()
        if not clean:
            continue

        spec = clean.split(";", 1)[0].strip()
        if not spec or "@" in spec:
            continue

        exact_match = _EXACT_PIN_RE.match(spec)
        if exact_match:
            pkg = exact_match.group(1)
            version = exact_match.group(2)
        else:
            match = re.match(r"^[A-Za-z0-9][A-Za-z0-9._-]*", spec)
            if not match:
                continue
            pkg = match.group(0)
            version = ""

        result = check_package(pkg, version)
        if result.severity not in ("PASS", "UNKNOWN"):
            results.append(result)
    return results
