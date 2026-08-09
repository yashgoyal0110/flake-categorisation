from flaketriage.detect import RERUN_PASSED, SAME_SHA_PASSED, find_flakes
from flaketriage.models import Job


def job(job_id, *, run=1, attempt=1, name="int local root fedora-current",
        conclusion="failure", sha="aaa", at="2026-08-04T10:00:00Z") -> Job:
    return Job(id=job_id, run_id=run, run_attempt=attempt, name=name, conclusion=conclusion,
               started_at=at, completed_at=at, html_url=f"https://x/{job_id}",
               head_sha=sha, workflow_name="ci")


def test_rerun_that_passed_is_a_flake():
    jobs = [
        job(1, run=10, attempt=1, conclusion="failure"),
        job(2, run=10, attempt=2, conclusion="success"),
    ]
    flakes = find_flakes(jobs)
    assert [f.job_id for f in flakes] == [1]
    assert flakes[0].detected_by == RERUN_PASSED


def test_a_job_that_stayed_red_is_not_a_flake():
    jobs = [
        job(1, run=10, attempt=1, conclusion="failure"),
        job(2, run=10, attempt=2, conclusion="failure"),
    ]
    assert find_flakes(jobs) == []


def test_rerun_rule_needs_the_pass_to_come_after():
    # The rerun rule is directional: it means "was red, went green". Green then red does not
    # satisfy it.
    jobs = [
        job(1, run=10, attempt=1, conclusion="success", sha="aaa"),
        job(2, run=10, attempt=2, conclusion="failure", sha="bbb"),
    ]
    assert find_flakes(jobs) == []


def test_green_then_red_on_the_same_commit_is_still_a_flake():
    # The same-sha rule is not directional, and should not be. If one commit produced both a pass
    # and a failure then the result is not deterministic, which is the definition of the thing we
    # are looking for. Which one came first only says which run was unlucky.
    jobs = [
        job(1, run=10, attempt=1, conclusion="success", sha="aaa"),
        job(2, run=10, attempt=2, conclusion="failure", sha="aaa"),
    ]
    flakes = find_flakes(jobs)
    assert [f.job_id for f in flakes] == [2]
    assert flakes[0].detected_by == SAME_SHA_PASSED


def test_same_commit_passing_elsewhere_is_a_flake():
    jobs = [
        job(1, run=10, sha="deadbeef", conclusion="failure"),
        job(2, run=11, sha="deadbeef", conclusion="success"),
    ]
    flakes = find_flakes(jobs)
    assert [f.job_id for f in flakes] == [1]
    assert flakes[0].detected_by == SAME_SHA_PASSED


def test_different_commits_are_not_compared():
    jobs = [
        job(1, run=10, sha="aaa", conclusion="failure"),
        job(2, run=11, sha="bbb", conclusion="success"),
    ]
    assert find_flakes(jobs) == []


def test_different_job_names_are_not_compared():
    jobs = [
        job(1, run=10, sha="aaa", name="int local root fedora-current", conclusion="failure"),
        job(2, run=11, sha="aaa", name="sys remote rootless debian-sid", conclusion="success"),
    ]
    assert find_flakes(jobs) == []


def test_the_stronger_rule_wins_when_both_apply():
    jobs = [
        job(1, run=10, attempt=1, sha="aaa", conclusion="failure"),
        job(2, run=10, attempt=2, sha="aaa", conclusion="success"),
        job(3, run=11, sha="aaa", conclusion="success"),
    ]
    flakes = find_flakes(jobs)
    assert len(flakes) == 1
    assert flakes[0].detected_by == RERUN_PASSED


def test_dimensions_survive_onto_the_flake():
    jobs = [
        job(1, run=10, attempt=1, name="sys remote rootless fedora-rawhide", conclusion="failure"),
        job(2, run=10, attempt=2, name="sys remote rootless fedora-rawhide", conclusion="success"),
    ]
    assert find_flakes(jobs)[0].dimensions == {
        "test": "sys", "mode": "remote", "priv": "rootless", "distro": "fedora-rawhide",
    }


def test_reusable_workflow_suffix_is_stripped():
    # Real Podman jobs come through a reusable workflow, so GitHub names them
    # "<job> / <workflow>". Found this only after pointing it at the live repo.
    j = job(1, name="sys local rootless fedora-current / lima")
    assert j.dimensions == {
        "test": "sys", "mode": "local", "priv": "rootless", "distro": "fedora-current",
    }


def test_aggregate_gate_jobs_are_not_counted():
    # "Total Success" is the needs-gate. It goes red because something it depends on went red, so
    # counting it means every flake appears twice, the second time under a name that says nothing.
    jobs = [
        job(1, run=10, attempt=1, name="Total Success", conclusion="failure"),
        job(2, run=10, attempt=2, name="Total Success", conclusion="success"),
        job(3, run=10, attempt=1, name="int local root fedora-current", conclusion="failure"),
        job(4, run=10, attempt=2, name="int local root fedora-current", conclusion="success"),
    ]
    flakes = find_flakes(jobs)
    assert [f.job_id for f in flakes] == [3]
