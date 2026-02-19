import click
from rich.console import Console
from ftl.config import load_config, init_config, find_config
from ftl.credentials import load_ftl_credentials, save_ftl_credential
from ftl.orchestrator import run_task, Session


@click.group(invoke_without_command=True)
@click.version_option(version="0.1.0")
@click.pass_context
def main(ctx):
    """FTL: Zero-trust control plane for AI development."""
    load_ftl_credentials()
    if ctx.invoked_subcommand is None:
        shell()


@main.command()
def init():
    """Initialize FTL in the current project. Creates .ftlconfig."""
    if find_config():
        click.echo(".ftlconfig already exists.")
        return
    config_path = init_config()
    click.echo(f"Created {config_path}")


@main.command()
@click.argument("key")
@click.argument("value")
def auth(key, value):
    """Save an FTL credential. Stored in ~/.ftl/credentials.

    Examples:
        ftl auth ANTHROPIC_API_KEY sk-ant-...
        ftl auth AWS_BEARER_TOKEN_BEDROCK ABSK...
    """
    save_ftl_credential(key, value)
    click.echo(f"Saved {key} to ~/.ftl/credentials")


@main.command()
@click.argument("task")
def code(task):
    """Run a coding task in an isolated sandbox.

    Example: ftl code "create login component"
    """
    if not find_config():
        click.echo("No .ftlconfig found. Run 'ftl init' first.")
        raise SystemExit(1)

    run_task(task)


SESSION_COMMANDS = {
    "test": "Run tests against current changes",
    "diff": "Show current diff",
    "merge": "Approve and merge changes",
    "reject": "Discard changes",
    "done": "Same as merge",
}


def shell():
    """Interactive FTL shell with session support."""
    console = Console()

    if not find_config():
        console.print("[red]No .ftlconfig found. Run 'ftl init' first.[/red]")
        raise SystemExit(1)

    config = load_config()
    console.print("[bold]FTL Shell[/bold]")
    console.print(f"[dim]Agent: {config['agent']} | Tester: {config['tester']} | Planner: {config.get('planner_model', 'default')}[/dim]")
    console.print("[dim]Type a task to start. Commands: test, diff, merge, reject, list, restore <id>, exit[/dim]\n")

    from ftl.snapshot import create_snapshot_store
    snapshot_store = create_snapshot_store()
    session = None

    while True:
        prompt = "ftl[active]> " if session and session.is_active else "ftl> "
        try:
            user_input = input(prompt).strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Goodbye.[/dim]")
            if session and session.is_active:
                session.reject()
            break

        if not user_input:
            continue

        if user_input in ("exit", "quit"):
            if session and session.is_active:
                session.reject()
            break

        # Snapshot commands (always available)
        if user_input == "list":
            config_path = find_config()
            snapshots = snapshot_store.list(str(config_path.parent))
            if not snapshots:
                console.print("[dim]No snapshots.[/dim]")
            else:
                for s in snapshots:
                    console.print(f"  {s['id']}  {s['project']}")
            continue

        if user_input == "list all":
            snapshots = snapshot_store.list()
            if not snapshots:
                console.print("[dim]No snapshots.[/dim]")
            else:
                for s in snapshots:
                    console.print(f"  {s['id']}  {s['project']}")
            continue

        if user_input.startswith("restore "):
            snapshot_id = user_input.split(" ", 1)[1].strip()
            console.print(f"Restore snapshot [bold]{snapshot_id}[/bold]?")
            confirm = input("Are you sure? (y/n) > ").strip().lower()
            if confirm in ("y", "yes"):
                try:
                    snapshot_store.restore(snapshot_id)
                    console.print("[green]Restored.[/green]")
                except ValueError as e:
                    console.print(f"[red]{e}[/red]")
            else:
                console.print("[dim]Cancelled.[/dim]")
            continue

        # Session commands (only when a session is active)
        if session and session.is_active:
            if user_input == "test":
                session.run_tests()
                continue

            if user_input == "diff":
                session.show_diff()
                continue

            if user_input in ("merge", "done"):
                session.merge()
                session = None
                continue

            if user_input == "reject":
                session.reject()
                session = None
                continue

            # Anything else is a follow-up message to the planner
            session.follow_up(user_input)
            continue

        # No active session — treat input as a new task
        session = Session()
        session.start(user_input)

        if session.diffs:
            console.print("\n[bold]Session active.[/bold] Commands: test, diff, merge, reject")
            console.print("[dim]Or type a follow-up instruction for the agent.[/dim]")
        else:
            session = None
