"""Rich terminal renderer for Claude Code's stream-json output.

Parses newline-delimited JSON events from `claude -p --output-format stream-json`
and displays per-tool progress with live elapsed-second counters, matching
the look of Claude Code's own interactive UI.
"""

import json
import sys
import threading
import time


class AgentRenderer:
    """Parses stream-json lines and renders per-tool status with timers.

    Usage:
        renderer = AgentRenderer(console)
        sandbox.exec_stream(cmd, callback=renderer.feed)
        renderer.finish()
    """

    def __init__(self, console, trace_id=None):
        self.console = console
        self._active = None  # {label, t0, stop, thread}
        self._trace_id = trace_id

    def feed(self, line):
        """Process one raw output line from the agent."""
        line = line.rstrip("\n")
        if not line:
            return
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            # Non-JSON line (e.g. agent stderr) — print directly
            self._finish_tool()
            self.console.print(line, highlight=False)
            return
        self._handle(event)

    def _handle(self, event):
        t = event.get("type")

        if t == "assistant":
            for block in event.get("message", {}).get("content", []):
                bt = block.get("type")
                if bt == "text":
                    text = block.get("text", "")
                    if text.strip():
                        self._finish_tool()
                        self.console.print(text, highlight=False, end="")
                elif bt == "tool_use":
                    self._finish_tool()
                    self._start_tool(block)
                # thinking blocks: silently skip

        elif t in ("tool", "result"):
            self._finish_tool()

    def _label(self, block):
        """Derive a human-readable label from a tool_use block."""
        name = block.get("name", "")
        inp = block.get("input", {})
        detail = next(
            (str(inp[k]) for k in ("file_path", "path", "command", "query", "pattern", "glob") if inp.get(k)),
            "",
        )
        if len(detail) > 60:
            detail = "…" + detail[-59:]
        return f"{name}: {detail}" if detail else name

    def _start_tool(self, block):
        label = self._label(block)
        stop = threading.Event()
        t0 = time.time()

        def _tick():
            while not stop.wait(timeout=1):
                elapsed = int(time.time() - t0)
                sys.stdout.write(f"\r  ◆ {label}  {elapsed}s")
                sys.stdout.flush()

        thread = threading.Thread(target=_tick, daemon=True)
        thread.start()
        self._active = {"label": label, "t0": t0, "stop": stop}

    def _finish_tool(self):
        if not self._active:
            return
        self._active["stop"].set()
        elapsed = time.time() - self._active["t0"]
        sys.stdout.write("\r\033[K")  # erase the live-counter line
        sys.stdout.flush()
        self.console.print(f"  [dim]◆ {self._active['label']}  {elapsed:.1f}s[/dim]")
        if self._trace_id:
            from ftl import cloudwatch
            cloudwatch.emit(self._trace_id, "tool", self._active["label"],
                            elapsed_ms=elapsed * 1000)
        self._active = None

    def finish(self):
        """Call after exec_stream returns to clean up any open tool state."""
        self._finish_tool()
