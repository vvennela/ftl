import shutil
import tempfile
from pathlib import Path
from rich.console import Console
import litellm

from ftl.config import load_config, find_config
from ftl.credentials import build_shadow_map
from ftl.snapshot import create_snapshot_store
from ftl.sandbox import create_sandbox
from ftl.agents import get_agent, AGENTS
from ftl.diff import compute_diff, diff_to_text, review_diff


def run_tests_with_model(diffs, model, sandbox):
    """Generate and run tests using an LLM model via LiteLLM."""
    diff_text = diff_to_text(diffs)

    response = litellm.completion(
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are an adversarial test engineer. Given code changes, generate "
                    "a test script that tries to break the code. Focus on edge cases, "
                    "null inputs, boundary conditions, and unexpected usage. Your goal is "
                    "to find bugs. Output ONLY the test script, no explanation. Use the "
                    "appropriate test framework (pytest for Python, jest/vitest for JS/TS)."
                ),
            },
            {
                "role": "user",
                "content": f"Write tests to find bugs in these changes:\n\n{diff_text}",
            },
        ],
    )

    test_code = response.choices[0].message.content

    # Strip markdown code fences — handle ```python, ```js, ``` etc.
    import re
    fence_pattern = re.compile(r"^```\w*\n(.*?)```$", re.DOTALL)
    match = fence_pattern.search(test_code.strip())
    if match:
        test_code = match.group(1)

    sandbox.exec(f"cat > /workspace/_ftl_test.py << 'FTLEOF'\n{test_code}\nFTLEOF")
    exit_code, stdout, stderr = sandbox.exec(
        "cd /workspace && python -m pytest _ftl_test.py -v 2>&1 || node _ftl_test.py 2>&1"
    )
    sandbox.exec("rm -f /workspace/_ftl_test.py")

    return exit_code, stdout, stderr


def run_tests_with_agent(diffs, agent_name, sandbox):
    """Run tests using a coding agent inside the sandbox."""
    diff_text = diff_to_text(diffs)
    agent = get_agent(agent_name)

    task = (
        "Review the following code changes and write tests that try to break them. "
        "Focus on edge cases, null inputs, boundary conditions, and unexpected usage. "
        "Run the tests and report results.\n\n"
        f"{diff_text}"
    )

    exit_code, stdout, stderr = agent.run(task, "/workspace")
    return exit_code, stdout, stderr


def run_verification(diffs, tester, sandbox):
    """Route to model or agent based on tester config."""
    console = Console()
    console.print(f"[bold]Running verification ({tester})...[/bold]")

    if tester in AGENTS:
        exit_code, stdout, stderr = run_tests_with_agent(diffs, tester, sandbox)
    else:
        exit_code, stdout, stderr = run_tests_with_model(diffs, tester, sandbox)

    if exit_code == 0:
        console.print("[green]  Tests passed.[/green]")
    else:
        console.print("[yellow]  Tests failed:[/yellow]")
        console.print(f"[dim]{stdout}{stderr}[/dim]")

    return exit_code, stdout, stderr


def run_task(task):
    """Execute the full FTL flow for a coding task."""
    console = Console()
    config = load_config()

    config_path = find_config()
    project_path = str(config_path.parent)

    # Validate tester != agent
    agent_name = config.get("agent", "claude-code")
    tester = config.get("tester", "bedrock/deepseek-r1")
    if tester == agent_name:
        console.print("[red]Error: tester cannot be the same as agent.[/red]")
        console.print("[red]Change 'tester' in .ftlconfig to a different agent or model.[/red]")
        raise SystemExit(1)

    # 1. Snapshot
    console.print("[bold]Snapshotting project...[/bold]")
    snapshot_store = create_snapshot_store()
    snapshot_id = snapshot_store.create(project_path)
    snapshot_path = str(Path.home() / ".ftl" / "snapshots" / snapshot_id)
    console.print(f"  Snapshot: {snapshot_id}")

    # 2. Copy project to temp workspace
    workspace = tempfile.mkdtemp(prefix="ftl_workspace_")
    for item in Path(project_path).rglob("*"):
        relative = item.relative_to(project_path)
        dest = Path(workspace) / relative
        if item.is_dir():
            dest.mkdir(parents=True, exist_ok=True)
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, dest)

    try:
        # 3. Build shadow credentials
        extra_vars = config.get("shadow_env", [])
        shadow_env, swap_table = build_shadow_map(project_path, extra_vars)
        if shadow_env:
            console.print(f"  Shadow credentials: {len(shadow_env)} keys injected")

        # 4. Boot sandbox
        console.print("[bold]Booting sandbox...[/bold]")
        sandbox = create_sandbox()
        sandbox.boot(workspace, credentials=shadow_env)
        console.print("  Sandbox ready")

        # 5. Run agent
        console.print(f"[bold]Running agent ({agent_name})...[/bold]")
        agent = get_agent(agent_name)
        exit_code, stdout, stderr = agent.run(task, "/workspace")

        if exit_code != 0:
            console.print(f"[red]Agent exited with code {exit_code}[/red]")
            if stderr:
                console.print(f"[red]{stderr}[/red]")

        # 6. Compute diff
        console.print("[bold]Computing diff...[/bold]")
        diffs = compute_diff(snapshot_path, workspace)

        if not diffs:
            console.print("[dim]No changes detected.[/dim]")
            sandbox.standby()
            return

        # 7. Verification
        test_exit, test_stdout, test_stderr = run_verification(diffs, tester, sandbox)

        # 8. Interactive review
        if test_exit != 0:
            console.print("[yellow]Tests failed. Review carefully.[/yellow]")

        planner_model = config.get("planner_model", "bedrock/amazon.nova-lite-v1:0")
        approved = review_diff(diffs, planner_model)

        # 9. Merge or discard
        if approved:
            console.print("[bold green]Approved. Merging changes...[/bold green]")
            for item in Path(workspace).rglob("*"):
                relative = item.relative_to(workspace)
                dest = Path(project_path) / relative
                if item.is_dir():
                    dest.mkdir(parents=True, exist_ok=True)
                else:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(item, dest)
            console.print("  Changes merged to project.")
        else:
            console.print("[bold red]Rejected. Changes discarded.[/bold red]")

        # 10. Standby
        sandbox.standby()
        console.print(f"[dim]Snapshot {snapshot_id} available for rollback.[/dim]")

    finally:
        try:
            shutil.rmtree(workspace)
        except OSError as e:
            console.print(f"[yellow]Warning: Failed to clean up {workspace}: {e}[/yellow]")
