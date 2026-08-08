from flaketriage.models import Category, Flake, Verdict
from flaketriage.report import group, issue_body, issue_title, signature, weekly_digest


def flake(job_id, name="int local root fedora-current", category=Category.NETWORK,
          summary="registry reset the connection"):
    f = Flake(job_id=job_id, run_id=job_id, run_attempt=1, job_name=name, head_sha="deadbeefcafe",
              html_url=f"https://github.com/x/y/runs/{job_id}", detected_by="rerun-passed",
              failed_at="2026-08-07T10:00:00Z", excerpt="connection reset by peer")
    if category:
        f.verdict = Verdict(category, 0.8, summary, "retry the pull", "heuristic",
                            ["connection reset by peer"])
    return f


def test_same_category_and_test_share_a_signature():
    # Distro is deliberately not in the key. Splitting one problem across four distros produces
    # four issues about one thing.
    a = flake(1, "int local root fedora-current")
    b = flake(2, "int remote rootless debian-sid")
    assert signature(a) == signature(b) == "network:int"


def test_different_tests_do_not_group():
    assert signature(flake(1, "int local root fedora-current")) != \
           signature(flake(2, "sys local root fedora-current"))


def test_groups_are_ordered_by_how_often_they_happened():
    flakes = [flake(1), flake(2), flake(3, "sys local root fedora-current")]
    assert list(group(flakes)) == ["network:int", "network:sys"]


def test_digest_calls_out_a_concentrated_dimension():
    flakes = [flake(i, "int local rootless fedora-rawhide") for i in range(4)]
    out = weekly_digest(flakes, repo="containers/podman")
    assert "always fedora-rawhide" in out
    assert "always rootless" in out


def test_digest_stays_quiet_when_there_is_no_pattern():
    flakes = [
        flake(1, "int local root fedora-current"),
        flake(2, "int local root debian-sid"),
        flake(3, "int remote rootless fedora-prior"),
    ]
    assert "no clear pattern" in weekly_digest(flakes)


def test_possible_real_failures_are_surfaced_first():
    flakes = [flake(1), flake(2, category=Category.REAL, summary="assertion failed")]
    out = weekly_digest(flakes)
    assert "may not be flakes at all" in out


def test_empty_window_says_so():
    assert "No flakes recorded" in weekly_digest([])


def test_issue_body_covers_every_occurrence_but_caps_the_list():
    flakes = [flake(i) for i in range(15)]
    body = issue_body("network:int", flakes)
    assert "Seen **15 times**" in body
    assert "and 5 more" in body
    assert "connection reset by peer" in body


def test_issue_title_mentions_the_pattern():
    flakes = [flake(i, "int local rootless fedora-rawhide") for i in range(3)]
    title = issue_title("network:int", flakes)
    assert title.startswith("[flake] int: network failures")
    assert "fedora-rawhide" in title


def test_unclassified_flakes_still_group():
    f = flake(1, category=None)
    assert signature(f) == "unclassified:int"


def test_group_order_is_stable_for_equal_counts():
    # Two runs over the same window should produce byte-identical reports, otherwise a scheduled
    # job that commits the digest generates noise diffs.
    flakes = [flake(1, "sys local root fedora-current"), flake(2, "apiv2 local root fedora-current")]
    assert list(group(flakes)) == list(group(list(reversed(flakes))))
