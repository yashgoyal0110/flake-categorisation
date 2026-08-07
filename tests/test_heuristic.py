import pytest

from flaketriage.classify.heuristic import HeuristicClassifier
from flaketriage.models import Category, Flake


def flake(excerpt: str) -> Flake:
    return Flake(job_id=1, run_id=1, run_attempt=1,
                 job_name="int local root fedora-current", head_sha="aaa", html_url="",
                 detected_by="rerun-passed", failed_at="2026-08-05T10:00:00Z",
                 excerpt=excerpt)


@pytest.mark.parametrize("excerpt,expected", [
    ("Error: connection reset by peer while pulling quay.io/podman/stable", Category.NETWORK),
    ("write /var/tmp/x: no space left on device", Category.RESOURCE),
    ("context deadline exceeded waiting for container to start", Category.TIMING),
    ("Error response from daemon: manifest unknown", Category.INFRA),
])
def test_recognises_the_obvious_ones(excerpt, expected):
    verdict = HeuristicClassifier().classify(flake(excerpt))
    assert verdict.category is expected
    assert verdict.confidence > 0.5
    assert verdict.evidence, "a verdict should point at the line that caused it"


def test_says_unknown_rather_than_guessing():
    # The number that decides whether maintainers keep reading the report is how often it is
    # confidently wrong, not how often it answers.
    verdict = HeuristicClassifier().classify(flake("something nobody has seen before"))
    assert verdict.category is Category.UNKNOWN
    assert verdict.confidence == 0.0


def test_empty_excerpt_is_unknown_not_a_crash():
    verdict = HeuristicClassifier().classify(flake(""))
    assert verdict.category is Category.UNKNOWN
    assert "no log excerpt" in verdict.summary


def test_a_build_failure_is_not_called_a_flake():
    verdict = HeuristicClassifier().classify(
        flake("./pkg/x.go:12:2: cannot use foo (type int) as type string"))
    assert verdict.category is Category.REAL
    assert not verdict.category.is_flake


def test_resource_beats_network_when_both_appear():
    # Ordering is deliberate. A disk-full runner often also produces connection errors, and
    # telling someone to retry the pull when the disk is full wastes their afternoon.
    verdict = HeuristicClassifier().classify(
        flake("no space left on device\nconnection refused"))
    assert verdict.category is Category.RESOURCE


def test_a_held_port_counts_as_a_resource_problem():
    # Found by running the sample set: a port left behind by a previous test was falling through
    # to unknown. It is exhaustion of a shared resource, and the fix is to find the leak.
    verdict = HeuristicClassifier().classify(
        flake("listen tcp4 :8080: bind: address already in use"))
    assert verdict.category is Category.RESOURCE


def test_a_dnf_timeout_inside_a_build_is_a_network_problem():
    # dnf and curl phrase timeouts differently to Go's net package, so the Go-shaped patterns
    # missed them entirely.
    verdict = HeuristicClassifier().classify(
        flake('error building at STEP "RUN dnf -y install golang": Curl error (28): '
              "Timeout was reached"))
    assert verdict.category is Category.NETWORK
