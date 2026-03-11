"""Optional observability for FTL.

Langfuse tracing:
    Activated automatically when LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY
    are present in the environment (via ftl auth or export).
    Traces every litellm.completion() call — tester, diff review, Q&A.
    Does NOT trace Claude Code internals (subprocess).

    ftl auth LANGFUSE_PUBLIC_KEY pk-lf-...
    ftl auth LANGFUSE_SECRET_KEY sk-lf-...

Agent heartbeat:
    Prints elapsed seconds while waiting for the first byte of agent output,
    so a 15-second Claude Code cold start doesn't look like a hang.
"""

import os
import threading
from ftl.ui import StatusPulse


def setup_langfuse():
    """Enable Langfuse tracing for all LiteLLM calls if credentials are set.

    Returns True if Langfuse was activated, False otherwise.
    """
    if not (os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY")):
        return False
    try:
        import litellm
        litellm.success_callback = ["langfuse"]
        litellm.failure_callback = ["langfuse"]
        return True
    except Exception:
        return False

class AgentHeartbeat:
    """Prints elapsed seconds in-place while waiting for first agent output.

    Stops silently the moment the agent produces its first line.

        heartbeat = AgentHeartbeat(console)
        heartbeat.start()
        for line in agent_output:
            heartbeat.stop()   # stops on first line
            console.print(line)
    """

    def __init__(self, console):
        self.console = console
        self._stop = threading.Event()
        self._pulse = StatusPulse(console, "thinking")

    def start(self):
        self._stop.clear()
        self._pulse.start()

    def stop(self):
        """Call on first agent output line — no-op if already stopped."""
        if not self._stop.is_set():
            self._stop.set()
            self._pulse.stop(detail="agent responding")
