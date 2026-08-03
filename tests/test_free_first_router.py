from __future__ import annotations

import json
import re
from pathlib import Path
from unittest import mock

from scripts import free_first_router as router


def _providers() -> tuple[router.Provider, router.Provider]:
    return (
        router.Provider("free-a", ("FREE_A_KEY",), "FREE_A_BASE", "https://a.example/v1", "FREE_A_MODELS", ("a",)),
        router.Provider("free-b", ("FREE_B_KEY",), "FREE_B_BASE", "https://b.example/v1", "FREE_B_MODELS", ("b",)),
    )


def test_first_free_429_then_next_free_success(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(router, "FREE_PROVIDERS", _providers())
    monkeypatch.setattr(router, "_request", mock.Mock(side_effect=[("", 429, 0.0), ("answer", 200, 0.0)]))
    monkeypatch.setenv("FREE_A_KEY", "a-secret")
    monkeypatch.setenv("FREE_B_KEY", "b-secret")

    output = tmp_path / "answer.md"
    metadata_path = tmp_path / "route.json"
    assert router.route("prompt", output, metadata_path, None) == 0

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert metadata["status"] == "success"
    assert metadata["paid_required"] is False
    assert metadata["attempted"] == 2
    assert metadata["prompt_sha256"] == __import__("hashlib").sha256(b"prompt").hexdigest()
    assert output.read_text(encoding="utf-8") == "answer"


def test_paid_agent_is_required_only_after_all_configured_free_attempts_are_429(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(router, "FREE_PROVIDERS", _providers())
    monkeypatch.setattr(router, "_request", mock.Mock(side_effect=[("", 429, 0.0), ("", 429, 0.0)]))
    monkeypatch.setenv("FREE_A_KEY", "a-secret")
    monkeypatch.setenv("FREE_B_KEY", "b-secret")

    output = tmp_path / "answer.md"
    metadata_path = tmp_path / "route.json"
    assert router.route("prompt", output, metadata_path, None) == 0

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert metadata["status"] == "all_free_429"
    assert metadata["paid_required"] is True
    assert not output.exists()


def test_auth_failure_never_requests_paid_agent(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(router, "FREE_PROVIDERS", _providers())
    monkeypatch.setattr(router, "_request", mock.Mock(return_value=("", 401, 0.0)))
    monkeypatch.setenv("FREE_A_KEY", "a-secret")
    monkeypatch.delenv("FREE_B_KEY", raising=False)

    metadata_path = tmp_path / "route.json"
    assert router.route("prompt", tmp_path / "answer.md", metadata_path, None) == 0

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert metadata["status"] == "auth_error"
    assert metadata["paid_required"] is False


def test_protocol_failure_is_not_treated_as_429_and_limits_are_explicit(tmp_path: Path, monkeypatch):
    providers = _providers()
    monkeypatch.setattr(router, "FREE_PROVIDERS", providers)
    request = mock.Mock(side_effect=router.FreeRouteError("protocol_error", "bad-json"))
    monkeypatch.setattr(router, "_request", request)
    monkeypatch.setenv("FREE_A_KEY", "a-secret")
    metadata_path = tmp_path / "route.json"
    assert router.route("prompt", tmp_path / "answer.md", metadata_path, None, timeout=7, max_tokens=11) == 0
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert metadata["status"] == "free_unavailable"
    assert metadata["paid_required"] is False
    request.assert_called_once_with(providers[0], "a", "prompt", timeout=7, max_tokens=11)


def test_plan_workflows_are_gated_after_the_free_route():
    router_source = (Path(__file__).parents[1] / "scripts" / "free_first_router.py").read_text(encoding="utf-8")
    assert not re.search(r"(?:CODINGPLAN|CODING_PLAN|AGENTPLAN|AGENT_PLAN|TOKENPLAN|TOKEN_PLAN)_API_KEY", router_source)

    workflow_root = Path(__file__).parents[1] / ".github" / "workflows"
    for workflow in workflow_root.glob("*.yml"):
        text = workflow.read_text(encoding="utf-8")
        for marker in ("Run Kimi Coding Plan through read-only OpenCode Agent", "Run Volcengine Plan through read-only OpenCode Agent"):
            if marker not in text:
                continue
            plan_position = text.index(marker)
            free_position = text.rfind("Run configured free endpoints first", 0, plan_position)
            assert free_position >= 0, workflow
            assert "steps.free_route.outputs.paid_required == 'true'" in text[free_position:plan_position + 500], workflow
