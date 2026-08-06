"""The model backend is tested through a fake transport.

Every one of these cases is a way the model misbehaves. That is the point: the interesting
question is not whether it works when the model answers correctly, it is what the pipeline does
on the other days.
"""

import json

from flaketriage.classify.ollama import OllamaClassifier
from flaketriage.models import Category, Flake


def flake(excerpt: str = "Error: connection reset by peer") -> Flake:
    return Flake(job_id=1, run_id=1, run_attempt=1,
                 job_name="int local root fedora-current", head_sha="aaa", html_url="",
                 detected_by="rerun-passed", failed_at="2026-08-06T10:00:00Z", excerpt=excerpt)


def responding(content) -> callable:
    payload = content if isinstance(content, str) else json.dumps(content)
    return lambda url, body: json.dumps({"message": {"content": payload}}).encode()


def test_a_well_formed_answer_is_used():
    post = responding({"category": "timing", "confidence": 0.7,
                       "summary": "container was polled before it was up",
                       "suggestion": "wait on readiness instead of sleeping"})
    verdict = OllamaClassifier(post=post).classify(flake())

    assert verdict.category is Category.TIMING
    assert verdict.confidence == 0.7
    assert verdict.classifier == "ollama"


def test_an_invented_category_falls_back():
    # The model is free to be creative. The pipeline is not.
    post = responding({"category": "cosmic rays", "confidence": 0.9, "summary": "sunspots"})
    verdict = OllamaClassifier(post=post).classify(flake())

    assert verdict.category is Category.NETWORK, "should land on the heuristic's answer"
    assert "fell back" in verdict.classifier


def test_prose_instead_of_json_falls_back():
    post = responding("Sure! Here's my analysis: this looks like a network issue.")
    verdict = OllamaClassifier(post=post).classify(flake())
    assert "fell back" in verdict.classifier
    assert verdict.category is Category.NETWORK


def test_an_unreachable_model_falls_back():
    def broken(url, body):
        raise ConnectionRefusedError("ollama is not running")

    verdict = OllamaClassifier(post=broken).classify(flake())
    assert verdict.category is Category.NETWORK
    assert "model unavailable" in verdict.classifier


def test_an_empty_summary_is_not_accepted():
    # A category with no explanation is not usable in a report, so treat it as a failed answer.
    post = responding({"category": "infra", "confidence": 0.9, "summary": "   "})
    verdict = OllamaClassifier(post=post).classify(flake())
    assert "fell back" in verdict.classifier


def test_confidence_outside_the_range_is_clamped():
    post = responding({"category": "infra", "confidence": 42, "summary": "runner died"})
    verdict = OllamaClassifier(post=post).classify(flake())
    assert verdict.confidence == 1.0


def test_no_excerpt_never_reaches_the_model():
    def explode(url, body):
        raise AssertionError("should not call the model with nothing to classify")

    verdict = OllamaClassifier(post=explode).classify(flake(excerpt=""))
    assert verdict.category is Category.UNKNOWN


def test_the_prompt_carries_the_matrix_dimensions():
    seen = {}

    def capture(url, body):
        seen["body"] = json.loads(body)
        return json.dumps({"message": {"content": json.dumps(
            {"category": "environment", "confidence": 0.6, "summary": "rawhide only"})}}).encode()

    OllamaClassifier(post=capture).classify(flake())

    user_message = seen["body"]["messages"][-1]["content"]
    assert "priv=root" in user_message
    assert "distro=fedora-current" in user_message
    assert seen["body"]["format"] == "json"
    assert seen["body"]["options"]["temperature"] == 0
