import io

from rich.console import Console

from ftl.orchestrator import Session


class FakeRenderer:
    def __init__(self, console, trace_id=None):
        self.lines = []
        self.finished = False

    def feed(self, line):
        self.lines.append(line)

    def finish(self):
        self.finished = True


class FakeAgent:
    def __init__(self):
        self.calls = []

    def continue_run(self, task, workspace, sandbox, callback=None, context=None):
        self.calls.append({
            "task": task,
            "workspace": workspace,
            "sandbox": sandbox,
            "context": context,
        })
        if callback is not None:
            callback("agent output\n")
        return 0, "agent output\n", ""


def test_session_follow_up_passes_agent_context(monkeypatch):
    session = Session.__new__(Session)
    session.console = Console(file=io.StringIO(), force_terminal=False, color_system=None)
    session.trace_id = "trace1234"
    session.agent = FakeAgent()
    session.sandbox = object()
    session.workspace = "/workspace"
    session.agent_calls = 0
    session.history = ["Build a login form."]
    session.diffs = []
    session._review = {"summary": "old review"}
    session._agent_context = lambda: {
        "history": ["Build a login form."],
        "diff_text": "--- CREATED: app.py ---",
    }

    monkeypatch.setattr("ftl.orchestrator.AgentRenderer", FakeRenderer)

    Session.follow_up(session, "Add tests.")

    assert session.agent.calls[0]["task"] == "Add tests."
    assert session.agent.calls[0]["workspace"] == "/workspace"
    assert session.agent.calls[0]["context"]["diff_text"] == "--- CREATED: app.py ---"
    assert session.history == ["Build a login form.", "Add tests."]
    assert session.agent_calls == 1
    assert session.diffs is None
    assert session._review is None
