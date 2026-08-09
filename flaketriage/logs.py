"""Turn a job log into something worth reading.

A failed Podman job log runs to tens of thousands of lines. Handing that to a model is expensive,
slow, and worse than handing it a hundred good lines, because the interesting part gets buried in
setup noise and the model starts explaining the package manager.

Podman already solves the same problem for its step summaries in hack/ci/github_log_summary.py,
which walks the Ginkgo HTML and keeps only the failed blocks. That parser works on the HTML
artifact. This one works on the plain-text job log from the API, which is what you have before you
have downloaded anything.
"""

from __future__ import annotations

import re

ANSI = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")

# GitHub prefixes every line of an API-fetched log with an ISO timestamp.
TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z\s?")

# Two tiers, and the distinction matters more than it looks.
#
# Tier one says what failed. Tier two only says that something did: GitHub appends
# "##[error]Process completed with exit code 2" at the very end of a failed job, after the
# post-steps have run, so anchoring on it lands the excerpt in artifact-upload boilerplate and the
# actual test failure is a thousand lines further up. Found that against real Podman logs, where
# every excerpt came back full of "Finished uploading artifact content to blob storage".
#
# So: use tier two only when no tier-one marker exists anywhere in the log.
TEST_MARKERS = (
    "Summarizing ",          # Ginkgo's end-of-run failure summary
    "[FAILED]",
    "FAIL!",
    "--- FAIL",              # go test
    "not ok ",               # BATS
    "panic:",
)

JOB_MARKERS = (
    "##[error]",
    "Error: ",
)

FAILURE_MARKERS = TEST_MARKERS + JOB_MARKERS

DEFAULT_CONTEXT_LINES = 60
DEFAULT_MAX_CHARS = 6000


def clean(line: str) -> str:
    return ANSI.sub("", TIMESTAMP.sub("", line)).rstrip()


def reduce_log(
    raw: str,
    context_lines: int = DEFAULT_CONTEXT_LINES,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> str:
    """Cut a job log down to the part that explains the failure.

    Falls back to the tail of the log when no marker is found. The tail is usually still the
    failure, and returning something imperfect beats returning nothing and forcing whoever is
    reading to open the run in a browser.
    """
    lines = [clean(line) for line in raw.splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        return ""

    anchor = _last_marker_index(lines)
    if anchor is None:
        excerpt = lines[-context_lines:]
    else:
        # Weighted towards what came before the marker. The cause is above the complaint.
        start = max(0, anchor - context_lines)
        end = min(len(lines), anchor + context_lines // 3)
        excerpt = lines[start:end]

    text = "\n".join(excerpt)
    if len(text) > max_chars:
        # Keep the end. The marker sits near it and that is the part being explained.
        text = "...\n" + text[-max_chars:]
    return text


def _last_marker_index(lines: list[str]) -> int | None:
    """Last line carrying the most informative kind of marker present."""
    for markers in (TEST_MARKERS, JOB_MARKERS):
        for i in range(len(lines) - 1, -1, -1):
            if any(marker in lines[i] for marker in markers):
                return i
    return None


def signal_lines(excerpt: str, limit: int = 5) -> list[str]:
    """The lines a human would point at when asked why it failed.

    Used as evidence on a verdict, so a maintainer can check the classifier's reasoning without
    opening the full log.
    """
    hits = [line.strip() for line in excerpt.splitlines()
            if any(marker in line for marker in FAILURE_MARKERS)]
    seen: set[str] = set()
    unique = []
    for line in hits:
        if line not in seen:
            seen.add(line)
            unique.append(line)
    return unique[:limit]
