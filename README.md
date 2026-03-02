# FTL

**Zero-trust control plane for AI coding agents.** Run Claude Code, Codex, Aider, or Kiro inside an isolated Docker sandbox with shadow credentials, parallel adversarial testing, and human-in-the-loop approval — without ever giving the agent access to your real secrets or filesystem.

---

## Quickstart

```bash
pip install -e .
ftl setup          # pull sandbox image, pick agent + tester, save API key
cd your-project
ftl init           # create .ftlconfig
ftl code 'your task here'
```

---

## How It Works

```
ftl code "build login component with Supabase auth"
```

```
1. SNAPSHOT      — rsync project state to ~/.ftl/snapshots/<id>
2. BOOT          — reuse persistent container or start fresh (per project)
3. INJECT        — shadow credentials replace real keys inside sandbox
4. AGENT ∥ TESTS — coding agent runs; adversarial tests generate in parallel
5. RUN TESTS     — pre-generated tests execute the moment the agent finishes
6. LINT          — diff scanned for credentials and dangerous operations
7. DIFF          — computed on demand; file-level review of all changes
8. APPROVE       — human reviews, asks questions, merges or rejects
```

The agent runs entirely inside Docker. It never sees your real API keys or your host filesystem. Nothing touches your project without explicit approval.

---

## Getting Started

