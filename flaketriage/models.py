"""The four things this tool talks about: a run, a job, a flake and a verdict."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class Category(StrEnum):
    """Why a job failed.

    Kept short on purpose. A classifier with twenty categories produces twenty ways to be subtly
    wrong, and a maintainer scanning a weekly report can hold about five buckets in their head.
    Each of these implies a different action, which is the only test of whether a category earns
    its place.
    """

    INFRA = "infra"                      # the runner, the registry, the image pull. Retry.
    NETWORK = "network"                  # timeout or connection reset reaching something external.
    TIMING = "timing"                    # race, ordering, or a too-short wait in the test itself.
    RESOURCE = "resource"                # out of disk, memory, ports, inotify watches.
    ENVIRONMENT = "environment"          # only fails on one distro, one privilege level, one mode.
    REAL = "real"                        # looks like an actual bug in the change under test.
    UNKNOWN = "unknown"                  # not enough signal. Say so instead of guessing.

    @property
    def is_flake(self) -> bool:
        """REAL is a failure worth keeping. UNKNOWN is an admission. The rest are flakes."""
        return self not in (Category.REAL, Category.UNKNOWN)


@dataclass(frozen=True)
class Job:
    """One job inside one attempt of one workflow run."""

    id: int
    run_id: int
    run_attempt: int
    name: str
    conclusion: str            # success, failure, cancelled, skipped
    started_at: str
    completed_at: str
    html_url: str
    head_sha: str
    workflow_name: str

    @property
    def failed(self) -> bool:
        return self.conclusion == "failure"

    @property
    def dimensions(self) -> dict[str, str]:
        """Pull the matrix axes out of the job name.

        Podman names these jobs "<test> <mode> <priv> <distro>", and uploads logs under the same
        shape, so the axes are already there and do not need to be recovered from the log body.
        "only fails rootless on rawhide" is often the entire diagnosis, and it is available before
        anything reads a single line of output.
        """
        parts = self.name.split()
        keys = ("test", "mode", "priv", "distro")
        return {k: v for k, v in zip(keys, parts) if v}


@dataclass
class Flake:
    """A job failure believed to be a flake, with the evidence for that belief."""

    job_id: int
    run_id: int
    run_attempt: int
    job_name: str
    head_sha: str
    html_url: str
    detected_by: str           # which rule decided this was a flake
    failed_at: str
    excerpt: str = ""          # the reduced log, not the whole thing
    verdict: Verdict | None = None

    @property
    def dimensions(self) -> dict[str, str]:
        parts = self.job_name.split()
        keys = ("test", "mode", "priv", "distro")
        return {k: v for k, v in zip(keys, parts) if v}


@dataclass
class Verdict:
    """What the classifier concluded.

    `confidence` and the option to answer UNKNOWN both exist for the same reason. A tool that is
    confidently wrong three times stops being read, and after that it does not matter how good the
    fourth answer is.
    """

    category: Category
    confidence: float          # 0.0 to 1.0
    summary: str               # one plain-English sentence
    suggestion: str = ""       # what a maintainer might do about it
    classifier: str = ""       # which backend produced this
    evidence: list[str] = field(default_factory=list)   # lines that drove the decision

    def __post_init__(self) -> None:
        self.confidence = max(0.0, min(1.0, float(self.confidence)))
