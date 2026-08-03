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

# Ordered by how much they usually mean. The last match wins, because a job that fails, retries
# something, and fails again should be read at its final failure.
FAILURE_MARKERS = (
    "##[error]",
    "Summarizing ",          # Ginkgo's end-of-run failure summary
    "[FAILED]",
    "FAIL!",
    "--- FAIL",              # go test
    "not ok ",               # BATS
    "Error: ",
)

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
    for i in range(len(lines) - 1, -1, -1):
        if any(marker in lines[i] for marker in FAILURE_MARKERS):
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
