"""Wiring: fetch, detect, reduce, classify, store."""

from __future__ import annotations

from collections.abc import Callable

from .classify import Classifier
from .detect import find_flakes
from .github import GitHub
from .logs import reduce_log
from .models import Flake, Job
from .store import Store


def collect_jobs(client: GitHub, runs: list[dict],
                 log: Callable[[str], None] = lambda _: None) -> list[Job]:
    """Every job across every attempt of the given runs.

    Walking attempts is what makes re-run detection possible at all, and it is also the expensive
    part, so it only happens for runs that actually had more than one.
    """
    jobs: list[Job] = []
    for run in runs:
        run_id = run["id"]
        attempts = int(run.get("run_attempt", 1))
        for attempt in range(1, attempts + 1):
            try:
                jobs.extend(client.jobs(run_id, attempt if attempts > 1 else None))
            except RuntimeError as exc:
                log(f"  skipped run {run_id} attempt {attempt}: {exc}")
    return jobs


def ingest(client: GitHub, store: Store, runs: list[dict],
           log: Callable[[str], None] = lambda _: None) -> list[Flake]:
    """Find flakes in these runs, attach a reduced log to each, and store them."""
    jobs = collect_jobs(client, runs, log)
    log(f"looked at {len(jobs)} jobs across {len(runs)} runs")

    flakes = find_flakes(jobs)
    log(f"{len(flakes)} look like flakes")

    for flake in flakes:
        try:
            raw = client.job_log(flake.job_id)
        except RuntimeError as exc:
            log(f"  no log for job {flake.job_id}: {exc}")
            raw = ""
        flake.excerpt = reduce_log(raw)
        store.save(flake)

    return flakes


def classify_pending(store: Store, classifier: Classifier, limit: int = 100,
                     log: Callable[[str], None] = lambda _: None) -> int:
    """Classify everything not yet classified. Safe to run repeatedly."""
    pending = store.unclassified(limit=limit)
    for flake in pending:
        flake.verdict = classifier.classify(flake)
        store.save(flake)
        log(f"  {flake.job_name}: {flake.verdict.category.value}")
    return len(pending)
