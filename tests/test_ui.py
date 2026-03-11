import io

from rich.console import Console

from ftl.ui import StatusPulse, phase_label, print_verdict


def test_phase_label_names():
    assert phase_label("snapshot") == "Snapshotting"
    assert phase_label("boot") == "Booting"
    assert phase_label("thinking") == "Thinking"
    assert phase_label("checking") == "Checking"
    assert phase_label("decide") == "Decide"


def test_status_pulse_non_tty_fallback_prints_summary():
    stream = io.StringIO()
    console = Console(file=stream, force_terminal=False, color_system=None)
    pulse = StatusPulse(console, "snapshot")

    pulse.start()
    pulse.stop(detail="snap1234")

    output = stream.getvalue()
    assert "Snapshotting" in output
    assert "snap1234" in output


def test_print_verdict_non_tty_fallback():
    stream = io.StringIO()
    console = Console(file=stream, force_terminal=False, color_system=None)

    print_verdict(console, "ready", "Decide: ready to review")

    assert "Decide: ready to review" in stream.getvalue()
