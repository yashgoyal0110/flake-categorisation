"""Pipeline tests with a fake GitHub, so the whole path runs without a network call."""

from flaketriage.classify.heuristic import HeuristicClassifier
from flaketriage.models import Job
from flaketriage.pipeline import classify_pending, collect_jobs, ingest
from flaketriage.store import Store


class FakeGitHub:
    def __init__(self, jobs_by_attempt, logs=None, failing_logs=()):
        self._jobs = jobs_by_attempt
        self._logs = logs or {}
        self._failing = set(failing_logs)
        self.attempts_requested = []

    def jobs(self, run_id, attempt=None):
        self.attempts_requested.append((run_id, attempt))
        return self._jobs.get((run_id, attempt), [])

    def job_log(self, job_id):
        if job_id in self._failing:
            raise RuntimeError("log expired")
        return self._logs.get(job_id, "")


def job(job_id, *, run=1, attempt=1, conclusion="failure", name="int local root fedora-current"):
    return Job(id=job_id, run_id=run, run_attempt=attempt, name=name, conclusion=conclusion,
               started_at="2026-08-08T10:00:00Z", completed_at="2026-08-08T10:05:00Z",
               html_url=f"https://x/{job_id}", head_sha="abc", workflow_name="ci")


def test_single_attempt_runs_are_not_walked_per_attempt():
    # Walking attempts costs an API call each. Only runs that were actually re-run need it.
    client = FakeGitHub({(1, None): [job(1)]})
    collect_jobs(client, [{"id": 1, "run_attempt": 1}])
    assert client.attempts_requested == [(1, None)]


def test_rerun_runs_are_walked_attempt_by_attempt():
    client = FakeGitHub({(1, 1): [job(1, attempt=1)],
                         (1, 2): [job(2, attempt=2, conclusion="success")]})
    jobs = collect_jobs(client, [{"id": 1, "run_attempt": 2}])
    assert client.attempts_requested == [(1, 1), (1, 2)]
    assert len(jobs) == 2


def test_a_failing_run_does_not_abort_the_batch():
    # One unreadable run should not lose the other twenty-four.
    class Partial(FakeGitHub):
        def jobs(self, run_id, attempt=None):
            if run_id == 2:
                raise RuntimeError("410 gone")
            return super().jobs(run_id, attempt)

    client = Partial({(1, None): [job(1)], (3, None): [job(3)]})
    jobs = collect_jobs(client, [{"id": 1}, {"id": 2}, {"id": 3}])
    assert {j.id for j in jobs} == {1, 3}


def test_ingest_attaches_a_reduced_log_and_stores(tmp_path):
    client = FakeGitHub(
        {(1, 1): [job(1, attempt=1)], (1, 2): [job(2, attempt=2, conclusion="success")]},
        logs={1: "2026-08-08T10:00:00.0000000Z Error: connection reset by peer"},
    )
    store = Store(tmp_path / "t.db")

    flakes = ingest(client, store, [{"id": 1, "run_attempt": 2}])

    assert len(flakes) == 1
    stored = store.all()[0]
    assert stored.excerpt == "Error: connection reset by peer", "timestamp should be stripped"


def test_a_missing_log_is_recorded_anyway(tmp_path):
    # Logs age out of retention. The flake still happened and still belongs in the record.
    client = FakeGitHub(
        {(1, 1): [job(1, attempt=1)], (1, 2): [job(2, attempt=2, conclusion="success")]},
        failing_logs={1},
    )
    store = Store(tmp_path / "t.db")
    ingest(client, store, [{"id": 1, "run_attempt": 2}])

    assert len(store.all()) == 1
    assert store.all()[0].excerpt == ""


def test_classify_pending_is_resumable(tmp_path):
    client = FakeGitHub(
        {(1, 1): [job(1, attempt=1)], (1, 2): [job(2, attempt=2, conclusion="success")]},
        logs={1: "no space left on device"},
    )
    store = Store(tmp_path / "t.db")
    ingest(client, store, [{"id": 1, "run_attempt": 2}])

    assert classify_pending(store, HeuristicClassifier()) == 1
    assert classify_pending(store, HeuristicClassifier()) == 0, "already done, nothing to redo"
    assert store.all()[0].verdict.category.value == "resource"


def test_auth_survives_an_api_redirect_but_not_a_storage_one():
    """GitHub 302s job logs to signed blob storage.

    urllib's own redirect handling forwards the Authorization header, and the storage backend
    answers 401 InvalidAuthenticationInfo, so every excerpt comes back empty and every flake is
    filed as unknown. curl -L drops auth across hosts, which is why the same request worked from a
    shell and not from Python. Only turned up against the live repository.
    """
    from flaketriage.github import onward_headers

    headers = {"Authorization": "Bearer secret", "User-Agent": "flaketriage"}

    # A renamed repository 301s within the API, and the retry must stay authenticated.
    kept = onward_headers("https://api.github.com/repos/new-org/podman/actions/runs", headers)
    assert kept["Authorization"] == "Bearer secret"

    # A log 302s to signed storage, where our token is not only useless but fatal.
    dropped = onward_headers(
        "https://productionresultssa0.blob.core.windows.net/actions-results/x?sig=abc", headers)
    assert "Authorization" not in dropped
    assert dropped["User-Agent"] == "flaketriage"
