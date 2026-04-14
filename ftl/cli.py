import json
import os
import subprocess

# Suppress LiteLLM's startup banner and verbose stderr before any import triggers it
os.environ.setdefault("LITELLM_LOG", "ERROR")
from datetime import datetime
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table
from ftl.config import (
    load_config,
    load_global_config,
    init_config,
    find_config,
    save_global_config,
    load_project_config,
    save_project_config,
)
from ftl.credentials import load_ftl_credentials, save_ftl_credential, FTL_CREDENTIALS_FILE
from ftl.log import LOGS_FILE
from ftl.orchestrator import run_task, Session
from ftl.languages import (
    detect_project_language,
    detect_project_languages,
    detect_top_level_languages,
    SUPPORTED_LANGUAGES,
)


@click.group(invoke_without_command=True)
@click.version_option(version="0.1.0")
@click.option(
    "--config",
    "config_mode",
    type=click.Choice(["aws"], case_sensitive=False),
    help="One-shot config shortcut. Currently supports: aws",
)
@click.pass_context
def main(ctx, config_mode):
    """FTL: Zero-trust control plane for AI development."""
    load_ftl_credentials()
    if config_mode == "aws":
        _configure_aws()
        return
    if ctx.invoked_subcommand is None:
        shell()


@main.command()
def init():
    """Initialize FTL in the current project. Creates .ftlconfig with defaults."""
    if find_config():
        click.echo(".ftlconfig already exists.")
        return
    config_path = _init_project_config(Path.cwd())
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
        _init_project_config(Path.cwd())
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


def _has_saved_credential(key):
    """Return True if the credential is already available in env or ~/.ftl/credentials."""
    if key in os.environ:
        return True
    if FTL_CREDENTIALS_FILE.exists():
        for line in FTL_CREDENTIALS_FILE.read_text().splitlines():
            if line.startswith(f"{key}="):
                return True
    return False


def _resolve_init_language(project_path):
    """Auto-detect the project language, prompting only when detection is ambiguous."""
    detected = detect_project_language(project_path)
    if detected:
        return detected

    detected_languages = detect_project_languages(project_path)
    options = sorted(SUPPORTED_LANGUAGES)
    label = ", ".join(options)
    if detected_languages:
        prompt = (
            "Multiple project languages detected "
            f"({', '.join(detected_languages)}). Choose the primary verification language ({label})"
        )
    else:
        prompt = f"Project language could not be detected. Choose one ({label})"
    return click.prompt(
        prompt,
        type=click.Choice(options, case_sensitive=False),
        default="python",
        show_choices=False,
    ).lower()


def _prompt_language_map(project_path):
    suggestions = detect_top_level_languages(project_path)
    if not suggestions:
        return {}

    console = Console()
    console.print("[bold]Language mapping[/bold]  [dim](optional for mixed repos)[/dim]")
    console.print("  [dim]FTL can use different verification languages for different folders.[/dim]")

    overrides = {}
    for folder, suggested in sorted(suggestions.items()):
        if click.confirm(f"  Map [cyan]{folder}/[/cyan] to [green]{suggested}[/green]?", default=True):
            choice = click.prompt(
                f"  Language for {folder}/",
                type=click.Choice(sorted(SUPPORTED_LANGUAGES), case_sensitive=False),
                default=suggested,
                show_choices=False,
            ).lower()
            overrides[folder] = choice
    return overrides


def _init_project_config(target_path):
    detected_languages = detect_project_languages(target_path)
    language = detect_project_language(target_path)
    overrides = {}

    if language:
        config_path = init_config(path=target_path, language=language)
    else:
        if detected_languages:
            choice = click.prompt(
                "This repo looks mixed. Setup mode",
                type=click.Choice(["primary", "mapped"], case_sensitive=False),
                default="mapped",
                show_choices=False,
            ).lower()
            primary = _resolve_init_language(target_path)
            if choice == "mapped":
                overrides = _prompt_language_map(target_path)
            config_path = init_config(path=target_path, language=primary)
            if overrides:
                save_project_config({"language_overrides": overrides}, config_path)
        else:
            primary = _resolve_init_language(target_path)
            config_path = init_config(path=target_path, language=primary)

    return config_path


