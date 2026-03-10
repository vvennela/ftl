from types import SimpleNamespace

from ftl import planner


def test_generate_tests_prompt_requests_broader_coverage(monkeypatch):
    captured = {}

    def fake_completion(model, messages):
        captured["messages"] = messages
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="print('ok')"))])

    monkeypatch.setattr(planner.litellm, "completion", fake_completion)

    planner.generate_tests_from_task("build a login form", "test-model")

    system = captured["messages"][0]["content"]
    assert "idempotency" in system
    assert "permission/auth behavior" in system
    assert "regression checks" in system


def test_run_verification_prompt_requests_failure_recovery(monkeypatch):
    captured = {}

    def fake_completion(model, messages):
        captured["messages"] = messages
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="print('ok')"))])

    monkeypatch.setattr(planner.litellm, "completion", fake_completion)
    monkeypatch.setattr(planner, "run_test_code", lambda code, sandbox, console: (0, "ok"))

    planner.run_verification(
        [{"path": "x.py", "status": "created", "lines": [("+", "print('x')")]}],
        "test-model",
        sandbox=object(),
    )

    system = captured["messages"][0]["content"]
    assert "failure recovery" in system
    assert "idempotency" in system
