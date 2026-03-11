"""Terminal renderer for agent output.

Claude emits newline-delimited JSON events, while other agents may emit plain
text. This renderer normalizes both into a responsive streamed display with
tool timing updates.
"""

from collections import deque
import json
import re
import sys
import threading
import time


class TokenLagWriter:
    """Render text in a fast token-by-token stream with a small trailing lag."""

    _TOKEN_RE = re.compile(r"\S+\s*|\n")

    def __init__(self, console, lag_tokens=15, cadence=0.004):
        self.console = console
        self.lag_tokens = lag_tokens
        self.cadence = cadence
        self._buffer = deque()
        self._stream = getattr(console, "file", sys.stdout)
        self._last_char = "\n"

    def push(self, text):
        if not text:
            return
        self._buffer.extend(self._tokenize(text))
        while len(self._buffer) > self.lag_tokens:
            self._emit(self._buffer.popleft(), delay=True)

    def flush(self):
        while self._buffer:
            self._emit(self._buffer.popleft(), delay=False)

    def _emit(self, token, delay):
        self._stream.write(token)
        self._stream.flush()
        if token:
            self._last_char = token[-1]
        if delay:
            time.sleep(self.cadence)

    def _tokenize(self, text):
        tokens = self._TOKEN_RE.findall(text)
        return tokens or [text]

    @property
    def ends_on_newline(self):
        return self._last_char == "\n"


class AgentRenderer:
    """Parses stream-json lines and renders per-tool status with timers.

    Usage:
        renderer = AgentRenderer(console)
        sandbox.exec_stream(cmd, callback=renderer.feed)
        renderer.finish()
    """

    def __init__(self, console, trace_id=None, stream_lag_tokens=15, stream_cadence=0.004):
        self.console = console
        self._active = None  # {label, t0, stop, thread}
        self._trace_id = trace_id
        self._stream = getattr(console, "file", sys.stdout)
        self._text = TokenLagWriter(
            console,
            lag_tokens=stream_lag_tokens,
            cadence=stream_cadence,
        )

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
            self._text.push(line + "\n")
            return
        if not isinstance(event, dict):
            self._finish_tool()
            self._text.push(line + "\n")
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
                        self._text.push(text)
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
        self._text.flush()
        label = self._label(block)
        stop = threading.Event()
        t0 = time.time()

        def _tick():
            while not stop.wait(timeout=1):
                elapsed = int(time.time() - t0)
                self._stream.write(f"\r  ◆ {label}  {elapsed}s")
                self._stream.flush()

        thread = threading.Thread(target=_tick, daemon=True)
        thread.start()
        self._active = {"label": label, "t0": t0, "stop": stop}

    def _finish_tool(self):
        if not self._active:
            return
        self._text.flush()
        self._active["stop"].set()
        elapsed = time.time() - self._active["t0"]
        self._stream.write("\r\033[K")  # erase the live-counter line
        self._stream.flush()
        self.console.print(f"  [dim]◆ {self._active['label']}  {elapsed:.1f}s[/dim]")
        if self._trace_id:
            from ftl import cloudwatch
            cloudwatch.emit(self._trace_id, "tool", self._active["label"],
                            elapsed_ms=elapsed * 1000)
        self._active = None

    def finish(self):
        """Call after exec_stream returns to clean up any open tool state."""
        self._finish_tool()
        self._text.flush()
        if not self._text.ends_on_newline:
            self._stream.write("\n")
            self._stream.flush()
