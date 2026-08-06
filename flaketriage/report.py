"""Turn stored verdicts into something a maintainer will actually read.

The reporting layer is where tools like this usually die. Categorising correctly and then emitting
one issue per occurrence produces forty issues about the same registry timeout, and the next
response is to mute the bot. So the grouping happens here, and the dimensions do most of the work:
"12 times this week, always rootless, always rawhide" is a diagnosis. "12 flakes" is noise.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable

from .models import Category, Flake


def signature(flake: Flake) -> str:
    """A stable key for 'the same flake happening again'.

    Category plus test type, rather than the full job name. Including the distro would split one
    problem into four issues, and whether it is distro-specific is exactly what the report should
    be telling you rather than assuming.
    """
    category = flake.verdict.category.value if flake.verdict else "unclassified"
    test = flake.dimensions.get("test", "unknown")
    return f"{category}:{test}"


def group(flakes: Iterable[Flake]) -> dict[str, list[Flake]]:
    grouped: dict[str, list[Flake]] = defaultdict(list)
    for flake in flakes:
        grouped[signature(flake)].append(flake)
    return dict(sorted(grouped.items(), key=lambda kv: len(kv[1]), reverse=True))


def _dimension_note(flakes: list[Flake]) -> str:
    """Say something only when a dimension is actually concentrated."""
    notes = []
    for axis in ("distro", "priv", "mode"):
        values = Counter(f.dimensions.get(axis) for f in flakes if f.dimensions.get(axis))
        if not values:
            continue
        value, count = values.most_common(1)[0]
        if count == len(flakes) and len(flakes) > 1:
            notes.append(f"always {value}")
        elif count / len(flakes) >= 0.8 and len(flakes) > 2:
            notes.append(f"mostly {value} ({count}/{len(flakes)})")
    return ", ".join(notes)


def weekly_digest(flakes: list[Flake], repo: str = "") -> str:
    """A markdown summary, ordered by how often each thing happened."""
    if not flakes:
        return "# CI flake report\n\nNo flakes recorded in this window.\n"

    grouped = group(flakes)
    real = [f for f in flakes if f.verdict and f.verdict.category is Category.REAL]
    unknown = [f for f in flakes if f.verdict and f.verdict.category is Category.UNKNOWN]

    lines = ["# CI flake report", ""]
    lines.append(f"{len(flakes)} flaky job failures across {len(grouped)} distinct signatures"
                 + (f" in `{repo}`" if repo else "") + ".")
    lines.append("")

    if real:
        # Surfaced first and separately. A real failure mislabelled as a flake is the one outcome
        # that actively costs something, so it should not be buried in a list of retries.
        lines.append(f"**{len(real)} of these may not be flakes at all** and are worth a look "
                     "before they get written off.")
        lines.append("")

    lines.append("| count | category | test | pattern | example |")
    lines.append("|---|---|---|---|---|")
    for sig, items in grouped.items():
        category, test = sig.split(":", 1)
        note = _dimension_note(items) or "no clear pattern"
        lines.append(f"| {len(items)} | {category} | {test} | {note} | [run]({items[0].html_url}) |")
    lines.append("")

    for sig, items in grouped.items():
        first = items[0]
        if not first.verdict:
            continue
        lines.append(f"### {sig} ({len(items)})")
        lines.append(f"{first.verdict.summary}")
        if first.verdict.suggestion:
            lines.append(f"Suggested: {first.verdict.suggestion}")
        note = _dimension_note(items)
        if note:
            lines.append(f"Pattern: {note}")
        lines.append("")

    if unknown:
        lines.append(f"_{len(unknown)} failures could not be categorised and are excluded from the "
                     "analysis above._")

    return "\n".join(lines) + "\n"


def issue_body(signature_key: str, flakes: list[Flake]) -> str:
    """The body for one auto-filed issue, covering every occurrence of one signature."""
    first = flakes[0]
    verdict = first.verdict

    lines = [
        f"Seen **{len(flakes)} times**. Filed automatically by flaketriage.",
        "",
    ]
    if verdict:
        lines += [f"**Category:** {verdict.category.value} "
                  f"(confidence {verdict.confidence:.0%}, via {verdict.classifier})",
                  "", verdict.summary, ""]
        if verdict.suggestion:
            lines += [f"**Suggested next step:** {verdict.suggestion}", ""]

    note = _dimension_note(flakes)
    if note:
        lines += [f"**Pattern:** {note}", ""]

    lines.append("**Occurrences**")
    for flake in flakes[:10]:
        lines.append(f"- [{flake.job_name}]({flake.html_url}) at {flake.failed_at} "
                     f"(`{flake.head_sha[:8]}`, detected by {flake.detected_by})")
    if len(flakes) > 10:
        lines.append(f"- ...and {len(flakes) - 10} more")

    if verdict and verdict.evidence:
        lines += ["", "**Evidence**", "```", *verdict.evidence[:5], "```"]

    return "\n".join(lines) + "\n"


def issue_title(signature_key: str, flakes: list[Flake]) -> str:
    category, test = signature_key.split(":", 1)
    note = _dimension_note(flakes)
    suffix = f" ({note})" if note else ""
    return f"[flake] {test}: {category} failures{suffix}"
