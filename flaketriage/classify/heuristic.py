"""Pattern-matching classifier. No model, no key, no network.

This is not a fallback in the apologetic sense. It is the baseline the model has to beat, and
without a baseline there is no way to say whether the model is earning its cost. It also runs in
CI, where calling a paid API on every push is not reasonable.

It is deliberately conservative. When nothing matches it says UNKNOWN instead of picking the
nearest category, because the number that matters for trust is how often the tool is confidently
wrong, not how often it answers.
"""

from __future__ import annotations

import re

from ..logs import signal_lines
from ..models import Category, Flake, Verdict

# Ordered. The first match wins, so the more specific and more actionable patterns come first.
RULES: list[tuple[Category, float, str, str, tuple[str, ...]]] = [
    (
        Category.RESOURCE, 0.85,
        "the runner ran out of a resource",
        "Check disk and memory headroom on the runner, and whether the job leaks containers.",
        ("no space left on device", "cannot allocate memory", "out of memory", "oom-killed",
         "too many open files", "no such file or directory: /proc", "inotify"),
    ),
    (
        Category.NETWORK, 0.8,
        "a network call failed or timed out",
        "Usually the registry or a package mirror. Worth a retry with backoff around the pull.",
        ("connection reset by peer", "connection refused", "i/o timeout", "no route to host",
         "temporary failure in name resolution", "tls handshake timeout", "dial tcp",
         "could not resolve host", "502 bad gateway", "503 service unavailable"),
    ),
    (
        Category.INFRA, 0.75,
        "the runner or the container environment failed, not the test",
        "Infrastructure rather than code. Re-run is the right response.",
        ("the runner has received a shutdown signal", "the operation was canceled",
         "failed to pull image", "manifest unknown", "error response from daemon",
         "systemd", "dbus", "cgroup"),
    ),
    (
        Category.TIMING, 0.7,
        "looks like a race or a wait that was too short",
        "Look for a fixed sleep or a poll without a deadline near the failing assertion.",
        ("timed out waiting", "context deadline exceeded", "deadlock", "data race",
         "timeout waiting for", "still running after", "eventually failed", "race detected"),
    ),
]

# Checked before the rules above. A compile or vet failure is not a flake at all, and letting it
# be labelled as one is how a real regression gets ignored.
REAL_MARKERS = (
    "cannot use ", "undefined:", "syntax error", "build failed",
    "expected 0 to equal", "expected error to be nil",
)

WORD = re.compile(r"[a-z0-9._/-]+")


class HeuristicClassifier:
    name = "heuristic"

    def classify(self, flake: Flake) -> Verdict:
        text = flake.excerpt.lower()
        if not text.strip():
            return Verdict(
                category=Category.UNKNOWN, confidence=0.0,
                summary="no log excerpt was available for this job",
                suggestion="The log may have aged out of retention.",
                classifier=self.name,
            )

        for category, confidence, summary, suggestion, needles in RULES:
            hit = next((n for n in needles if n in text), None)
            if hit:
                return Verdict(
                    category=category, confidence=confidence, summary=summary,
                    suggestion=suggestion, classifier=self.name,
                    evidence=_evidence(flake.excerpt, hit),
                )

        if any(marker in text for marker in REAL_MARKERS):
            return Verdict(
                category=Category.REAL, confidence=0.5,
                summary="reads like an assertion or build failure rather than an environment problem",
                suggestion="Worth a human look before writing this off as a flake.",
                classifier=self.name, evidence=signal_lines(flake.excerpt),
            )

        return Verdict(
            category=Category.UNKNOWN, confidence=0.0,
            summary="no known pattern matched this failure",
            suggestion="Needs a human, or a model with more context than pattern matching.",
            classifier=self.name, evidence=signal_lines(flake.excerpt),
        )


def _evidence(excerpt: str, needle: str) -> list[str]:
    """The actual lines that triggered the match, so the reasoning can be checked."""
    hits = [line.strip() for line in excerpt.splitlines() if needle in line.lower()]
    return hits[:3] or signal_lines(excerpt, limit=3)
