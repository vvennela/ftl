import click
from rich.console import Console
from ftl.config import load_config, init_config, find_config
from ftl.orchestrator import run_task


@click.group(invoke_without_command=True)
@click.version_option(version="0.1.0")
@click.pass_context
def main(ctx):
    """FTL: Zero-trust control plane for AI development."""
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
@click.argument("task")
def code(task):
    """Run a coding task in an isolated sandbox.

    Example: ftl code "create login component"
    """
    if not find_config():
        click.echo("No .ftlconfig found. Run 'ftl init' first.")
        raise SystemExit(1)

    run_task(task)


def shell():
    """Interactive FTL shell."""
    console = Console()

    if not find_config():
        console.print("[red]No .ftlconfig found. Run 'ftl init' first.[/red]")
        raise SystemExit(1)

    config = load_config()
    console.print("[bold]FTL Shell[/bold]")
    console.print(f"[dim]Agent: {config['agent']} | Tester: {config['tester']}[/dim]")
    console.print("[dim]Type a task, 'list' for snapshots, 'restore <id>', or 'exit'.[/dim]\n")

    from ftl.snapshot import create_snapshot_store
    snapshot_store = create_snapshot_store()

    while True:
        try:
            user_input = input("ftl> ").strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Goodbye.[/dim]")
            break

        if not user_input:
            continue

        if user_input in ("exit", "quit"):
            break

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

        # Anything else is a task
        run_task(user_input)