You need **Python 3.11+**, **Docker Desktop** (or Docker Engine on Linux), and an **Anthropic API key** ([console.anthropic.com](https://console.anthropic.com)). On Linux, also install rsync (`apt install rsync`).

### Step 1 — Install

```bash
git clone https://github.com/vvennela/ftl
cd ftl
pip install -e .
```

### Step 2 — Setup (one time)

```bash
ftl setup
```

Pulls the sandbox image from Docker Hub, asks which agent and tester model you want, and saves your API key:

```
Which agent do you want to use?
  1. Claude Code  (Anthropic, recommended)
  2. Codex        (OpenAI)
  3. Aider        (open-source)
  4. Kiro         (AWS)
  Choice [1]:

Which model for test generation?
  1. Anthropic API — claude-haiku  (uses ANTHROPIC_API_KEY)
  2. AWS Bedrock   — claude-sonnet (uses AWS credentials)
  3. Skip test generation
  Choice [1]:
```

Your choices are saved globally to `~/.ftl/config.json` and used as defaults for every new project. Credentials are saved to `~/.ftl/credentials` and loaded automatically on every invocation — no need to `export` each session.

**Docker Hub images** — pulled automatically based on your agent selection:

```
vvenne/ftl:latest   — Claude Code
vvenne/ftl:codex    — Codex
vvenne/ftl:aider    — Aider
vvenne/ftl:kiro     — Kiro
vvenne/ftl:full     — all agents
```

### Step 3 — Initialize your project

```bash
cd your-project
ftl init
```

Creates `.ftlconfig` with defaults. Edit it to change the agent, tester model, or any other setting.

### Step 4 — Run a task

```bash
ftl code 'create a Stripe payment module'   # use single quotes if the task contains $
```

FTL snapshots your project, boots the sandbox, runs the agent while generating tests in parallel, then shows you a diff to review:

- `a` — approve and merge changes to your project
- `r` — reject and discard all changes
- Any other input — ask the model a question about the diff (e.g. "does this handle null inputs?")

Steps 1–2 are one-time machine setup. Step 3 is once per project.

### Adding credentials later

```bash
ftl auth ANTHROPIC_API_KEY sk-ant-...
ftl auth OPENAI_API_KEY sk-...
ftl auth AWS_BEARER_TOKEN_BEDROCK ABSK...
```

Or put them in a `.env` file in your project root — FTL reads it automatically.

---

## Interactive Shell

```bash
ftl
```

```
ftl> build a login page with email and password

ftl[active]> add form validation
ftl[active]> diff     — show all changes since snapshot
ftl[active]> test     — re-run tests manually
ftl[active]> merge    — review diff, approve/reject, merge to project
ftl[active]> reject   — discard all changes
```

Follow-up instructions continue the same agent conversation in the same container. No cold boot between tasks.

---

## Agents

FTL supports four coding agents. Select one during `ftl setup` or set `agent` in `.ftlconfig`.

| Agent | Key | Requires |
|---|---|---|
| Claude Code | `"claude-code"` | `ANTHROPIC_API_KEY` |
| Codex | `"codex"` | `OPENAI_API_KEY` |
| Aider | `"aider"` | `OPENAI_API_KEY` or `ANTHROPIC_API_KEY` |
| Kiro | `"kiro"` | AWS credentials + browser login |

**Kiro authentication:** Kiro uses browser-based AWS SSO. After your first `ftl code` run, authenticate inside the container:

```bash
docker exec -it $(docker ps -qf ancestor=ftl-sandbox) kiro-cli login
```

Credentials persist in the container until it is removed.

---

## Configuration

`ftl init` creates `.ftlconfig` in your project root. All fields:

```json
{
  "agent": "claude-code",
  "tester": "claude-haiku-4-5-20251001",

  "shadow_env": ["MY_EXTRA_SECRET"],
  "agent_env": ["SOME_VAR_TO_FORWARD"],

  "setup": "pip install -r requirements.txt 2>/dev/null; npm install --silent 2>/dev/null; true",

  "snapshot_backend": "local",
  "s3_bucket": "my-ftl-snapshots",
  "cloudwatch_log_group": "/ftl/myproject",
  "secrets_manager_prefix": "/myproject/prod/",
  "guardrail_id": "abc123def456",
  "guardrail_version": "1"
}
```

| Field | Required | Description |
|---|---|---|
| `agent` | Yes | Agent to run: `"claude-code"`, `"codex"`, `"aider"`, `"kiro"` |
| `tester` | Yes | LiteLLM model string for adversarial test generation |
| `shadow_env` | No | Extra env var names to shadow beyond what's in `.env` |
| `agent_env` | No | Extra env vars from your host to forward into the sandbox (for agent auth) |
| `setup` | No | Shell command run once on a **fresh container only**, before the agent starts. Use for installing project dependencies. |
| `snapshot_backend` | No | `"local"` (default) or `"s3"` |
| `s3_bucket` | No | S3 bucket name. Required when `snapshot_backend` is `"s3"` |
| `cloudwatch_log_group` | No | CloudWatch log group for session traces. Created automatically by `ftl config --aws`. |
| `secrets_manager_prefix` | No | AWS Secrets Manager prefix (e.g. `"/myproject/prod/"`). When set, replaces `.env` as the secrets source. |
| `guardrail_id` | No | Bedrock Guardrail ID. When set, replaces the local credential linter — hard-blocks merge if the guardrail intervenes. |
| `guardrail_version` | No | Guardrail version to apply (default: `"DRAFT"`). Set automatically by `ftl config --aws`. |

### Choosing a tester model

Any [LiteLLM-supported model](https://docs.litellm.ai/docs/providers) works:

```json
{ "tester": "claude-haiku-4-5-20251001" }                    // Anthropic direct (default)
{ "tester": "bedrock/us.anthropic.claude-sonnet-4-6" }        // AWS Bedrock
{ "tester": "openai/gpt-4o-mini" }                            // OpenAI
```

The tester runs in parallel with the agent, so latency is free regardless of model.

### Project dependencies (setup hook)

If your project requires `pip install` or `npm install`, add a `setup` command. It runs once when a fresh container is created:

```json
{
  "setup": "pip install -r requirements.txt 2>/dev/null; npm install --silent 2>/dev/null; true"
}
```

The `true` at the end prevents a missing `requirements.txt` or `package.json` from failing the boot. On warm container reuse, this command is skipped — packages persist in `/home/ftl/.local/` across tasks.

---

## Shadow Credentials

Your `.env` has real keys:

```
STRIPE_SECRET_KEY=sk_live_abc123
OPENAI_API_KEY=sk-proj-...
```

FTL generates shadow values and injects them into the sandbox:

```
STRIPE_SECRET_KEY=ftl_shadow_stripe_secret_key_7f8a2b3c
OPENAI_API_KEY=ftl_shadow_openai_api_key_4d9e2a1f
```

The agent writes code using these shadow values. Your real `.env` never enters the container. Before merge, FTL's lint scanner checks the diff for:

- Hardcoded shadow values or known credential patterns (Stripe, Anthropic, AWS, GitHub, etc.)
- Dangerous SQL: `DROP TABLE`, `DROP DATABASE`, `TRUNCATE`, `DELETE FROM` without `WHERE`
- Dangerous shell: `rm -rf`, `shred`, `dd if=`, `chmod -R 777`

All findings are advisory — flagged for your review, never a hard block (unless Bedrock Guardrails is configured).

### Network Proxy (optional)

Install `cryptography` to enable live credential swapping at the network layer:

```bash
pip install -e ".[proxy]"
```

When active, FTL starts an HTTP/HTTPS intercepting proxy on the host. The container routes all outbound traffic through it. For every outgoing request, the proxy replaces shadow credential bytes with the real values before they reach the upstream server — so live API calls work correctly while the agent never learns your real keys.

```
Container sends:  Authorization: Bearer ftl_shadow_stripe_secret_key_7f8a2b3c
Proxy rewrites:   Authorization: Bearer sk_live_abc123
Stripe receives:  Authorization: Bearer sk_live_abc123  ✓
```

HTTPS traffic is handled via MITM using a per-session ephemeral CA installed in the container's trust store at boot. The CA key is never written to disk on the host.

---

## AWS Setup

FTL has four independently configurable AWS-backed capabilities. You can use any combination by editing `.ftlconfig` directly, or let `ftl config --aws` provision everything at once.

| Capability | Local (default) | AWS mode |
|---|---|---|
| Snapshots | rsync to `~/.ftl/snapshots/` | S3 |
| Traces | `~/.ftl/logs.jsonl` | CloudWatch |
| Secrets | Read from `.env` | Secrets Manager |
| Diff safety | Local credential linter | Bedrock Guardrails |

### Prerequisites

```bash
pip install -e ".[aws]"
```

Configure AWS credentials using any standard method:

```bash
# Option 1: AWS CLI
aws configure

# Option 2: environment variables
export AWS_ACCESS_KEY_ID=...
export AWS_SECRET_ACCESS_KEY=...
export AWS_DEFAULT_REGION=us-east-1

# Option 3: ftl auth (persists across sessions)
ftl auth AWS_ACCESS_KEY_ID ...
ftl auth AWS_SECRET_ACCESS_KEY ...
ftl auth AWS_DEFAULT_REGION us-east-1
```

### One-shot wizard

```bash
ftl config --aws
```

This provisions all four AWS resources and writes the config in one step:

1. Reads your account ID and region via STS
2. Creates S3 bucket `ftl-<account>-<region>` (idempotent)
3. Creates CloudWatch log group `/ftl/<project-name>` (idempotent)
4. Creates a Bedrock Guardrail `ftl-<project-name>` with PII and credential blocking
5. Prompts for an optional Secrets Manager prefix
6. Merges all new keys into your `.ftlconfig`

Run it again at any time — it will not duplicate existing resources.

### S3 Snapshots

Snapshots are stored as gzipped tarballs at `s3://<bucket>/snapshots/<project-hash>/<id>.tar.gz`. The local cache at `~/.ftl/snapshots/` is kept so the Docker container can mount snapshots without a per-task S3 download.

To configure manually, add to `.ftlconfig`:

```json
{
  "snapshot_backend": "s3",
  "s3_bucket": "my-ftl-snapshots"
}
```

### Secrets Manager

When `secrets_manager_prefix` is set, FTL fetches secrets from AWS Secrets Manager instead of reading `.env`. Secrets are loaded at session start, shadow values are generated from them, and the credential-swap proxy works identically from that point.

```json
{ "secrets_manager_prefix": "/myproject/prod/" }
```

Secrets with JSON object values (e.g. `{"API_KEY": "...", "DB_PASSWORD": "..."}`) are expanded into individual keys. Plain-string secrets use the last path segment as the key name, uppercased.

### Bedrock Guardrails

When `guardrail_id` is set, FTL applies a Bedrock Guardrail to the full diff text before the human review step, replacing the local credential linter.

```json
{
  "guardrail_id": "abc123def456",
  "guardrail_version": "1"
}
```

If the guardrail intervenes (e.g. detects an AWS key, API token, or PII), the merge is **hard-blocked** and the changes are discarded — no human review prompt. If it passes, review proceeds normally. Findings (PII type, content policy category) are printed before the block decision.

### CloudWatch Tracing

When `cloudwatch_log_group` is set, FTL emits structured JSON events to CloudWatch Logs for each session stage (snapshot, boot, agent, tests).

```json
{ "cloudwatch_log_group": "/ftl/myproject" }
```

---

## Tracing

FTL prints elapsed time at each stage (snapshot, boot, agent, tests) automatically.

For full LLM observability, enable [Langfuse](https://langfuse.com):

```bash
pip install -e ".[tracing]"

ftl auth LANGFUSE_PUBLIC_KEY pk-lf-...
ftl auth LANGFUSE_SECRET_KEY sk-lf-...
ftl auth LANGFUSE_HOST https://cloud.langfuse.com   # optional
```

Every `litellm.completion()` call (tester, diff review, Q&A) is traced automatically.

---

## Sandbox Internals

```
~/.ftl/
├── snapshots/<id>/     — project state at task start (rsync, respects .ftlignore)
├── containers/<hash>   — persistent container ID per project path
├── config.json         — global defaults set by ftl setup
└── credentials         — ftl auth storage (mode 600)
```

**Container lifecycle:**
- Persists across runs, keyed by project path
- Workspace (`/workspace`) wiped and restored from snapshot on each task
- Everything outside `/workspace` persists: user-installed packages in `/home/ftl/.local/`, global npm installs, agent conversation history

**What persists across tasks in the same container:**

| Location | On task reset | Notes |
|---|---|---|
| `/workspace/` | Wiped and restored | Project files |
| `/home/ftl/.local/` | Persists | `pip install` packages |
| `/usr/lib/python3/` | Persists | Pre-installed: stripe, requests, httpx, boto3, openai, anthropic, pydantic, pytest |
| Global node_modules | Persists | `npm install -g` |
| `/home/ftl/.claude/` | Persists | Claude Code conversation history |

**Node.js warm start:** On every boot, FTL runs `claude --version` in the background to load Claude Code's modules into the Linux page cache. By the time you see "Running agent...", Node.js is already warm — eliminating the 5-8s cold-start penalty on the first task.

---

## CLI Reference

```bash
ftl setup                         # pull sandbox image, choose agent + tester, save API key

ftl init                          # create .ftlconfig in current project
ftl code 'task description'       # run task, review, merge/reject
ftl                               # interactive shell

ftl config --aws                  # provision AWS resources and write config

ftl snapshots                     # list snapshots for current project
ftl snapshots --all               # list all snapshots
ftl snapshots clean --last 10     # delete 10 most recent
ftl snapshots clean --all -y      # delete all (no prompt)

ftl auth KEY VALUE                # save credential to ~/.ftl/credentials
ftl logs                          # show session audit log
ftl logs --all                    # across all projects
```

---

## Project Structure

```
FTL/
├── Dockerfile                   # Base image (Claude Code). Agent tags built on top.
├── scripts/
│   └── publish.sh               # Build and push all Docker Hub tag variants
├── ftl/
│   ├── cli.py                   # CLI entry points, setup wizard, interactive shell
│   ├── orchestrator.py          # Session lifecycle: snapshot → boot → agent ∥ tester → merge
│   ├── planner.py               # Tester: parallel test generation + execution
│   ├── proxy.py                 # HTTP/HTTPS credential-swap proxy (optional)
│   ├── render.py                # stream-json renderer: per-tool live counters
│   ├── diff.py                  # Diff computation, display, interactive review with LLM Q&A
│   ├── lint.py                  # Credential + dangerous operation scanner
│   ├── secrets.py               # AWS Secrets Manager loader (replaces .env in AWS mode)
│   ├── guardrails.py            # Bedrock Guardrail apply (replaces lint in AWS mode)
│   ├── tracing.py               # Langfuse tracing, StageTimer, AgentHeartbeat
│   ├── config.py                # .ftlconfig loader + ~/.ftl/config.json global defaults
│   ├── credentials.py           # Shadow credential generation, ~/.ftl/credentials store
│   ├── ignore.py                # Shared ignore rules (ALWAYS_IGNORE + .ftlignore)
│   ├── log.py                   # Session audit log
│   ├── agents/
│   │   ├── base.py              # Abstract agent interface
│   │   ├── claude_code.py       # Claude Code adapter (stream-json, --verbose)
│   │   ├── codex.py             # Codex adapter
│   │   ├── aider.py             # Aider adapter
│   │   └── kiro.py              # Kiro adapter
│   ├── sandbox/
│   │   ├── base.py              # Abstract sandbox interface
│   │   └── docker.py            # Docker backend: persistent containers, Node.js pre-warm
│   └── snapshot/
│       ├── base.py              # Abstract snapshot interface
│       ├── local.py             # Local rsync-based snapshots
│       └── s3.py                # S3-backed snapshots (requires boto3)
```

---

## Vision

The current coding agent is one capability. The bigger picture: a **planner** (cheap, fast LLM) that reads a natural-language goal and routes it to the right tools.

```
"Write a Stripe payment module, open a PR, and Slack Brian it's ready."
```

The planner decomposes this into structured actions:

```json
{"action": "agent",  "task": "write a Stripe payment module with webhook handling"}
{"action": "tool",   "name": "github", "params": {"op": "open_pr", "title": "Add Stripe payment module"}}
{"action": "tool",   "name": "slack",  "params": {"to": "Brian", "message": "Stripe PR is ready for review"}}
```

Each action is dispatched in sequence. Coding tasks go through the full FTL sandbox loop (snapshot → agent → tests → diff → approve). Tool actions (email, Slack, GitHub) are confirmed before execution.

**Contact resolution:** `~/.ftl/world.yaml` maps natural names to real addresses, populated from your top contacts across email, iMessage, and Slack. "Brian" resolves to `brian@company.com` and `@brian` in your workspace.

**Why the planner is not a monolith:** The coding agent already handles tool use, file editing, and multi-step reasoning internally. The planner sits above it — routing between *types* of action, not micromanaging code generation. This keeps the two concerns cleanly separated.

---

## Roadmap

**Done:**
- Isolated Docker sandbox with persistent containers (no cold-boot penalty per task)
- Shadow credential injection — real keys never enter the container
- Node.js pre-warm — eliminates 5-8s agent cold-start on first task
- Per-tool live progress display (stream-json renderer with elapsed counters)
- Parallel adversarial test generation (tester runs while agent codes)
- Linux-internal diff (runs inside container, no host-side Python/VirtioFS overhead)
- Live streaming agent output (line-by-line, not blocking until completion)
- rsync-based snapshots with ignore rules
- S3 snapshot backend for durability and cross-machine access
- Credential + dangerous operation linter (DROP TABLE, rm -rf, etc.)
- HTTP/HTTPS credential-swap proxy (MITM, ephemeral CA, shadow→real at network layer)
- Session audit log
- AWS Secrets Manager integration — replaces `.env` as secrets source in AWS mode
- Bedrock Guardrails integration — hard-blocks merge on detected secrets or PII
- `ftl config --aws` one-shot wizard — provisions S3, CloudWatch, Guardrail, prompts for SM prefix
- CloudWatch session tracing
- Multi-agent support: Claude Code, Codex, Aider, Kiro
- `ftl setup` wizard — agent selection, tester model, Docker Hub pull
- Published Docker Hub images (`vvenne/ftl:latest`, `:codex`, `:aider`, `:kiro`, `:full`)

**Next:**
- Tool dispatch layer — planner routes between coding, email, Slack, GitHub
- Contact resolution from `~/.ftl/world.yaml` (top email/Slack/iMessage contacts)
- Remote execution — Firecracker/Lambda sandbox backend; S3 snapshots already done

**Later:**
- Virtualization.framework sandbox (sub-second boot via VM snapshots, no Docker dependency)
- DynamoDB audit log
- Multi-agent parallelism — planner fans out independent tasks

---

## Philosophy

> Agents are untrustworthy by construction. FTL is the layer that makes them safe to use anyway.

The agent cannot have skin in the game. The human must. Every change requires explicit approval before it touches the real filesystem.

---

## License

MIT
