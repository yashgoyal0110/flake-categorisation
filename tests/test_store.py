from flaketriage.models import Category, Flake, Verdict
from flaketriage.store import Store


def make_flake(job_id: int = 1, name: str = "int local rootless fedora-current") -> Flake:
    return Flake(
        job_id=job_id, run_id=100, run_attempt=1, job_name=name,
        head_sha="abc1234", html_url="https://github.com/x/y/actions/runs/100",
        detected_by="rerun-passed", failed_at="2026-08-03T10:00:00Z",
        excerpt="connection reset by peer",
    )


def test_saves_and_reads_back(tmp_path):
    store = Store(tmp_path / "t.db")
    store.save(make_flake())

    got = store.all()
    assert len(got) == 1
    assert got[0].job_name == "int local rootless fedora-current"
    assert got[0].verdict is None


def test_save_is_idempotent_on_job_id(tmp_path):
    # Ingestion re-runs over an overlapping window, so the same job will be seen more than once.
    store = Store(tmp_path / "t.db")
    store.save(make_flake())
    store.save(make_flake())
    assert len(store.all()) == 1


def test_classifying_updates_in_place(tmp_path):
    store = Store(tmp_path / "t.db")
    flake = make_flake()
    store.save(flake)
    assert len(store.unclassified()) == 1

    flake.verdict = Verdict(
        category=Category.NETWORK, confidence=0.8,
        summary="registry connection reset mid-pull",
        suggestion="retry the pull", classifier="heuristic",
        evidence=["connection reset by peer"],
    )
    store.save(flake)

    assert store.unclassified() == []
    got = store.all()[0]
    assert got.verdict.category is Category.NETWORK
    assert got.verdict.evidence == ["connection reset by peer"]


def test_counts_group_unclassified_separately(tmp_path):
    store = Store(tmp_path / "t.db")
    store.save(make_flake(1))

    classified = make_flake(2)
    classified.verdict = Verdict(Category.INFRA, 0.9, "runner died")
    store.save(classified)

    assert store.count_by_category() == {"unclassified": 1, "infra": 1}