_AGENT_AUTH_PROMPTS = {
    "claude-code": {
        "title": "Anthropic API key",
        "detail": "(used by the coding agent)",
        "help": "Get one at https://console.anthropic.com",
        "key": "ANTHROPIC_API_KEY",
        "example": "ftl auth ANTHROPIC_API_KEY sk-ant-...",
    },
    "codex": {
        "title": "OpenAI API key",
        "detail": "(used by the Codex agent)",
        "help": "Set the key used by codex inside the sandbox.",
        "key": "OPENAI_API_KEY",
        "example": "ftl auth OPENAI_API_KEY sk-...",
    },
    "aider": {
        "title": "Agent API key",
        "detail": "(Aider needs OPENAI_API_KEY or ANTHROPIC_API_KEY)",
        "help": "OPENAI_API_KEY is prompted by default; you can swap to Anthropic later.",
        "key": "OPENAI_API_KEY",
        "example": "ftl auth OPENAI_API_KEY sk-...",
    },
}


def _ensure_agent_credential(console, agent_name):
    """Prompt for the selected agent's auth credential if it is not already configured."""
    prompt = _AGENT_AUTH_PROMPTS.get(agent_name)
    if not prompt:
        return

    key = prompt["key"]
    if _has_saved_credential(key):
        console.print(f"  [green]{key} already configured.[/green]")
        return

    console.print(f"[bold]{prompt['title']}[/bold]  [dim]{prompt['detail']}[/dim]")
    console.print(f"  [dim]{prompt['help']}[/dim]")
    value = click.prompt(f"  {key}", hide_input=True, default="", show_default=False)
    if value.strip():
        save_ftl_credential(key, value.strip())
        console.print(f"  [green]Saved {key} to ~/.ftl/credentials[/green]")
    else:
        console.print(f"  [yellow]Skipped. Set later: {prompt['example']}[/yellow]")


_REGISTRY = "vvenne/ftl"

# Agent choices for the setup wizard.
# (number, label, docker_hub_tag, agent_config_key, [local_fallback_snippets])
_AGENT_CHOICES = [
    ("1", "Claude Code  (Anthropic, recommended)", "latest", "claude-code", []),
    ("2", "Codex        (OpenAI)",                 "codex",  "codex",       ["codex"]),
    ("3", "Aider        (open-source)",             "aider",  "aider",       ["aider"]),
]

# Dockerfile snippets for local fallback builds.
_AGENT_SNIPPETS = {
    "codex": "RUN npm install -g @openai/codex && npm cache clean --force",
    "aider": "RUN pip3 install --break-system-packages aider-chat",
}

# Provider menu for tester/reviewer selection.
# (number, label, key, api_key_env_var_or_None)
# api_key_env_var=None means no key needed (Ollama=local, Bedrock=AWS creds)
_PROVIDER_CHOICES = [
    ("1", "Anthropic     (e.g. claude-haiku-4-5-20251001)",                          "anthropic", "ANTHROPIC_API_KEY"),
    ("2", "OpenAI        (e.g. gpt-4o-mini)",                                         "openai",    "OPENAI_API_KEY"),
    ("3", "Ollama        (e.g. ollama/llama3  — local, no key needed)",               "ollama",    None),
    ("4", "AWS Bedrock   (e.g. bedrock/us.anthropic.claude-haiku-4-5-20251001)",      "bedrock",   None),
    ("5", "Other         (any LiteLLM-compatible string)",                             "other",     None),
]


