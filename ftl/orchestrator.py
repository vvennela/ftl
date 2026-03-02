import os
import platform
import shutil
import subprocess
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from rich.console import Console

from ftl import cloudwatch
from ftl.config import load_config, find_config
from ftl.credentials import build_shadow_map
from ftl.log import write_log
from ftl.snapshot import create_snapshot_store
from ftl.sandbox import create_sandbox
from ftl.agents import get_agent
from ftl.diff import display_diff, review_diff
from ftl.lint import lint_diffs, display_violations
from ftl.planner import generate_tests_from_task, run_test_code, run_verification
from ftl.tracing import setup_langfuse, StageTimer, AgentHeartbeat
from ftl.render import AgentRenderer

setup_langfuse()


def _try_start_proxy(swap_table):
    """Start the credential-swap proxy if cryptography is available and swap_table is non-empty.

    Returns the proxy instance (started), or None if disabled/unavailable.
    """
    if not swap_table:
        return None
    try:
        from ftl.proxy import CredentialSwapProxy
        proxy = CredentialSwapProxy(swap_table)
        proxy.start()
        return proxy
    except (ImportError, RuntimeError):
        return None


# Agent auth env vars to forward from host into sandbox.
AGENT_AUTH_VARS = {
    "claude-code": ["ANTHROPIC_API_KEY"],
    "kiro": ["KIRO_API_KEY", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_DEFAULT_REGION"],
    "codex": ["OPENAI_API_KEY"],
    "aider": ["OPENAI_API_KEY", "ANTHROPIC_API_KEY"],  # model-dependent
}

# Required key per agent — checked before sandbox boot to fail fast.
AGENT_REQUIRED_KEY = {
    "claude-code": "ANTHROPIC_API_KEY",
    "codex": "OPENAI_API_KEY",
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


def _merge_changes(diffs, workspace, project_path):
    """Apply only the actual changes back to the project (diff-driven merge).

    For diffs produced by get_diff(), content is in diff["_content_bytes"].
    Falls back to shutil.copy2 from a local workspace path if not present.
    """
    workspace = Path(workspace)
    project = Path(project_path)

    for diff in diffs:
        rel = Path(diff["path"])
        if diff["status"] in ("created", "modified"):
            dest = project / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            if "_content_bytes" in diff:
                dest.write_bytes(diff["_content_bytes"])
            else:
                src = workspace / rel
                shutil.copy2(src, dest)
        elif diff["status"] == "deleted":
            target = project / rel
            if target.exists():
                target.unlink()


class Session:
    """An active FTL coding session.

    Manages the sandbox, agent, and diff state for a task.
    Agent and tester run in parallel — tests are generated from the task
    description while the agent codes, then run immediately when both finish.
    """

    def __init__(self):
        self.console = Console()
        self.config = load_config()
        self.config_path = find_config()
        self.project_path = str(self.config_path.parent)

        self.agent_name = self.config.get("agent", "claude-code")
        self.tester = self.config.get("tester", "bedrock/us.anthropic.claude-sonnet-4-6")
        self.trace_id = uuid.uuid4().hex[:8]

        self.sandbox = None
        self.agent = None
        self.agent_calls = 0
        self.snapshot_id = None
        self.snapshot_path = None
        self.workspace = None
        self.diffs = None
        self.shadow_env = None
        self.task = None
        self._proxy = None

    def start(self, task):
        """Start a new coding session: snapshot → sandbox → agent ∥ test-gen → run tests → diff."""
        timer = StageTimer(self.console)

        # Init CloudWatch tracing (no-op if not configured or boto3 absent)
        log_group = self.config.get("cloudwatch_log_group", "")
        log_stream = f"{datetime.now().strftime('%Y/%m/%d')}/{self.trace_id}"
        cloudwatch.init(log_group, log_stream)
        cloudwatch.emit(self.trace_id, "session", "start",
                        task=task, project=self.project_path, agent=self.agent_name)

        # 1. Snapshot
        self.console.print("[bold]Snapshotting project...[/bold]")
        snapshot_store = create_snapshot_store(self.config)
        self.snapshot_id = snapshot_store.create(self.project_path)
        self.snapshot_path = str(Path.home() / ".ftl" / "snapshots" / self.snapshot_id)
        self.console.print(f"  Snapshot: {self.snapshot_id}")
        elapsed = timer.mark("snapshot")
        cloudwatch.emit(self.trace_id, "stage", "snapshot", elapsed_ms=elapsed * 1000)

        # 2. Shadow credentials + proxy
        sm_prefix = self.config.get("secrets_manager_prefix", "")
        if sm_prefix:
            # AWS mode: Secrets Manager replaces .env
            from ftl.secrets import load_from_secrets_manager
            from ftl.credentials import generate_shadow_key
            sm_secrets = load_from_secrets_manager(sm_prefix)
            self.shadow_env, swap_table = {}, {}
            for name, real_value in sm_secrets.items():
                shadow_value = generate_shadow_key(name)
                self.shadow_env[name] = shadow_value
                swap_table[shadow_value] = real_value
            if sm_secrets:
                self.console.print(f"  Secrets Manager: {len(sm_secrets)} secrets loaded")
        else:
            # Local mode: read .env as before
            extra_vars = self.config.get("shadow_env", [])
            self.shadow_env, swap_table = build_shadow_map(self.project_path, extra_vars)
            if self.shadow_env:
                self.console.print(f"  Shadow credentials: {len(self.shadow_env)} keys injected")

        # Start credential-swap proxy (requires cryptography; silently skipped if absent)
        self._proxy = _try_start_proxy(swap_table)
        if self._proxy:
            self.console.print(
                f"  Proxy: credential swap active on port {self._proxy.port}"
            )
        elif swap_table:
            self.console.print(
                "[yellow]  Warning: credential-swap proxy unavailable "
                "(install cryptography: pip install -e '.[proxy]'). "
                "Agent will use shadow values — live API calls may fail.[/yellow]"
            )

        # 3. Agent auth + proxy routing env vars
        agent_env = _collect_agent_env(self.agent_name, self.config)

        # Validate agent credentials before spending time on sandbox boot
        required_key = AGENT_REQUIRED_KEY.get(self.agent_name)
        if required_key and required_key not in agent_env:
            self.console.print(
                f"[bold red]{required_key} is not set.[/bold red]\n"
                f"  Run: ftl auth {required_key} <your-key>"
            )
            raise SystemExit(1)
        
        # Aider requires at least one model key
        if self.agent_name == "aider":
            if not any(k in agent_env for k in ["OPENAI_API_KEY", "ANTHROPIC_API_KEY"]):
                self.console.print(
                    "[bold red]Aider requires OPENAI_API_KEY or ANTHROPIC_API_KEY[/bold red]\n"
                    "  Run: ftl auth OPENAI_API_KEY <your-key>"
                )
                raise SystemExit(1)

        if self._proxy:
            agent_env.update(self._proxy.env_vars())
        if agent_env:
            self.console.print(f"  Agent auth: {len(agent_env)} keys forwarded")

        # 4. Boot sandbox
        self.console.print("[bold]Booting sandbox...[/bold]")
        self.sandbox = create_sandbox()
        self.sandbox.boot(
            self.snapshot_path,
            credentials=self.shadow_env,
            agent_env=agent_env,
            project_path=self.project_path,
            setup_cmd=self.config.get("setup"),
        )
        self.workspace = "/workspace"
        self.agent = get_agent(self.agent_name)
        self.agent_calls = 0

        # Install proxy CA cert into container trust store
        if self._proxy:
            self._proxy.install_ca_in_container(self.sandbox)

        if self.sandbox.fresh and self.config.get("setup"):
            self.console.print("  Setup: ran on fresh container")

        self.console.print(
            f"  Sandbox ready"
            f"  [dim]({'fresh' if self.sandbox.fresh else 'warm'} container)[/dim]"
        )
        elapsed = timer.mark("boot")
        cloudwatch.emit(self.trace_id, "stage", "boot", elapsed_ms=elapsed * 1000)

        # 5. Run agent + generate tests in parallel.
        #    Tests generate while the agent codes; when the agent finishes the
        #    diff is shown immediately and tests run in a background thread.
        self.console.print(
            f"[bold]Running agent[/bold]"
            f"[dim]  (generating tests in parallel via {self.tester})[/dim]"
        )

        heartbeat = AgentHeartbeat(self.console)
        renderer = AgentRenderer(self.console, trace_id=self.trace_id)

        def _run_agent():
            heartbeat.start()
            def _stream(line):
                heartbeat.stop()
                renderer.feed(line)
            result = self.agent.run(task, "/workspace", self.sandbox, callback=_stream)
            heartbeat.stop()
            renderer.finish()
            return result

        with ThreadPoolExecutor(max_workers=2) as executor:
            agent_future = executor.submit(_run_agent)
            test_future = executor.submit(generate_tests_from_task, task, self.tester)

        try:
            agent_future.result()
        except Exception as e:
            self.console.print(f"[yellow]  Agent error: {e}[/yellow]")

        self.agent_calls = 1
        elapsed = timer.mark("agent")
        cloudwatch.emit(self.trace_id, "stage", "agent", elapsed_ms=elapsed * 1000)

        # 6. Run tests — generation was parallel so test_future is usually
        #    already done by the time the agent finishes.
        test_code = test_future.result()
        if test_code:
            self.console.print("[bold]Running tests...[/bold]")
            run_test_code(test_code, self.sandbox, self.console)
            elapsed = timer.mark("tests")
            cloudwatch.emit(self.trace_id, "stage", "tests", elapsed_ms=elapsed * 1000)

        self.task = task

        write_log({
            "event": "session_start",
            "task": task,
            "snapshot": self.snapshot_id,
            "project": self.project_path,
            "agent": self.agent_name,
        }, trace_id=self.trace_id)

    def _get_diffs(self):
        """Return diffs, computing lazily on first call."""
        if self.diffs is None and self.sandbox:
            self.diffs = self.sandbox.get_diff(self.snapshot_path)
        return self.diffs or []

    def follow_up(self, message):
        """Send a follow-up instruction to the agent (continues the session)."""
        if not self.sandbox:
            self.console.print("[red]No active session. Type a task first.[/red]")
            return

        self.console.print(f"[bold cyan]  → Agent: {message}[/bold cyan]")

        renderer = AgentRenderer(self.console, trace_id=self.trace_id)
        self.agent.continue_run(message, "/workspace", self.sandbox, callback=renderer.feed)
        renderer.finish()
        self.agent_calls += 1
        self.diffs = None  # invalidate; recomputed on next access

    def show_diff(self):
        """Display the current diff."""
        display_diff(self._get_diffs())

    def run_tests(self):
        """Manually trigger tests against the current diff."""
        if not self.sandbox:
            self.console.print("[red]No active session.[/red]")
            return
        diffs = self._get_diffs()
        if not diffs:
            self.console.print("[dim]No changes to test.[/dim]")
            return
        run_verification(diffs, self.tester, self.sandbox)

    def merge(self):
        """Approve and merge changes back to the project."""
        diffs = self._get_diffs()
        if not diffs:
            self.console.print("[dim]No changes to merge.[/dim]")
            self._cleanup()
            return

        guardrail_id = self.config.get("guardrail_id", "")
        if guardrail_id:
            # AWS mode: Bedrock Guardrails replaces local lint
            from ftl.guardrails import apply_guardrail
            from ftl.diff import diff_to_text
            blocked, gr_findings = apply_guardrail(
                guardrail_id,
                self.config.get("guardrail_version", "DRAFT"),
                diff_to_text(diffs),
            )
            if gr_findings:
                self.console.print("[bold red]Bedrock Guardrail findings:[/bold red]")
                for f in gr_findings:
                    self.console.print(f"  [red]• {f}[/red]")
            if blocked:
                self.console.print("[bold red]Guardrail blocked merge. Changes discarded.[/bold red]")
                self._cleanup()
                return
            violations = []  # no local lint when guardrail active
        else:
            # Local mode: existing lint scan
            violations = lint_diffs(diffs, self.shadow_env)
            display_violations(violations)
            if violations:
                self.console.print(
                    "[bold yellow]Credential violations detected. "
                    "Proceeding to review — inspect flagged lines carefully.[/bold yellow]\n"
                )

        planner_model = self.config.get("planner_model", self.tester)
        approved = review_diff(diffs, planner_model)

        if approved:
            self.console.print("[bold green]Approved. Merging changes...[/bold green]")
            _merge_changes(diffs, self.workspace, self.project_path)
            self.console.print("  Changes merged to project.")
            write_log({
                "event": "merge",
                "task": self.task or "",
                "snapshot": self.snapshot_id,
                "project": self.project_path,
                "result": "merged",
                "files_changed": len(diffs),
                "lint_violations": len(violations),
            }, trace_id=self.trace_id)
        else:
            self.console.print("[bold red]Rejected. Changes discarded.[/bold red]")
            write_log({
                "event": "review",
                "task": self.task or "",
                "snapshot": self.snapshot_id,
                "project": self.project_path,
                "result": "rejected",
            }, trace_id=self.trace_id)

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
        }, trace_id=self.trace_id)
        self._cleanup()

    def _cleanup(self):
        """Put sandbox on standby and clear session state."""
        if self.sandbox:
            self.sandbox.standby()
            self.console.print(f"[dim]Snapshot {self.snapshot_id} available for rollback.[/dim]")
        if self._proxy:
            self._proxy.stop()
            self._proxy = None
        self.sandbox = None
        self.agent = None
        self.agent_calls = 0
        self.workspace = None
        self.diffs = None
        self.shadow_env = None

    @property
    def is_active(self):
        return self.sandbox is not None


def _notify(title, message):
    """Send a system notification. Best-effort — never raises."""
    try:
        if platform.system() == "Darwin":
            subprocess.run(
                ["osascript", "-e", f'display notification "{message}" with title "{title}"'],
                capture_output=True,
            )
        elif platform.system() == "Linux":
            subprocess.run(["notify-send", title, message], capture_output=True)
    except Exception:
        pass


def _fmt_elapsed(seconds):
    m, s = divmod(int(seconds), 60)
    return f"{m}m {s}s" if m else f"{s}s"


def run_task(task):
    """One-shot mode: run task, review, merge/reject, done."""
    t0 = time.time()
    session = Session()
    session.start(task)

    elapsed = _fmt_elapsed(time.time() - t0)
    session.console.print(f"\n[dim]Completed in {elapsed}[/dim]")
    _notify("FTL", f"Done in {elapsed}")

    # merge() computes diff lazily; cleans up whether or not there are changes
    session.merge()
