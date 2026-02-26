# FTL

**Zero-trust control plane for AI coding agents.** Run Claude Code inside an isolated Docker sandbox with shadow credentials, parallel adversarial testing, and human-in-the-loop approval — without ever giving the agent access to your real secrets or filesystem.

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
6. DIFF          — computed on demand; file-level review of all changes
7. APPROVE       — human reviews, asks questions, merges or rejects
```

The agent runs entirely inside Docker. It never sees your real API keys or your host filesystem. Nothing touches your project without explicit approval.

---

## Prerequisites

- **Python 3.11+**
- **Docker Desktop** (Mac/Windows) or Docker Engine (Linux)
- **An Anthropic API key** — get one at [console.anthropic.com](https://console.anthropic.com)
- **rsync** — pre-installed on macOS; `apt install rsync` on Linux

For the tester model, you need either an Anthropic API key (direct) or AWS Bedrock access.

---

## Installation

```bash
# 1. Clone the repo
git clone https://github.com/vvennela/ftl
cd ftl

# 2. Install the package
pip install -e .

# 3. Build the sandbox Docker image (one time, ~2 min)
docker build -t ftl-sandbox .
```

---

## Setup

### Store your credentials

`ftl auth` writes to `~/.ftl/credentials` (mode 600) and loads automatically on every invocation — no need to `export` on each shell session.

```bash
# Anthropic API key (required for Claude Code agent)
ftl auth ANTHROPIC_API_KEY sk-ant-...