# Default tester model per agent — same provider, cheapest capable model.
# Shown as the pre-filled default in setup; user can override with Customize.
_AGENT_DEFAULT_TESTER = {
    "claude-code": "claude-haiku-4-5-20251001",
    "codex":       "gpt-4o-mini",
    "aider":       "gpt-4o-mini",
}

# API key needed for the default tester model (None = no key, e.g. Bedrock/Ollama).
_AGENT_DEFAULT_TESTER_KEY = {
    "claude-code": "ANTHROPIC_API_KEY",
    "codex":       "OPENAI_API_KEY",
    "aider":       "OPENAI_API_KEY",
}


def _pull_or_build(console, hub_tag, local_agents):
    """Pull ftlhq/ftl-sandbox:<hub_tag> from Docker Hub, tag as ftl-sandbox locally.
    Falls back to a local build (base Dockerfile + agent layers) if pull fails.
    """
    import tempfile

    hub_image = f"{_REGISTRY}:{hub_tag}"
    console.print(f"  Pulling {hub_image}...")
    pull = subprocess.run(["docker", "pull", hub_image], capture_output=True)
    if pull.returncode == 0:
        subprocess.run(["docker", "tag", hub_image, "ftl-sandbox"], check=True)
        console.print("  [green]Pulled.[/green]")
        return

    console.print("  [dim]Hub pull failed — building locally (one-time)...[/dim]")
    dockerfile_dir = Path(__file__).parent.parent
    result = subprocess.run(["docker", "build", "-t", "ftl-sandbox-base", str(dockerfile_dir)])
    if result.returncode != 0:
        console.print("[red]Base image build failed.[/red]")
        raise SystemExit(1)

    if not local_agents:
        subprocess.run(["docker", "tag", "ftl-sandbox-base", "ftl-sandbox"], check=True)
        console.print("  [green]Image ready.[/green]")
        return

    snippets = "\n".join(_AGENT_SNIPPETS[a] for a in local_agents if a in _AGENT_SNIPPETS)
    dockerfile_content = f"FROM ftl-sandbox-base\nUSER root\n{snippets}\nUSER ftl\n"

    with tempfile.NamedTemporaryFile(mode="w", suffix=".dockerfile", delete=False) as f:
        f.write(dockerfile_content)
        tmp_path = Path(f.name)
    try:
        result = subprocess.run(
            ["docker", "build", "-t", "ftl-sandbox", "-f", str(tmp_path), str(tmp_path.parent)],
        )
        if result.returncode != 0:
            console.print("[red]Agent layer build failed.[/red]")
            raise SystemExit(1)
    finally:
        tmp_path.unlink(missing_ok=True)

    console.print("  [green]Image ready.[/green]")


def _prompt_model(console, role, saved_keys):
    """Prompt the user to pick a provider and model for tester or reviewer.

    saved_keys: set of API key env var names already saved this session —
    skips re-prompting if the key was just entered for the tester.

    Returns (model_string, updated_saved_keys).
    """
    console.print(f"[bold]Which model for {role}?[/bold]")
    console.print("  [dim]Any LiteLLM-compatible string is accepted. See: https://docs.litellm.ai/docs/providers[/dim]")
    for num, label, _, _ in _PROVIDER_CHOICES:
        console.print(f"  {num}. {label}")
    console.print()
    choice = click.prompt("  Choice", default="1").strip()
    matched = next((p for p in _PROVIDER_CHOICES if p[0] == choice), _PROVIDER_CHOICES[0])
    _, _, provider_key, api_key_var = matched

    model = click.prompt("  Model").strip()
    if not model:
        console.print(f"  [yellow]Skipped {role}.[/yellow]")
        return "", saved_keys

    # Prompt for API key if needed and not already saved this session
    if api_key_var and api_key_var not in saved_keys:
        existing = os.environ.get(api_key_var) or (
            next(
                (line.split("=", 1)[1] for line in
                 (FTL_CREDENTIALS_FILE.read_text().splitlines() if FTL_CREDENTIALS_FILE.exists() else [])
                 if line.startswith(f"{api_key_var}=")),
                None,
            )
        )
        if existing:
            console.print(f"  [green]{api_key_var} already configured.[/green]")
            saved_keys.add(api_key_var)
        else:
            key = click.prompt(f"  {api_key_var}", hide_input=True, default="", show_default=False)
            if key.strip():
                save_ftl_credential(api_key_var, key.strip())
                console.print(f"  [green]{api_key_var} saved to ~/.ftl/credentials[/green]")
                saved_keys.add(api_key_var)
            else:
                console.print(f"  [yellow]Skipped. Set later: ftl auth {api_key_var} <value>[/yellow]")

    console.print(f"  [green]{role.capitalize()}: {model}[/green]")
    return model, saved_keys


