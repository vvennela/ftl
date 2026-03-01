import json
import os
import subprocess
from datetime import datetime
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table
from ftl.config import load_config, init_config, find_config
from ftl.credentials import load_ftl_credentials, save_ftl_credential, FTL_CREDENTIALS_FILE
from ftl.log import LOGS_FILE
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
    """Initialize FTL in the current project. Creates .ftlconfig with defaults."""
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


@main.group(invoke_without_command=True)
@click.option("--all", "show_all", is_flag=True, help="Show snapshots for all projects.")
@click.pass_context
def snapshots(ctx, show_all):
    """List and manage project snapshots."""
    if ctx.invoked_subcommand is not None:
        return

    from ftl.snapshot import create_snapshot_store

    console = Console()
    config_path = find_config()
    store = create_snapshot_store(load_config() if config_path else None)

    if not show_all and not config_path:
        console.print("[red]No .ftlconfig found. Use --all or run 'ftl init'.[/red]")
        raise SystemExit(1)

    project_filter = str(config_path.parent) if config_path and not show_all else None
    snapshot_list = _snapshots_sorted(store, project_filter)

    if not snapshot_list:
        console.print("[dim]No snapshots found.[/dim]")
        return

    table = Table(title="Snapshots")
    table.add_column("ID", style="bold cyan")
    table.add_column("Project", style="dim")
    table.add_column("Created", style="dim")

    for s in snapshot_list:
        table.add_row(s["id"], s["project"], s["created"])

    console.print(table)


