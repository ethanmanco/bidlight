"""Post the digest as a GitHub issue. GitHub then emails it to repo watchers."""

from __future__ import annotations

import requests

API = "https://api.github.com"
LABEL = "digest"


class GitHubError(RuntimeError):
    pass


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def ensure_label(repo: str, token: str, session: requests.Session) -> None:
    response = session.post(
        f"{API}/repos/{repo}/labels",
        headers=_headers(token),
        json={"name": LABEL, "color": "0e8a16", "description": "Daily Bidlight digest"},
        timeout=30,
    )
    if response.status_code not in (201, 422):  # 422: label already exists
        raise GitHubError(f"could not create label: HTTP {response.status_code}")


def post_issue(repo: str, token: str, title: str, body: str, session: requests.Session | None = None) -> str:
    """Create the issue and return its URL."""
    session = session or requests.Session()
    ensure_label(repo, token, session)
    response = session.post(
        f"{API}/repos/{repo}/issues",
        headers=_headers(token),
        json={"title": title, "body": body, "labels": [LABEL]},
        timeout=30,
    )
    if response.status_code != 201:
        raise GitHubError(f"could not create issue: HTTP {response.status_code} {response.text[:200]}")
    return response.json()["html_url"]
