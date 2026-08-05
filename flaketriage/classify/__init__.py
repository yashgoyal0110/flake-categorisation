"""Classifier backends.

One interface, several implementations, chosen at runtime. The heuristic one needs no key and no
network, which is what makes this tool clonable: a maintainer can run the whole pipeline and see
real output before deciding whether they want a model involved at all.

Every backend returns the same Verdict. A backend that cannot produce one returns UNKNOWN rather
than guessing, because a wrong category stated confidently is worse than no category.
"""

from __future__ import annotations

from typing import Protocol

from ..models import Flake, Verdict


class Classifier(Protocol):
    name: str

    def classify(self, flake: Flake) -> Verdict:
        ...


def get(name: str, **kwargs) -> Classifier:
    """Resolve a backend by name. Imports are local so an unused backend costs nothing."""
    if name == "heuristic":
        from .heuristic import HeuristicClassifier
        return HeuristicClassifier()
    if name == "ollama":
        from .ollama import OllamaClassifier
        return OllamaClassifier(**kwargs)
    raise ValueError(f"unknown classifier {name!r}, expected one of: heuristic, ollama")


__all__ = ["Classifier", "Verdict", "get"]