def _snapshots_sorted(store, project_filter=None):
    """Return snapshots sorted oldest-first, with a 'created' field."""
    raw = store.list(project_filter)
    result = []
    for s in raw:
        snap_path = Path.home() / ".ftl" / "snapshots" / s["id"]
        mtime = snap_path.stat().st_mtime
        result.append({**s, "mtime": mtime, "created": datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")})
    return sorted(result, key=lambda s: s["mtime"])


@snapshots.command("clean")
@click.option("--last", "last_n", type=int, default=None, help="Delete the N most recent snapshots.")
@click.option("--all", "delete_all", is_flag=True, help="Delete all snapshots.")
@click.option("--project-only", is_flag=True, help="Limit to snapshots from the current project.")
@click.option("-y", "--yes", is_flag=True, help="Skip confirmation prompt.")
def snapshots_clean(last_n, delete_all, project_only, yes):
    """Delete snapshots. Use --last N or --all."""
    from ftl.snapshot import create_snapshot_store

    console = Console()

    if not last_n and not delete_all:
        console.print("[red]Specify --last N or --all.[/red]")
        raise SystemExit(1)

    config_path = find_config()
    store = create_snapshot_store(load_config() if config_path else None)
    project_filter = str(config_path.parent) if project_only and config_path else None
    all_snaps = _snapshots_sorted(store, project_filter)

    if delete_all:
        targets = all_snaps
    else:
        targets = all_snaps[-last_n:]  # most recent N (list is oldest-first)

    if not targets:
        console.print("[dim]No snapshots to delete.[/dim]")
        return

    console.print(f"[bold]About to delete {len(targets)} snapshot(s):[/bold]")
    for s in targets:
        console.print(f"  [cyan]{s['id']}[/cyan]  {s['project']}  [dim]{s['created']}[/dim]")

    if not yes:
        confirm = input("\nDelete these snapshots? (y/n) > ").strip().lower()
        if confirm not in ("y", "yes"):
            console.print("[dim]Cancelled.[/dim]")
            return

    for s in targets:
        store.delete(s["id"])
        console.print(f"  [red]Deleted[/red] {s['id']}")

    console.print(f"[bold green]Done. {len(targets)} snapshot(s) removed.[/bold green]")


@main.command()
@click.option("-n", "--limit", default=20, help="Number of log entries to show.")
@click.option("--all", "show_all", is_flag=True, help="Show logs for all projects.")
def logs(limit, show_all):
    """Show session audit log."""
    console = Console()

    if not LOGS_FILE.exists():
        console.print("[dim]No logs yet. Run a task first.[/dim]")
        return

    config_path = find_config()
    project_filter = str(config_path.parent) if config_path and not show_all else None

    entries = []
    for line in LOGS_FILE.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if project_filter and entry.get("project") != project_filter:
            continue
        entries.append(entry)

    if not entries:
        console.print("[dim]No logs found.[/dim]")
        return

    table = Table(title="Session Log")
    table.add_column("Time", style="dim")
    table.add_column("Event", style="bold")
    table.add_column("Task", max_width=50)
    table.add_column("Snapshot", style="cyan")
    table.add_column("Result", style="bold")

    for entry in entries[-limit:]:
        ts = entry.get("timestamp", "")
        if ts:
            try:
                ts = datetime.fromisoformat(ts).strftime("%m-%d %H:%M")
            except ValueError:
                pass
        result = entry.get("result", "")
        result_style = {"merged": "[green]merged[/green]", "rejected": "[red]rejected[/red]"}.get(result, result)
        table.add_row(
            ts,
            entry.get("event", ""),
            entry.get("task", "")[:50],
            entry.get("snapshot", ""),
            result_style,
        )

    console.print(table)


def _check_api_key_configured():
    """Return True if ANTHROPIC_API_KEY is in env or ~/.ftl/credentials."""
    if "ANTHROPIC_API_KEY" in os.environ:
        return True
    if FTL_CREDENTIALS_FILE.exists():
        for line in FTL_CREDENTIALS_FILE.read_text().splitlines():
            if line.startswith("ANTHROPIC_API_KEY="):
                return True
    return False


def _build_image(console):
    """Build the ftl-sandbox Docker image from the bundled Dockerfile."""
    dockerfile_dir = Path(__file__).parent.parent
    dockerfile = dockerfile_dir / "Dockerfile"
    if not dockerfile.exists():
        console.print("[red]Dockerfile not found.[/red]")
        console.print(f"  Expected at: {dockerfile}")
        console.print("  Run manually from the FTL repo root: docker build -t ftl-sandbox .")
        raise SystemExit(1)

    console.print("[bold]Building ftl-sandbox image (~2 min)...[/bold]")
    result = subprocess.run(
        ["docker", "build", "-t", "ftl-sandbox", str(dockerfile_dir)],
    )
    if result.returncode != 0:
        console.print("[red]Build failed.[/red]")
        raise SystemExit(1)
    console.print("  [green]Image built.[/green]")


@main.command()
def setup():
    """One-command setup: verify Docker, build sandbox image, save API key."""
    console = Console()

    # 1. Check Docker is running
    console.print("[bold]Checking Docker...[/bold]")
    try:
        subprocess.run(["docker", "info"], capture_output=True, check=True)
        console.print("  [green]Docker is running.[/green]")
    except FileNotFoundError:
        console.print("[red]Docker not found. Install Docker Desktop and try again.[/red]")
        console.print("  https://docs.docker.com/get-docker/")
        raise SystemExit(1)
    except subprocess.CalledProcessError:
        console.print("[red]Docker is installed but not running. Start Docker Desktop and try again.[/red]")
        raise SystemExit(1)

    # 2. Check if image already exists, build if not
    result = subprocess.run(
        ["docker", "images", "-q", "ftl-sandbox:latest"],
        capture_output=True, text=True,
    )
    if result.stdout.strip():
        console.print("  [green]ftl-sandbox image already exists. Skipping build.[/green]")
    else:
        _build_image(console)

    # 3. Prompt for ANTHROPIC_API_KEY if not configured
    console.print()
    if _check_api_key_configured():
        console.print("  [green]ANTHROPIC_API_KEY already configured.[/green]")
    else:
        console.print("[bold]Anthropic API key[/bold]")
        console.print("  [dim]Get one at https://console.anthropic.com[/dim]")
        key = click.prompt("  ANTHROPIC_API_KEY", hide_input=True, default="", show_default=False)
        if key.strip():
            save_ftl_credential("ANTHROPIC_API_KEY", key.strip())
            console.print("  [green]Saved to ~/.ftl/credentials[/green]")
        else:
            console.print("  [yellow]Skipped. Set it later with: ftl auth ANTHROPIC_API_KEY sk-ant-...[/yellow]")

    # 4. Done
    console.print()
    console.print("[bold green]Setup complete.[/bold green]")
    console.print("  Next: [bold]cd your-project && ftl init && ftl code 'your task'[/bold]")


def _configure_aws():
    """Provision AWS resources and write config for AWS mode."""
    console = Console()

    try:
        import boto3
    except ImportError:
        console.print("[red]boto3 not installed. Run: pip install -e \".[aws]\"[/red]")
        raise SystemExit(1)

    # 1. Get account ID and region
    console.print("[bold]Configuring FTL for AWS...[/bold]")
    sts = boto3.client("sts")
    identity = sts.get_caller_identity()
    account_id = identity["Account"]
    region = boto3.session.Session().region_name or "us-east-1"
    console.print(f"  Account: {account_id}  Region: {region}")

    config_path = find_config()
    if not config_path:
        console.print("[red]No .ftlconfig found. Run 'ftl init' first.[/red]")
        raise SystemExit(1)
    project_name = config_path.parent.name

    # 2. Create S3 bucket (idempotent)
    bucket_name = f"ftl-{account_id}-{region}"
    s3 = boto3.client("s3", region_name=region)
    console.print(f"  S3 bucket: {bucket_name}")
    try:
        if region == "us-east-1":
            s3.create_bucket(Bucket=bucket_name)
        else:
            s3.create_bucket(
                Bucket=bucket_name,
                CreateBucketConfiguration={"LocationConstraint": region},
            )
        console.print("    [green]Created.[/green]")
    except s3.exceptions.BucketAlreadyOwnedByYou:
        console.print("    [dim]Already exists.[/dim]")
    except Exception as e:
        console.print(f"    [yellow]Warning: {e}[/yellow]")

    # 3. Create CloudWatch log group (idempotent)
    log_group = f"/ftl/{project_name}"
    cw = boto3.client("logs", region_name=region)
    console.print(f"  CloudWatch log group: {log_group}")
    try:
        cw.create_log_group(logGroupName=log_group)
        console.print("    [green]Created.[/green]")
    except cw.exceptions.ResourceAlreadyExistsException:
        console.print("    [dim]Already exists.[/dim]")

    # 4. Create Bedrock Guardrail (idempotent)
    guardrail_name = f"ftl-{project_name}"
    bedrock = boto3.client("bedrock", region_name=region)
    console.print(f"  Bedrock Guardrail: {guardrail_name}")
    guardrail_id = None
    guardrail_version = "1"
    try:
        gr_response = bedrock.create_guardrail(
            name=guardrail_name,
            description=f"FTL credential and content safety guardrail for {project_name}",
            sensitiveInformationPolicyConfig={
                "piiEntitiesConfig": [
                    {"type": t, "action": "BLOCK"}
                    for t in [
                        "AWS_ACCESS_KEY",
                        "API_KEY",
                        "USERNAME",
                        "PASSWORD",
                        "EMAIL",
                        "CREDIT_DEBIT_CARD_NUMBER",
                    ]
                ]
            },
            blockedInputMessaging="Input blocked by FTL guardrail.",
            blockedOutputsMessaging="Output blocked by FTL guardrail.",
        )
        guardrail_id = gr_response["guardrailId"]
        ver_response = bedrock.create_guardrail_version(guardrailIdentifier=guardrail_id)
        guardrail_version = str(ver_response["version"])
        console.print(f"    [green]Created (id={guardrail_id}, version={guardrail_version}).[/green]")
    except bedrock.exceptions.ConflictException:
        # Find existing by name
        paginator = bedrock.get_paginator("list_guardrails")
        for page in paginator.paginate():
            for gr in page.get("guardrails", []):
                if gr["name"] == guardrail_name:
                    guardrail_id = gr["id"]
                    guardrail_version = str(gr.get("version", "1"))
                    break
            if guardrail_id:
                break
        console.print(f"    [dim]Already exists (id={guardrail_id}).[/dim]")

    # 5. Prompt for optional Secrets Manager prefix
    sm_prefix = click.prompt(
        "  Secrets Manager prefix (leave blank to skip)",
        default="",
        show_default=False,
    ).strip()

    # 6. Read existing config, merge new keys, write back
    existing = {}
    if config_path.exists():
        try:
            existing = json.loads(config_path.read_text())
        except (json.JSONDecodeError, OSError):
            pass

    existing["snapshot_backend"] = "s3"
    existing["s3_bucket"] = bucket_name
    existing["cloudwatch_log_group"] = log_group
    if guardrail_id:
        existing["guardrail_id"] = guardrail_id
        existing["guardrail_version"] = guardrail_version
    if sm_prefix:
        existing["secrets_manager_prefix"] = sm_prefix

    config_path.write_text(json.dumps(existing, indent=2) + "\n")
    console.print(f"\n[bold green]Done. .ftlconfig updated.[/bold green]")
    console.print(f"  [dim]{config_path}[/dim]")


@main.command("config")
@click.option("--aws", "aws_mode", is_flag=True,
              help="Configure FTL to use AWS for snapshots, tracing, secrets, and guardrails.")
def config_cmd(aws_mode):
    """Configure FTL settings."""
    if not aws_mode:
        click.echo("Usage: ftl config --aws")
        return
    _configure_aws()


def shell():
    """Interactive FTL shell with session support."""
    console = Console()

    if not find_config():
        console.print("[red]No .ftlconfig found. Run 'ftl init' first.[/red]")
        raise SystemExit(1)

    config = load_config()
    console.print("[bold]FTL Shell[/bold]")
    console.print(f"[dim]Agent: {config['agent']} | Tester: {config['tester']}[/dim]")
    console.print("[dim]Type a task to start. Commands: test, diff, merge, reject, list, restore <id>, exit[/dim]\n")

    from ftl.snapshot import create_snapshot_store
    snapshot_store = create_snapshot_store(config)
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

        console.print("\n[bold]Session active.[/bold] Commands: test, diff, merge, reject")
        console.print("[dim]Or type a follow-up instruction for the agent.[/dim]")