@main.command()
def setup():
    """One-command setup: choose agent, tester, reviewer, pull sandbox image, save API keys."""
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

    # 2. Agent selection
    console.print()
    image_exists = bool(
        subprocess.run(
            ["docker", "images", "-q", "ftl-sandbox:latest"],
            capture_output=True, text=True,
        ).stdout.strip()
    )

    global_cfg = load_global_config()
    chosen_agent_key = global_cfg.get("agent", "claude-code")
    if image_exists and not click.confirm(
        "  ftl-sandbox image already exists. Reconfigure?", default=False
    ):
        console.print("  [dim]Skipping image setup.[/dim]")
    else:
        console.print()
        console.print("[bold]Which agent do you want to use?[/bold]")
        for num, label, _, _, _ in _AGENT_CHOICES:
            console.print(f"  {num}. {label}")
        console.print()
        choice = click.prompt("  Choice", default="1").strip()
        matched = next((c for c in _AGENT_CHOICES if c[0] == choice), _AGENT_CHOICES[0])
        _, _, chosen_tag, chosen_agent_key, chosen_local_agents = matched
        console.print()
        _pull_or_build(console, chosen_tag, chosen_local_agents)
        save_global_config({"agent": chosen_agent_key})

    # 3. Agent credential
    console.print()
    _ensure_agent_credential(console, chosen_agent_key)

    # 4. Tester + reviewer model
    console.print()
    saved_keys = {
        prompt["key"]
        for prompt in _AGENT_AUTH_PROMPTS.values()
        if _has_saved_credential(prompt["key"])
    }
    default_tester = _AGENT_DEFAULT_TESTER.get(chosen_agent_key, "")
    if default_tester:
        console.print(f"[bold]Tester / reviewer model[/bold]  [dim](runs tests and reviews diffs)[/dim]")
        console.print(f"  Default: [cyan]{default_tester}[/cyan]")
        if click.confirm("  Customize?", default=False):
            tester_model, saved_keys = _prompt_model(console, "tester", saved_keys)
        else:
            tester_model = default_tester
            console.print(f"  [green]Using {tester_model}[/green]")
            default_key = _AGENT_DEFAULT_TESTER_KEY.get(chosen_agent_key)
            if default_key and not _has_saved_credential(default_key):
                val = click.prompt(f"  {default_key}", hide_input=True, default="", show_default=False)
                if val.strip():
                    save_ftl_credential(default_key, val.strip())
                    console.print(f"  [green]{default_key} saved.[/green]")
                    saved_keys.add(default_key)
    else:
        tester_model, saved_keys = _prompt_model(console, "tester", saved_keys)
    save_global_config({"tester": tester_model, "reviewer": tester_model})

    # 6. Done
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


@main.group("config", invoke_without_command=True)
@click.option("--aws", "aws_mode", is_flag=True,
              help="Configure FTL to use AWS for snapshots, tracing, secrets, and guardrails.")
@click.pass_context
def config_cmd(ctx, aws_mode):
    """View and update project config."""
    if aws_mode:
        _configure_aws()
        return
    if ctx.invoked_subcommand is None:
        config_show()


