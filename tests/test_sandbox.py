from types import SimpleNamespace

from ftl.sandbox import create_sandbox
from ftl.sandbox.docker import DockerSandbox


def test_create_sandbox_keeps_selected_agent():
    sandbox = create_sandbox(agent="codex")

    assert isinstance(sandbox, DockerSandbox)
    assert sandbox.agent_name == "codex"

def test_docker_sandbox_prewarms_selected_agent(monkeypatch):
    calls = []
    sandbox = DockerSandbox(image="image", agent_name="codex")
    sandbox.container_id = "container123"

    class FakeAgent:
        def warmup_command(self):
            return "codex --version"

    monkeypatch.setattr("ftl.agents.get_agent", lambda name: FakeAgent())
    monkeypatch.setattr(
        "ftl.sandbox.docker.subprocess.run",
        lambda cmd, capture_output=True, timeout=30: calls.append(cmd) or SimpleNamespace(returncode=0),
    )

    sandbox._prewarm_agent()

    assert calls == [["docker", "exec", "-u", "ftl", "container123", "sh", "-c", "codex --version"]]
