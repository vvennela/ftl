import os
import shutil
import tempfile
from pathlib import Path
from rich.console import Console

from ftl.config import load_config, find_config
from ftl.credentials import build_shadow_map
from ftl.ignore import get_ignore_set, should_ignore
from ftl.log import write_log
from ftl.snapshot import create_snapshot_store
from ftl.sandbox import create_sandbox
from ftl.diff import display_diff, review_diff
from ftl.lint import lint_diffs, display_violations
from ftl.planner import PlannerLoop


# Agent auth env vars to forward from host into sandbox.
AGENT_AUTH_VARS = {
    "claude-code": ["ANTHROPIC_API_KEY"],
    "kiro": ["KIRO_API_KEY", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_DEFAULT_REGION"],
}


def _collect_agent_env(agent_name, config):
    """Collect auth env vars for the agent from the host environment."""
    env = {}
    for key in AGENT_AUTH_VARS.get(agent_name, []):
        if key in os.environ:
            env[key] = os.environ[key]
    for key in config.get("agent_env", []):
        if key in os.environ:
            env[key] = os.environ[key]
    return env


def _copy_project_to_workspace(project_path, workspace, ignore_set):
    """Copy project to temp workspace, respecting ignore rules."""
    project = Path(project_path)
    for item in project.rglob("*"):
        relative = item.relative_to(project)
        if should_ignore(relative, ignore_set):
            continue
        dest = Path(workspace) / relative
        if item.is_dir():
            dest.mkdir(parents=True, exist_ok=True)
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, dest)


def _merge_changes(diffs, workspace, project_path):
    """Apply only the actual changes back to the project (diff-driven merge)."""
    workspace = Path(workspace)
    project = Path(project_path)

    for diff in diffs:
        rel = Path(diff["path"])
        if diff["status"] in ("created", "modified"):
            src = workspace / rel
            dest = project / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
        elif diff["status"] == "deleted":
            target = project / rel
            if target.exists():
                target.unlink()


