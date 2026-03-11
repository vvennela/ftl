"""Terminal UI helpers for FTL's status feedback."""

import threading
import time
import re


_HEX_RE = re.compile(r"^#?([0-9a-fA-F]{6})$")


def _hex_to_rgb(value):
    match = _HEX_RE.match(value)
    if not match:
        raise ValueError(f"Invalid hex color: {value!r}")
    raw = match.group(1)
    return tuple(int(raw[i:i + 2], 16) for i in (0, 2, 4))


def _ansi_rgb(rgb):
    r, g, b = rgb
    return f"\033[38;2;{r};{g};{b}m"


def _blend(a, b, t):
    return tuple(int(x + (y - x) * t) for x, y in zip(a, b))


PALETTE = {
    "snapshot": {"base": "#f59e0b", "accent": "#fde68a", "icon": "◌"},
    "boot": {"base": "#38bdf8", "accent": "#bae6fd", "icon": "◌"},
    "thinking": {"base": "#a78bfa", "accent": "#ddd6fe", "icon": "◌"},
    "checking": {"base": "#34d399", "accent": "#a7f3d0", "icon": "◌"},
    "decide": {"base": "#f472b6", "accent": "#fbcfe8", "icon": "◌"},
    "ready": {"base": "#34d399", "accent": "#d1fae5", "icon": "●"},
    "warning": {"base": "#f59e0b", "accent": "#fde68a", "icon": "●"},
    "blocked": {"base": "#fb7185", "accent": "#fecdd3", "icon": "●"},
    "done": {"base": "#60a5fa", "accent": "#dbeafe", "icon": "●"},
}


def phase_label(name):
    return {
        "snapshot": "Snapshotting",
        "boot": "Booting",
        "thinking": "Thinking",
        "checking": "Checking",
        "decide": "Decide",
    }[name]


class StatusPulse:
    """Animate a single status line while a phase is active."""

    def __init__(self, console, phase):
        self.console = console
        self.phase = phase
        self._stop = threading.Event()
        self._thread = None
        self._t0 = None
        self._rendered = False
        self._tty = bool(getattr(console.file, "isatty", lambda: False)())

    def start(self):
        self._t0 = time.time()
        if not self._tty:
            self.console.print(f"[bold]{phase_label(self.phase)}...[/bold]")
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self, outcome="done", detail=""):
        elapsed = time.time() - self._t0 if self._t0 else 0
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=0.2)
        if not self._tty:
            suffix = f"  {detail}" if detail else ""
            self.console.print(f"[bold]{phase_label(self.phase)}[/bold]  [dim]{elapsed:.1f}s{suffix}[/dim]")
            return elapsed
        self._write_final(outcome, elapsed, detail)
        return elapsed

    def _run(self):
        frame = 0
        while not self._stop.wait(timeout=0.09):
            self._write(self._animated_line(frame))
            frame += 1

    def _animated_line(self, frame):
        spec = PALETTE[self.phase]
        base = _hex_to_rgb(spec["base"])
        accent = _hex_to_rgb(spec["accent"])
        icon = spec["icon"]
        label = phase_label(self.phase)
        parts = [f"{_ansi_rgb(base)}{icon}\033[0m "]
        for idx, char in enumerate(label):
            if char == " ":
                parts.append(char)
                continue
            wave = (idx + frame) % 6
            t = 0.2 if wave in (0, 5) else 0.55 if wave in (1, 4) else 1.0
            rgb = _blend(base, accent, t)
            weight = "\033[1m" if wave in (2, 3) else ""
            parts.append(f"{weight}{_ansi_rgb(rgb)}{char}\033[0m")
        return "".join(parts)

    def _write_final(self, outcome, elapsed, detail):
        spec = PALETTE[outcome]
        label = phase_label(self.phase)
        detail_text = f"  {detail}" if detail else ""
        text = (
            f"{_ansi_rgb(_hex_to_rgb(spec['base']))}{spec['icon']}\033[0m "
            f"{_ansi_rgb(_hex_to_rgb(spec['accent']))}{label}\033[0m"
            f"  \033[2m{elapsed:.1f}s{detail_text}\033[0m"
        )
        self._write(text, final=True)

    def _write(self, text, final=False):
        if not self._tty:
            return
        file = self.console.file
        file.write("\r\033[2K" + text)
        file.flush()
        if final:
            file.write("\n")
            file.flush()


def print_verdict(console, verdict, message):
    """Print a short final verdict line with the shared palette."""
    spec = PALETTE[verdict]
    if getattr(console.file, "isatty", lambda: False)():
        rgb = _ansi_rgb(_hex_to_rgb(spec["base"]))
        accent = _ansi_rgb(_hex_to_rgb(spec["accent"]))
        console.file.write(f"{rgb}{spec['icon']}\033[0m {accent}{message}\033[0m\n")
        console.file.flush()
    else:
        console.print(f"[bold]{message}[/bold]")