# Tester model — pick one:
ftl auth AWS_BEARER_TOKEN_BEDROCK ABSK...   # AWS Bedrock (recommended)
# or just use ANTHROPIC_API_KEY for both agent and tester
```

Alternatively, use environment variables or a `.env` file in your project root — FTL reads `.env` automatically for shadow credential generation.

### Initialize a project

```bash
cd your-project
ftl init
```

This creates `.ftlconfig` in the project root. Edit it to configure your agent and tester:

```json
{
  "agent": "claude-code",
  "tester": "bedrock/us.anthropic.claude-sonnet-4-6"
}
```

---

## Running a Task

```bash
ftl code 'create a Stripe payment module'
```

Use single quotes if the task contains `$`.

FTL will:
1. Snapshot your project
2. Boot the sandbox (warm reuse if available, fresh container otherwise)
3. Run the agent while generating tests in parallel
4. Show live per-tool progress as the agent works
5. Run the generated tests
6. Display the diff and prompt for review

At the review prompt:
- `a` — approve and merge changes to your project
- `r` — reject and discard all changes
- Any question — ask the model about the diff (e.g. "does this handle null inputs?")

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

## Configuration

`ftl init` creates `.ftlconfig` in your project root. All fields:

```json
{
  "agent": "claude-code",
  "tester": "bedrock/us.anthropic.claude-sonnet-4-6",

  "shadow_env": ["MY_EXTRA_SECRET"],
  "agent_env": ["SOME_VAR_TO_FORWARD"],

  "setup": "pip install -r requirements.txt 2>/dev/null; npm install --silent 2>/dev/null; true",

  "snapshot_backend": "local",
  "s3_bucket": "my-ftl-snapshots"
}
```

| Field | Required | Description |
|---|---|---|
| `agent` | Yes | Agent to run. `"claude-code"` or `"kiro"` |
| `tester` | Yes | LiteLLM model string for adversarial test generation |
| `shadow_env` | No | Extra env var names to shadow beyond what's in `.env` |
| `agent_env` | No | Extra env vars from your host to forward into the sandbox (for agent auth) |
| `setup` | No | Shell command run once on a **fresh container only**, before the agent starts. Use for installing project dependencies. |
| `snapshot_backend` | No | `"local"` (default) or `"s3"` |
| `s3_bucket` | No | S3 bucket name. Required when `snapshot_backend` is `"s3"` |

### Choosing a tester model

Any [LiteLLM-supported model](https://docs.litellm.ai/docs/providers) works:

```json
{ "tester": "bedrock/us.anthropic.claude-sonnet-4-6" }   // AWS Bedrock
{ "tester": "anthropic/claude-haiku-4-5-20251001" }       // Anthropic direct
{ "tester": "openai/gpt-4o" }                             // OpenAI
```

The tester must be a different model than the agent. Bedrock is recommended for cost — it runs the tester in parallel with the agent so latency is free.

### Project dependencies (setup hook)

If your project requires `pip install` or `npm install`, add a `setup` command. It runs once when a fresh container is created:

```json
{
  "agent": "claude-code",
  "tester": "bedrock/us.anthropic.claude-sonnet-4-6",
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

The agent writes code using these shadow values. Your real `.env` never enters the container. Before merge, FTL's credential linter scans the diff for hardcoded shadow values and flags them.

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

## AWS Setup (S3 Snapshots)

Store snapshots in S3 for durability and cross-machine access:

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

Add to `.ftlconfig`:

```json
{
  "agent": "claude-code",
  "tester": "bedrock/us.anthropic.claude-sonnet-4-6",
  "snapshot_backend": "s3",
  "s3_bucket": "my-ftl-snapshots"
}
```

Snapshots are stored as gzipped tarballs at `s3://<bucket>/snapshots/<project-hash>/<id>.tar.gz`. The local cache at `~/.ftl/snapshots/` is kept so the Docker container can mount snapshots without a per-task S3 download.

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
└── credentials         — ftl auth storage (mode 600)
```

**Container lifecycle:**
- Persists across runs, keyed by project path
- Workspace (`/workspace`) wiped and restored from snapshot on each task
- Everything outside `/workspace` persists: user-installed packages in `/home/ftl/.local/`, global npm installs, Claude Code's conversation history

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
ftl init                          # create .ftlconfig in current directory
ftl code 'task description'       # run task, review, merge/reject
ftl                               # interactive shell

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
├── Dockerfile                   # Debian slim, Node 22, Python 3.11, Claude Code
├── ftl/
│   ├── cli.py                   # CLI entry points and interactive shell
│   ├── orchestrator.py          # Session lifecycle: snapshot → boot → agent ∥ tester → merge
│   ├── planner.py               # Tester: parallel test generation + execution
│   ├── proxy.py                 # HTTP/HTTPS credential-swap proxy (optional)
│   ├── render.py                # stream-json renderer: per-tool live counters
│   ├── diff.py                  # Diff computation, display, interactive review with LLM Q&A
│   ├── lint.py                  # Credential leak detection on diffs
│   ├── tracing.py               # Langfuse tracing, StageTimer, AgentHeartbeat
│   ├── config.py                # .ftlconfig loader (git-style directory walk)
│   ├── credentials.py           # Shadow credential generation, ~/.ftl/credentials store
│   ├── ignore.py                # Shared ignore rules (ALWAYS_IGNORE + .ftlignore)
│   ├── log.py                   # Session audit log
│   ├── agents/
│   │   ├── base.py              # Abstract agent interface
│   │   ├── claude_code.py       # Claude Code adapter (stream-json, --verbose)
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
- Credential linter — flags hardcoded shadow values in diffs before merge
- HTTP/HTTPS credential-swap proxy (MITM, ephemeral CA, shadow→real at network layer)
- Session audit log

**Next:**
- Tool dispatch layer — planner routes between coding, email, Slack, GitHub
- Contact resolution from `~/.ftl/world.yaml` (top email/Slack/iMessage contacts)
- Remote execution — Firecracker/Lambda sandbox backend; S3 snapshots already done

**Later:**
- Virtualization.framework sandbox (sub-second boot via VM snapshots, no Docker dependency)
- DynamoDB audit log
- Multi-agent parallelism — planner fans out independent tasks

---

## Rebuilding

Required after pulling changes that touch the Dockerfile:

```bash
pip install -e .
docker build -t ftl-sandbox .
```

---

## Philosophy

> Agents are untrustworthy by construction. FTL is the layer that makes them safe to use anyway.

The agent cannot have skin in the game. The human must. Every change requires explicit approval before it touches the real filesystem.

---

## License

MIT