class Session:
    """An active FTL coding session.

    Manages the sandbox, planner loop, and workspace for a task.
    Supports follow-up messages, manual test/diff/merge commands.
    """

    def __init__(self):
        self.console = Console()
        self.config = load_config()
        self.config_path = find_config()
        self.project_path = str(self.config_path.parent)

        self.agent_name = self.config.get("agent", "claude-code")
        self.tester = self.config.get("tester", "bedrock/deepseek-r1")

        self.sandbox = None
        self.planner = None
        self.workspace = None
        self.snapshot_id = None
        self.snapshot_path = None
        self.diffs = None
        self.shadow_env = None
        self.task = None

    def start(self, task):
        """Start a new coding session with the given task."""
        # Validate
        if self.tester == self.agent_name:
            self.console.print("[red]Error: tester cannot be the same as agent.[/red]")
            raise SystemExit(1)

        # 1. Snapshot
        self.console.print("[bold]Snapshotting project...[/bold]")
        snapshot_store = create_snapshot_store()
        self.snapshot_id = snapshot_store.create(self.project_path)
        self.snapshot_path = str(Path.home() / ".ftl" / "snapshots" / self.snapshot_id)
        self.console.print(f"  Snapshot: {self.snapshot_id}")

        # 2. Copy to workspace (filtered)
        ignore_set = get_ignore_set(self.project_path)
        self.workspace = tempfile.mkdtemp(prefix="ftl_workspace_")
        _copy_project_to_workspace(self.project_path, self.workspace, ignore_set)

        # 3. Shadow credentials
        extra_vars = self.config.get("shadow_env", [])
        self.shadow_env, swap_table = build_shadow_map(self.project_path, extra_vars)
        shadow_env = self.shadow_env
        if shadow_env:
            self.console.print(f"  Shadow credentials: {len(shadow_env)} keys injected")

        # 4. Agent auth
        agent_env = _collect_agent_env(self.agent_name, self.config)
        if agent_env:
            self.console.print(f"  Agent auth: {len(agent_env)} keys forwarded")

        # 5. Boot sandbox
        self.console.print("[bold]Booting sandbox...[/bold]")
        self.sandbox = create_sandbox()
        self.sandbox.boot(self.workspace, credentials=shadow_env, agent_env=agent_env)
        self.console.print("  Sandbox ready")

        # 6. Create planner and run
        self.planner = PlannerLoop(
            self.config, self.sandbox, self.snapshot_path, self.workspace
        )
        self.task = task
        self.diffs = self.planner.run(task)

        write_log({
            "event": "session_start",
            "task": task,
            "snapshot": self.snapshot_id,
            "project": self.project_path,
            "agent": self.agent_name,
            "files_changed": len(self.diffs) if self.diffs else 0,
        })

        if not self.diffs:
            self.console.print("[dim]No changes detected.[/dim]")

    def follow_up(self, message):
        """Send a follow-up instruction to the planner (continues the session)."""
        if not self.planner:
            self.console.print("[red]No active session. Type a task first.[/red]")
            return

        self.planner.inject_message(message)
        self.diffs = self.planner.run(message)  # run() skips re-adding since messages already set

    def show_diff(self):
        """Display the current diff."""
        if not self.diffs:
            from ftl.diff import compute_diff
            self.diffs = compute_diff(self.snapshot_path, self.workspace)
        display_diff(self.diffs)

    def run_tests(self):
        """Manually trigger tests."""
        if not self.sandbox:
            self.console.print("[red]No active session.[/red]")
            return
        from ftl.diff import compute_diff
        from ftl.planner import run_verification
        self.diffs = compute_diff(self.snapshot_path, self.workspace)
        if not self.diffs:
            self.console.print("[dim]No changes to test.[/dim]")
            return
        run_verification(self.diffs, self.tester, self.sandbox)

    def merge(self):
        """Approve and merge changes back to the project."""
        if not self.diffs:
            self.console.print("[dim]No changes to merge.[/dim]")
            return

        # Run credential lint before review
        violations = lint_diffs(self.diffs, self.shadow_env)
        display_violations(violations)
        if violations:
            self.console.print(
                "[bold yellow]Credential violations detected. "
                "Proceeding to review — inspect flagged lines carefully.[/bold yellow]\n"
            )

        planner_model = self.config.get("planner_model", "bedrock/amazon.nova-lite-v1:0")
        approved = review_diff(self.diffs, planner_model)

        if approved:
            self.console.print("[bold green]Approved. Merging changes...[/bold green]")
            _merge_changes(self.diffs, self.workspace, self.project_path)
            self.console.print("  Changes merged to project.")
            write_log({
                "event": "merge",
                "task": self.task or "",
                "snapshot": self.snapshot_id,
                "project": self.project_path,
                "result": "merged",
                "files_changed": len(self.diffs),
                "lint_violations": len(violations),
            })
        else:
            self.console.print("[bold red]Rejected. Changes discarded.[/bold red]")
            write_log({
                "event": "review",
                "task": self.task or "",
                "snapshot": self.snapshot_id,
                "project": self.project_path,
                "result": "rejected",
            })

        self._cleanup()

    def reject(self):
        """Discard changes and clean up."""
        self.console.print("[bold red]Changes discarded.[/bold red]")
        write_log({
            "event": "reject",
            "task": self.task or "",
            "snapshot": self.snapshot_id,
            "project": self.project_path,
            "result": "rejected",
        })
        self._cleanup()

    def _cleanup(self):
        """Clean up sandbox and workspace."""
        if self.sandbox:
            self.sandbox.standby()
            self.console.print(f"[dim]Snapshot {self.snapshot_id} available for rollback.[/dim]")
        if self.workspace:
            try:
                shutil.rmtree(self.workspace)
            except OSError as e:
                self.console.print(f"[yellow]Warning: Failed to clean up {self.workspace}: {e}[/yellow]")
        self.sandbox = None
        self.planner = None
        self.workspace = None
        self.diffs = None
        self.shadow_env = None

    @property
    def is_active(self):
        return self.planner is not None


def run_task(task):
    """One-shot mode: run task, review, merge/reject, done."""
    session = Session()
    session.start(task)

    if session.diffs:
        session.merge()  # triggers interactive review
    else:
        session._cleanup()
