import shlex
from ftl.agents.base import Agent

# --full-auto: skips all approval prompts (sets ask-for-approval=on-request + sandbox=workspace-write)
# --dangerously-bypass-approvals-and-sandbox: no internal sandboxing (FTL's Docker is the sandbox)
_FLAGS = "--dangerously-bypass-approvals-and-sandbox"


class CodexAgent(Agent):
    supports_continue = False
    supports_structured_stream = False
    persistent_state_paths = ("/home/ftl/.codex/",)

    def _compose_follow_up(self, task, context=None):
        """Codex follow-ups are stateless, so restate the active session context."""
        context = context or {}
        history = context.get("history") or []
        diff_text = (context.get("diff_text") or "").strip()
        summary = []

        if history:
            summary.append("Prior instructions in this session:")
            for index, item in enumerate(history, start=1):
                summary.append(f"{index}. {item}")

        if diff_text:
            summary.append("Current unmerged workspace diff:")
            summary.append(diff_text)

        summary.append("Continue from that state and apply this instruction:")
        summary.append(task)
        return "\n\n".join(summary)

    def run(self, task, workspace, sandbox, callback=None, context=None):
        escaped = shlex.quote(task)
        cmd = f"cd {workspace} && codex exec {escaped} {_FLAGS}"
        if callback is not None:
            return sandbox.exec_stream(cmd, callback=callback, timeout=3600)
        return sandbox.exec(cmd, timeout=3600)

    def continue_run(self, task, workspace, sandbox, callback=None, context=None):
        prompt = self._compose_follow_up(task, context=context)
        return self.run(prompt, workspace, sandbox, callback=callback)

    def warmup_command(self):
        return "codex --version"

    def setup_sandbox(self, sandbox):
        """Seed Codex's own auth state from the injected API key."""
        cmd = (
            "if [ -n \"${OPENAI_API_KEY:-}\" ]; then "
            "printf '%s' \"$OPENAI_API_KEY\" | codex login --with-api-key >/dev/null 2>&1; "
            "fi"
        )
        sandbox.exec(cmd, timeout=120)
