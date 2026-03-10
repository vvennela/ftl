from ftl.agents.claude_code import ClaudeCodeAgent
from ftl.agents.codex import CodexAgent


class FakeSandbox:
    def __init__(self):
        self.calls = []

    def exec(self, command, timeout=3600):
        self.calls.append(("exec", command, timeout))
        return 0, "", ""

    def exec_stream(self, command, callback=None, timeout=3600):
        self.calls.append(("exec_stream", command, timeout))
        if callback is not None:
            callback("done\n")
        return 0, "done\n", ""


def test_codex_follow_up_includes_session_context():
    sandbox = FakeSandbox()
    agent = CodexAgent()

    agent.continue_run(
        "Add validation for blank email addresses.",
        "/workspace",
        sandbox,
        context={
            "history": [
                "Build a login form.",
                "Add password reset support.",
            ],
            "diff_text": "--- MODIFIED: app.py ---\n+ validate_email(value)\n",
        },
    )

    _, command, _ = sandbox.calls[0]
    assert "codex exec" in command
    assert "Prior instructions in this session" in command
    assert "Build a login form." in command
    assert "Current unmerged workspace diff" in command
    assert "validate_email(value)" in command
    assert "Add validation for blank email addresses." in command


def test_agent_capabilities_and_warmup_commands():
    claude = ClaudeCodeAgent()
    codex = CodexAgent()

    assert claude.supports_continue is True
    assert claude.supports_structured_stream is True
    assert claude.warmup_command() == "claude --version"
    assert "/home/ftl/.claude/" in claude.persistent_state_paths

    assert codex.supports_continue is False
    assert codex.supports_structured_stream is False
    assert codex.warmup_command() == "codex --version"
    assert "/home/ftl/.codex/" in codex.persistent_state_paths


def test_codex_bootstraps_login_from_openai_api_key():
    sandbox = FakeSandbox()
    agent = CodexAgent()

    agent.setup_sandbox(sandbox)

    mode, command, timeout = sandbox.calls[0]
    assert mode == "exec"
    assert "codex login --with-api-key" in command
    assert "OPENAI_API_KEY" in command
    assert timeout == 120