@config_cmd.command("show")
def config_show():
    """Show the current project config."""
    console = Console()
    config_path = find_config()
    if not config_path:
        console.print("[red]No .ftlconfig found. Run 'ftl init' first.[/red]")
        raise SystemExit(1)
    console.print_json(data=load_project_config(config_path))


@config_cmd.command("language")
@click.argument("language", type=click.Choice(sorted(SUPPORTED_LANGUAGES), case_sensitive=False))
def config_language(language):
    """Set the primary project language."""
    console = Console()
    config_path = find_config()
    if not config_path:
        console.print("[red]No .ftlconfig found. Run 'ftl init' first.[/red]")
        raise SystemExit(1)
    save_project_config({"language": language.lower()}, config_path)
    console.print(f"[green]Primary language set to {language.lower()}.[/green]")


@config_cmd.command("map")
@click.argument("path_prefix")
@click.argument("language", type=click.Choice(sorted(SUPPORTED_LANGUAGES), case_sensitive=False))
def config_map(path_prefix, language):
    """Map a subdirectory to a language for mixed repos."""
    console = Console()
    config_path = find_config()
    if not config_path:
        console.print("[red]No .ftlconfig found. Run 'ftl init' first.[/red]")
        raise SystemExit(1)
    cfg = load_project_config(config_path)
    overrides = dict(cfg.get("language_overrides", {}))
    overrides[path_prefix.strip("/")] = language.lower()
    save_project_config({"language_overrides": overrides}, config_path)
    console.print(f"[green]Mapped {path_prefix.strip('/')}/ to {language.lower()}.[/green]")


def shell():
    """Interactive FTL shell with session support."""
    console = Console()

    if not find_config():
        console.print("[yellow]No .ftlconfig found in this directory.[/yellow]")
        if click.confirm("  Initialize FTL here?", default=True):
            config_path = _init_project_config(Path.cwd())
            console.print(f"  [green]Created {config_path}[/green]\n")
        else:
            raise SystemExit(0)

    config = load_config()
    console.print("Welcome to...")
    console.print("[bold italic blue]███████╗████████╗██╗[/bold italic blue]")
    console.print("[bold italic blue]██╔════╝╚══██╔══╝██║[/bold italic blue]")
    console.print("[bold italic blue]█████╗     ██║   ██║[/bold italic blue]")
    console.print("[bold italic blue]██╔══╝     ██║   ██║[/bold italic blue]")
    console.print("[bold italic blue]██║        ██║   ███████╗[/bold italic blue]")
    console.print("[bold italic blue]╚═╝        ╚═╝   ╚══════╝[/bold italic blue]")
    console.print()
    console.print(f"[dim]Agent: {config['agent']} | Tester: {config['tester']}[/dim]")
    console.print("[dim]Type a task to start. Commands: test, diff, merge, reject, list, restore <id>, exit[/dim]\n")

    from ftl.snapshot import create_snapshot_store
    snapshot_store = create_snapshot_store(config)
    session = Session()
    session.preboot()

    while True:
        prompt = "ftl[active]> " if session and session.is_active and session.task else "ftl> "
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
        if session and session.is_active and session.task:
            if user_input == "test":
                session.run_tests()
                continue

            if user_input == "diff":
                session.show_diff()
                continue

            if user_input in ("merge", "done"):
                session.merge(allow_continue=True)
                if not session.is_active:
                    session = Session()
                    session.preboot()
                continue

            if user_input == "reject":
                session.reject()
                session = Session()
                session.preboot()
                continue

            # Anything else is a follow-up message to the planner
            session.follow_up(user_input)
            continue

        # No active session — treat input as a new task
        session.start(user_input)

        console.print("\n[bold]Session active.[/bold] Commands: test, diff, merge, reject")
        console.print("[dim]Or type a follow-up instruction for the agent.[/dim]")
