"""A small GitHub Actions API client.

urllib rather than requests, so the tool has no runtime dependencies. The HTTP call is injectable
so tests never touch the network, which matters more than it sounds: the interesting cases here
are re-run attempts and paginated job lists, and those are tedious to reproduce against a live
repository on demand.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

from .models import Job

API = "https://api.github.com"

Fetch = Callable[[str, dict[str, str]], tuple[int, dict[str, str], bytes]]


API_HOST = "api.github.com"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Stops urllib following redirects on its own so we can decide what to send onwards."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def _urlopen(url: str, headers: dict[str, str], _depth: int = 0
             ) -> tuple[int, dict[str, str], bytes]:
    """GET, following redirects by hand.

    Two redirects matter here and urllib gets one of them wrong.

    A job log 302s to signed blob storage, and urllib's own redirect handling forwards the
    Authorization header to it. The storage backend rejects a bearer token it did not issue with
    401 InvalidAuthenticationInfo, so every log fetch comes back empty and every flake ends up
    uncategorised. The signature in the redirect URL is the credential, so the header has to be
    dropped when the host changes. curl -L does this by default, which is why the same request
    works from a shell and not from Python.

    A repository that has been renamed 301s within api.github.com, and there the header must be
    kept or the retry is unauthenticated.
    """
    request = urllib.request.Request(url, headers=headers)
    try:
        with _OPENER.open(request, timeout=60) as response:
            status, response_headers, body = (
                response.status, dict(response.headers), response.read())
    except urllib.error.HTTPError as exc:
        status, response_headers, body = exc.code, dict(exc.headers or {}), exc.read()

    if status in (301, 302, 303, 307, 308) and _depth < 5:
        location = response_headers.get("Location")
        if not location:
            return status, response_headers, body
        target = urllib.parse.urljoin(url, location)
        return _urlopen(target, onward_headers(target, headers), _depth + 1)

    return status, response_headers, body


def onward_headers(target: str, headers: dict[str, str]) -> dict[str, str]:
    """Which headers survive a redirect.

    Everything if we are still on api.github.com, because a renamed repository 301s within the API
    and the retry has to stay authenticated. Nothing but the user agent otherwise, because the
    signature embedded in a blob storage URL is the credential and a bearer token it did not issue
    gets the whole request rejected.
    """
    if urllib.parse.urlparse(target).hostname == API_HOST:
        return headers
    return {"User-Agent": headers.get("User-Agent", "flaketriage")}


class GitHub:
    def __init__(self, repo: str, token: str | None = None, fetch: Fetch = _urlopen,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self.repo = repo
        self.token = token if token is not None else os.environ.get("GITHUB_TOKEN", "")
        self._fetch = fetch
        self._sleep = sleep

    def _headers(self, accept: str = "application/vnd.github+json") -> dict[str, str]:
        headers = {"Accept": accept, "X-GitHub-Api-Version": "2022-11-28",
                   "User-Agent": "flaketriage"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _get_json(self, path: str, **params: Any) -> dict:
        query = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        url = f"{API}{path}" + (f"?{query}" if query else "")

        for attempt in range(4):
            status, headers, body = self._fetch(url, self._headers())
            if status == 200:
                return json.loads(body)
            # Secondary rate limits come back as 403 with a Retry-After. Honour it rather than
            # hammering, because getting the token blocked mid-backfill wastes the whole run.
            if status in (403, 429) and attempt < 3:
                self._sleep(float(headers.get("Retry-After", 2 ** attempt)))
                continue
            raise RuntimeError(f"GET {url} failed with {status}: {body[:200]!r}")
        raise RuntimeError(f"GET {url} gave up after retries")

    def runs(self, workflow: str | None = None, status: str = "completed",
             per_page: int = 50, created: str | None = None) -> list[dict]:
        """Recent workflow runs, newest first."""
        path = f"/repos/{self.repo}/actions/runs"
        if workflow:
            path = f"/repos/{self.repo}/actions/workflows/{workflow}/runs"
        payload = self._get_json(path, status=status, per_page=per_page, created=created)
        return payload.get("workflow_runs", [])

    def jobs(self, run_id: int, attempt: int | None = None) -> list[Job]:
        """Jobs for a run, or for one specific attempt of it.

        The per-attempt endpoint is the important one. Without it you only ever see the latest
        attempt, and a flake that passed on re-run looks like a job that simply passed.
        """
        if attempt is None:
            path = f"/repos/{self.repo}/actions/runs/{run_id}/jobs"
        else:
            path = f"/repos/{self.repo}/actions/runs/{run_id}/attempts/{attempt}/jobs"

        collected: list[Job] = []
        page = 1
        while True:
            payload = self._get_json(path, per_page=100, page=page, filter="latest")
            batch = payload.get("jobs", [])
            collected.extend(_to_job(j) for j in batch)
            if len(batch) < 100:
                break
            page += 1
        return collected

    def run_attempts(self, run_id: int) -> int:
        payload = self._get_json(f"/repos/{self.repo}/actions/runs/{run_id}")
        return int(payload.get("run_attempt", 1))

    def job_log(self, job_id: int) -> str:
        """Raw log text for one job. Empty string when it has already been expired by retention."""
        url = f"{API}/repos/{self.repo}/actions/jobs/{job_id}/logs"
        status, _, body = self._fetch(url, self._headers(accept="application/vnd.github+json"))
        if status == 200:
            return body.decode("utf-8", errors="replace")
        if status in (404, 410):
            return ""
        raise RuntimeError(f"log fetch for job {job_id} failed with {status}")


def _to_job(raw: dict) -> Job:
    return Job(
        id=raw["id"],
        run_id=raw["run_id"],
        run_attempt=raw.get("run_attempt", 1),
        name=raw.get("name", ""),
        conclusion=raw.get("conclusion") or "",
        started_at=raw.get("started_at") or "",
        completed_at=raw.get("completed_at") or "",
        html_url=raw.get("html_url") or "",
        head_sha=raw.get("head_sha") or "",
        workflow_name=raw.get("workflow_name") or "",
    )
