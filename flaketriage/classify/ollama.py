"""Local model backend, talking to Ollama over HTTP.

Local rather than hosted, for three reasons that all matter for this particular tool. CI logs
carry hostnames, paths and occasionally things nobody meant to print, and not shipping them to a
third party avoids that conversation entirely. A classifier that runs on every failed job in a
40-job matrix would be metered, and cost pressure is how a useful tool quietly gets switched off.
And a maintainer can run it without asking anyone for a key.

The contract with the model is the important part of this file, not the prompt. The model is asked
for one JSON object with a fixed shape. Anything else, including a valid-looking answer with an
invented category, falls back to the heuristic. This is the same discipline I ended up needing on
AstraMail: the model is a component that can fail, and the product has to keep working when it
does.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable

from ..models import Category, Flake, Verdict
from .heuristic import HeuristicClassifier

DEFAULT_HOST = "http://localhost:11434"
DEFAULT_MODEL = "llama3.1:8b"

SYSTEM_PROMPT = """You categorise CI job failures for the Podman project.

Answer with a single JSON object and nothing else:
{"category": "...", "confidence": 0.0-1.0, "summary": "...", "suggestion": "..."}

category must be exactly one of:
  infra       - the runner, the image pull, the container daemon. Not the test.
  network     - a timeout, reset or DNS failure reaching something external.
  timing      - a race, an ordering assumption, or a wait that was too short.
  resource    - out of disk, memory, file descriptors or similar.
  environment - fails only on a specific distro, privilege level or mode.
  real        - looks like a genuine bug in the code under test.
  unknown     - the log does not say enough to tell.

Rules:
- Prefer unknown over a confident guess. Being wrong costs more than being unhelpful.
- summary is one sentence, plain English, no restating the log.
- suggestion is what a maintainer might actually do next, or "" if you have nothing useful.
"""


class OllamaClassifier:
    name = "ollama"

    def __init__(self, host: str = DEFAULT_HOST, model: str = DEFAULT_MODEL,
                 post: Callable[[str, bytes], bytes] | None = None,
                 fallback=None) -> None:
        self.host = host.rstrip("/")
        self.model = model
        self._post = post or _http_post
        self._fallback = fallback or HeuristicClassifier()

    def classify(self, flake: Flake) -> Verdict:
        if not flake.excerpt.strip():
            return self._fallback.classify(flake)

        try:
            raw = self._post(f"{self.host}/api/chat", self._payload(flake))
            verdict = self._parse(raw)
        except Exception:
            # Model unreachable, slow, or talking nonsense. The pipeline continues either way,
            # because a failed classification must not lose the flake record itself.
            return self._degrade(flake, "model unavailable")

        if verdict is None:
            return self._degrade(flake, "model returned an unusable answer")
        return verdict

    def _payload(self, flake: Flake) -> bytes:
        dims = ", ".join(f"{k}={v}" for k, v in flake.dimensions.items()) or "unknown"
        user = (
            f"Job: {flake.job_name}\n"
            f"Matrix: {dims}\n"
            f"Detected as a flake by: {flake.detected_by}\n\n"
            f"Failure excerpt:\n{flake.excerpt}"
        )
        return json.dumps({
            "model": self.model,
            "stream": False,
            # Ollama can enforce JSON at the decoder, which removes most of the ways this goes
            # wrong before any parsing happens.
            "format": "json",
            "options": {"temperature": 0},
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user},
            ],
        }).encode()

    def _parse(self, raw: bytes) -> Verdict | None:
        try:
            content = json.loads(raw)["message"]["content"]
            data = json.loads(content)
            category = Category(str(data["category"]).strip().lower())
        except (KeyError, ValueError, TypeError, json.JSONDecodeError):
            return None

        summary = str(data.get("summary", "")).strip()
        if not summary:
            return None

        return Verdict(
            category=category,
            confidence=float(data.get("confidence", 0.5) or 0.5),
            summary=summary,
            suggestion=str(data.get("suggestion", "")).strip(),
            classifier=self.name,
        )

    def _degrade(self, flake: Flake, reason: str) -> Verdict:
        verdict = self._fallback.classify(flake)
        verdict.classifier = f"{self._fallback.name} (fell back: {reason})"
        return verdict


def _http_post(url: str, body: bytes) -> bytes:
    request = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()
