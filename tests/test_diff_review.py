from ftl import diff as diff_mod


class FakeRenderer:
    def __init__(self, console):
        self.lines = []
        self.finished = False

    def feed(self, line):
        self.lines.append(line)

    def finish(self):
        self.finished = True


class FakeThread:
    def __init__(self, target=None, daemon=None):
        self.target = target

    def start(self):
        return None


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
            callback("review answer\n")
        return 0, "review answer\n", ""


def test_ask_about_diff_uses_selected_agent(monkeypatch):
    agent = FakeAgent()

    monkeypatch.setattr(diff_mod, "AgentRenderer", FakeRenderer)
    monkeypatch.setattr(diff_mod.threading, "Thread", FakeThread)

    diff_mod.ask_about_diff(
        "Does this handle null inputs?",
        sandbox=object(),
        workspace="/workspace",
        agent=agent,
        context={"history": ["Initial task"], "diff_text": "--- CREATED: app.py ---"},
    )

    assert len(agent.calls) == 1
    assert agent.calls[0]["task"] == "Does this handle null inputs?"
    assert agent.calls[0]["workspace"] == "/workspace"
    assert agent.calls[0]["context"]["history"] == ["Initial task"]


def test_ask_about_diff_suppresses_unreachable_warning_after_partial_output(monkeypatch):
    agent = FakeAgent()
    messages = []

    class PartialFailureAgent(FakeAgent):
        def continue_run(self, task, workspace, sandbox, callback=None, context=None):
            if callback is not None:
                callback("partial answer\n")
            raise RuntimeError("stream ended")

    monkeypatch.setattr(diff_mod, "AgentRenderer", FakeRenderer)
    monkeypatch.setattr(diff_mod.threading, "Thread", FakeThread)

    class FakeConsole:
        def print(self, message="", *args, **kwargs):
            messages.append(str(message))

    monkeypatch.setattr(diff_mod, "Console", lambda: FakeConsole())

    diff_mod.ask_about_diff(
        "Question?",
        sandbox=object(),
        workspace="/workspace",
        agent=PartialFailureAgent(),
        context={},
    )

    assert not any("Could not reach agent" in message for message in messages)


def test_review_diff_refreshes_context_after_agent_question(monkeypatch):
    asked = []
    initial = [{"path": "app.py", "status": "created", "lines": [("+", "first")]}]
    updated = [{"path": "app.py", "status": "created", "lines": [("+", "second")]}]
    context = {"history": ["Initial task"], "diff_text": diff_mod.diff_to_text(initial)}

    monkeypatch.setattr(diff_mod, "display_diff", lambda diffs: None)
    monkeypatch.setattr(
        diff_mod,
        "ask_about_diff",
        lambda question, sandbox, workspace, agent, context=None: asked.append(
            {
                "question": question,
                "agent": agent,
                "context": dict(context or {}),
            }
        ),
    )

    actions = iter(["question", "approve"])
    monkeypatch.setattr(diff_mod, "_read_review_action", lambda allow_continue=True: next(actions))
    monkeypatch.setattr(diff_mod, "_prompt_review_question", lambda: "What changed?")

    decision = diff_mod.review_diff(
        initial,
        sandbox=object(),
        workspace="/workspace",
        agent="codex-agent",
        question_context=context,
        get_diffs=lambda: updated,
    )

    assert decision == "approve"
    assert asked[0]["agent"] == "codex-agent"
    assert asked[0]["question"] == "What changed?"
    assert context["diff_text"] == diff_mod.diff_to_text(updated)


def test_review_diff_can_return_continue(monkeypatch):
    diffs = [{"path": "app.py", "status": "created", "lines": [("+", "first")]}]

    monkeypatch.setattr(diff_mod, "_read_review_action", lambda allow_continue=True: "continue")

    decision = diff_mod.review_diff(
        diffs,
        sandbox=object(),
        workspace="/workspace",
        agent="codex-agent",
    )

    assert decision == "continue"
