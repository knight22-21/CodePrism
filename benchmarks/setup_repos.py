"""
Clone real-world repos used for extended benchmark runs.

Usage:
    python -m benchmarks.setup_repos

Clones into benchmarks/repos/ (gitignored).
Skips repos that are already present.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPOS = [
    {
        "name": "requests",
        "url": "https://github.com/psf/requests.git",
        "tag": "v2.32.3",
    },
    {
        "name": "flask",
        "url": "https://github.com/pallets/flask.git",
        "tag": "3.0.3",
    },
    {
        "name": "httpx",
        "url": "https://github.com/encode/httpx.git",
        "tag": "0.27.2",
    },
    {
        "name": "fastapi",
        "url": "https://github.com/tiangolo/fastapi.git",
        "tag": "0.115.0",
    },
    {
        "name": "pydantic",
        "url": "https://github.com/pydantic/pydantic.git",
        "tag": "v2.9.2",
    },
    {
        "name": "express",
        "url": "https://github.com/expressjs/express.git",
        "tag": "v4.22.3",
    },
    {
        "name": "react",
        "url": "https://github.com/facebook/react.git",
        "tag": "v18.3.1",
    },
    {
        "name": "typescript",
        "url": "https://github.com/microsoft/TypeScript.git",
        "tag": "v5.6.3",
    },
    {
        "name": "gin",
        "url": "https://github.com/gin-gonic/gin.git",
        "tag": "v1.10.0",
    },
    {
        "name": "cobra",
        "url": "https://github.com/spf13/cobra.git",
        "tag": "v1.8.1",
    },
]

REPOS_DIR = Path(__file__).parent / "repos"


def clone(repo: dict) -> None:
    dest = REPOS_DIR / repo["name"]
    if dest.exists():
        print(f"  {repo['name']}: already present at {dest}")
        return
    REPOS_DIR.mkdir(parents=True, exist_ok=True)
    print(f"  {repo['name']}: cloning {repo['url']} @ {repo['tag']} ...")
    subprocess.run(
        ["git", "clone", "--depth=1", "--branch", repo["tag"], repo["url"], str(dest)],
        check=True,
    )
    print(f"  {repo['name']}: done -> {dest}")


def main() -> None:
    print(f"Cloning {len(REPOS)} repo(s) into {REPOS_DIR}\n")
    failed = []
    for repo in REPOS:
        try:
            clone(repo)
        except subprocess.CalledProcessError as exc:
            print(f"  ERROR cloning {repo['name']}: {exc}", file=sys.stderr)
            failed.append(repo["name"])
    print()
    if failed:
        print(f"Failed: {failed}", file=sys.stderr)
        sys.exit(1)
    print("All repos ready. Run the extended benchmark with:")
    print("  python -m benchmarks.run_token_benchmark --tasks benchmarks/tasks/requests_tasks.json")


if __name__ == "__main__":
    main()
