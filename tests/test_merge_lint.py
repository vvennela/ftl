import io

from rich.console import Console

from ftl.orchestrator import Session


def test_merge_blocks_unapproved_destructive_operations(monkeypatch):
    session = Session.__new__(Session)
    session.console = Console(file=io.StringIO(), force_terminal=False, color_system=None)
    session.config = {}
    session.shadow_env = {}
    session.task = "add a status endpoint"
    session.snapshot_id = "snap12345"
    session.project_path = "/tmp/project"
    session.workspace = "/workspace"
    session.sandbox = object()
    session.trace_id = "trace1234"
    session._review = None
    session._get_diffs = lambda: [{"path": "cleanup.py", "status": "created", "lines": [("+", "os.remove('x')")]}]

    cleanup_called = []
    log_entries = []

    monkeypatch.setattr(
        "ftl.orchestrator.lint_diffs",
        lambda diffs, shadow_env=None, task="": [
            type(
                "Violation",
                (),
                {
                    "blocking": True,
                    "reason": "Destructive filesystem delete: os.remove",
                    "file_path": "cleanup.py",
                    "line_num": 1,
                    "line_content": "os.remove('x')",
                },
            )()
        ],
    )
    monkeypatch.setattr("ftl.orchestrator.display_violations", lambda violations: None)
    monkeypatch.setattr("ftl.orchestrator.display_review", lambda review, console=None: None)
    monkeypatch.setattr("ftl.orchestrator.review_diff", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("review_diff should not run")))
    monkeypatch.setattr("ftl.orchestrator.write_log", lambda entry, trace_id=None: log_entries.append(entry))
    session._cleanup = lambda: cleanup_called.append(True)

    Session.merge(session)

    assert cleanup_called == [True]
    assert log_entries[0]["result"] == "rejected"


def test_merge_uses_specific_warning_message_for_destructive_lint(monkeypatch):
    stream = io.StringIO()
    session = Session.__new__(Session)
    session.console = Console(file=stream, force_terminal=False, color_system=None)
    session.config = {}
    session.shadow_env = {}
    session.task = "delete the cache file after upload completes"
    session.snapshot_id = "snap12345"
    session.project_path = "/tmp/project"
    session.workspace = "/workspace"
    session.sandbox = object()
    session.agent = object()
    session.trace_id = "trace1234"
    session._review = None
    session._get_diffs = lambda: [{"path": "cleanup.py", "status": "created", "lines": [("+", "Path('/tmp/cache').unlink()")]}]
    session._agent_context = lambda: {}

    monkeypatch.setattr(
        "ftl.orchestrator.lint_diffs",
        lambda diffs, shadow_env=None, task="": [
            type(
                "Violation",
                (),
                {
                    "blocking": False,
                    "reason": "Destructive filesystem delete: Path.unlink",
                    "file_path": "cleanup.py",
                    "line_num": 1,
                    "line_content": "Path('/tmp/cache').unlink()",
                },
            )()
        ],
    )
    monkeypatch.setattr("ftl.orchestrator.display_violations", lambda violations: None)
    monkeypatch.setattr("ftl.orchestrator.display_review", lambda review, console=None: None)
    monkeypatch.setattr("ftl.orchestrator.review_diff", lambda *args, **kwargs: False)
    monkeypatch.setattr("ftl.orchestrator.write_log", lambda entry, trace_id=None: None)
    session._cleanup = lambda: None

    Session.merge(session)

    assert "Review warning: destructive operation detected" in stream.getvalue()


def test_merge_marks_failed_tests_as_review_warning(monkeypatch):
    stream = io.StringIO()
    session = Session.__new__(Session)
    session.console = Console(file=stream, force_terminal=False, color_system=None)
    session.config = {}
    session.shadow_env = {}
    session.task = "add subtract helper"
    session.snapshot_id = "snap12345"
    session.project_path = "/tmp/project"
    session.workspace = "/workspace"
    session.sandbox = object()
    session.agent = object()
    session.trace_id = "trace1234"
    session._review = None
    session._test_exit_code = 1
    session._test_output = "tests failed"
    session._get_diffs = lambda: [{"path": "calc.py", "status": "modified", "lines": [("+", "def subtract(a, b): return a - b")]}]
    session._agent_context = lambda: {}

    monkeypatch.setattr("ftl.orchestrator.lint_diffs", lambda diffs, shadow_env=None, task="": [])
    monkeypatch.setattr("ftl.orchestrator.display_violations", lambda violations: None)
    monkeypatch.setattr("ftl.orchestrator.display_review", lambda review, console=None: None)
    monkeypatch.setattr("ftl.orchestrator.review_diff", lambda *args, **kwargs: False)
    monkeypatch.setattr("ftl.orchestrator.write_log", lambda entry, trace_id=None: None)
    session._cleanup = lambda: None

    Session.merge(session)

    output = stream.getvalue()
    assert "Review warning: verification failed" in output
    assert "Decide: review required" in output
