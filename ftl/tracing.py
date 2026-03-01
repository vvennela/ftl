"""Optional observability for FTL.

Langfuse tracing:
    Activated automatically when LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY
    are present in the environment (via ftl auth or export).
    Traces every litellm.completion() call — tester, diff review, Q&A.
    Does NOT trace Claude Code internals (subprocess).

    ftl auth LANGFUSE_PUBLIC_KEY pk-lf-...
    ftl auth LANGFUSE_SECRET_KEY sk-lf-...

Stage timing:
    StageTimer wraps orchestrator stages and prints elapsed time after each.
    Always on — no config needed.

Agent heartbeat:
    Prints elapsed seconds while waiting for the first byte of agent output,
    so a 15-second Claude Code cold start doesn't look like a hang.
"""

import os
import threading
import time


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


class StageTimer:
    """Prints elapsed wall-clock time after each named stage.

    Usage:
        t = StageTimer(console)
        do_snapshot()
        t.mark("snapshot")      # prints "  snapshot  0.8s"
        do_boot()
        t.mark("boot")          # prints "  boot  0.2s"
    """

    def __init__(self, console):
        self.console = console
        self._stage_start = time.time()

    def mark(self, label):
        elapsed = time.time() - self._stage_start
        self._stage_start = time.time()
        self.console.print(f"  [dim]{label}  {elapsed:.1f}s[/dim]")
        return elapsed


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
        self._thread = None
        self._t0 = None

    def start(self):
        self._t0 = time.time()
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        """Call on first agent output line — no-op if already stopped."""
        self._stop.set()

    def _run(self):
        interval = 5
        while not self._stop.wait(timeout=interval):
            elapsed = int(time.time() - self._t0)
            self.console.print(
                f"  [dim]waiting for agent...  {elapsed}s[/dim]",
                highlight=False,
            )
