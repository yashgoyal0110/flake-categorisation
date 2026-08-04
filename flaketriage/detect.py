"""Decide which failures were flakes.

There is no single correct answer here, which is the first thing worth agreeing with maintainers
rather than assuming. Two rules are implemented because they have different trade-offs and
between them they cover most of what is visible from the API.

RERUN_PASSED is precise and under-counts. It only fires when somebody clicked re-run, so a flake
nobody bothered to re-run is invisible to it. It is the closest thing to ground truth available,
which makes it the right source for a labelled set.

SAME_SHA_PASSED catches more. If the identical commit produced both a failing and a passing run of
the same job, the code did not change, so something else did. It picks up flakes nobody re-ran, at
the cost of occasionally being fooled by a change in the environment between the two runs.

A third rule, correlating the same failing test across unrelated pull requests, would catch the
most and needs a stable test identity parsed out of the log. That is deliberately not here yet,
because getting test identity wrong quietly poisons the data.
"""

from __future__ import annotations

from collections import defaultdict

from .models import Flake, Job

RERUN_PASSED = "rerun-passed"
SAME_SHA_PASSED = "same-sha-passed"


def find_flakes(jobs: list[Job]) -> list[Flake]:
    """Given every job across every attempt, return the failures that look like flakes."""
    flakes: dict[int, Flake] = {}

    for job in _rerun_passed(jobs):
        flakes[job.id] = _to_flake(job, RERUN_PASSED)

    for job in _same_sha_passed(jobs):
        # A job already caught by the stronger rule keeps that label.
        flakes.setdefault(job.id, _to_flake(job, SAME_SHA_PASSED))

    return sorted(flakes.values(), key=lambda f: f.failed_at, reverse=True)


def _rerun_passed(jobs: list[Job]) -> list[Job]:
    """Failed in one attempt of a run, passed in a later attempt of the same run."""
    by_run_and_name: dict[tuple[int, str], list[Job]] = defaultdict(list)
    for job in jobs:
        by_run_and_name[(job.run_id, job.name)].append(job)

    found = []
    for attempts in by_run_and_name.values():
        attempts.sort(key=lambda j: j.run_attempt)
        passed_later = {
            j.run_attempt for j in attempts if j.conclusion == "success"
        }
        for job in attempts:
            if job.failed and any(a > job.run_attempt for a in passed_later):
                found.append(job)
    return found


def _same_sha_passed(jobs: list[Job]) -> list[Job]:
    """Failed in one run, and the same job name passed on the identical commit in another run."""
    by_sha_and_name: dict[tuple[str, str], list[Job]] = defaultdict(list)
    for job in jobs:
        if job.head_sha:
            by_sha_and_name[(job.head_sha, job.name)].append(job)

    found = []
    for group in by_sha_and_name.values():
        if not any(j.conclusion == "success" for j in group):
            continue
        found.extend(j for j in group if j.failed)
    return found


def _to_flake(job: Job, detected_by: str) -> Flake:
    return Flake(
        job_id=job.id,
        run_id=job.run_id,
        run_attempt=job.run_attempt,
        job_name=job.name,
        head_sha=job.head_sha,
        html_url=job.html_url,
        detected_by=detected_by,
        failed_at=job.completed_at or job.started_at,
    )
