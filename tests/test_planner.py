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
    assert "high-signal language" in system
    assert "No filler" in system


def test_generate_tests_prompt_includes_language_specific_runtime(monkeypatch):
    captured = {}

    def fake_completion(model, messages):
        captured["messages"] = messages
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="package main"))])

    monkeypatch.setattr(planner.litellm, "completion", fake_completion)

    planner.generate_tests_from_task("build a cli", "test-model", language="go")

    system = captured["messages"][0]["content"]
    user = captured["messages"][1]["content"]
    assert "single self-contained Go validation program" in system
    assert "high-signal language" in system
    assert "Target language: go" in user


def test_run_verification_prompt_requests_failure_recovery(monkeypatch):
    captured = {}

    def fake_completion(model, messages):
        captured["messages"] = messages
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="print('ok')"))])

    monkeypatch.setattr(planner.litellm, "completion", fake_completion)
    monkeypatch.setattr(
        planner,
        "run_test_code",
        lambda code, sandbox, console, language="python", project_path=None: (0, "ok"),
    )

    planner.run_verification(
        [{"path": "x.py", "status": "created", "lines": [("+", "print('x')")]}],
        "test-model",
        sandbox=object(),
    )

    system = captured["messages"][0]["content"]
    assert "failure recovery" in system
    assert "idempotency" in system
    assert "No filler" in system


def test_run_test_code_uses_cpp_runtime(monkeypatch):
    calls = []

    class FakeSandbox:
        def exec(self, command):
            calls.append(command)
            return 0, "ok", ""

    planner.run_test_code("int main() { return 0; }", FakeSandbox(), console=SimpleNamespace(print=lambda *args, **kwargs: None), language="cpp")

    assert "/workspace/_ftl_test.cpp" in calls[0]
    assert "g++ -std=c++17" in calls[1]


def test_run_test_code_uses_single_file_java_runtime_for_maven_projects(tmp_path):
    calls = []
    (tmp_path / "pom.xml").write_text("<project />\n")

    class FakeSandbox:
        def exec(self, command):
            calls.append(command)
            return 0, "ok", ""

    planner.run_test_code(
        "class FtlGeneratedTest { public static void main(String[] args) {} }",
        FakeSandbox(),
        console=SimpleNamespace(print=lambda *args, **kwargs: None),
        language="java",
        project_path=tmp_path,
    )

    assert "/workspace/FtlGeneratedTest.java" in calls[0]
    assert "java ./FtlGeneratedTest.java" in calls[1]
