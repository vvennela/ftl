<h1 align="center">FTL 🚀</h1>

<p align="center"><strong>Zero-trust control plane for AI coding agents.</strong></p>

<p align="center">Run Claude Code, Codex, or Aider inside an isolated Docker sandbox with shadow credentials, parallel adversarial testing, and human-in-the-loop approval.</p>

<p align="center">Your agent gets real work done. It does not get your real secrets, direct filesystem access, or automatic merge power.</p>

---

## Why FTL

Most agent wrappers optimize for convenience first and safety later. FTL is built for the opposite case: you want the speed of Claude Code or Codex, but you do not want to hand an autonomous coding tool your machine, your credentials, and unchecked write access.

With FTL:

- Your agent runs inside Docker, not on your host
- Real credentials stay outside the sandbox
- Tests and review happen before merge
- Destructive operations and leaked secrets are flagged before approval
- The human stays in control of what lands in the repo

## Quickstart

```bash
pip install -e .
ftl setup              # pick agent, pull sandbox image, save API key
cd your-project
ftl init
ftl code 'your task'
```

If you just want the mental model:

1. `ftl init` adds a small project config
2. `ftl code 'build X'` snapshots your repo and starts the sandbox
3. The agent writes code while tests and review run in parallel
4. You inspect the diff and choose what gets merged

The result is an agent workflow that still feels fast, but is much harder to misuse accidentally.

---

## Getting Started

You need **Python 3.11+**, **Docker Desktop** (or Docker Engine on Linux), and credentials for the agent you want to run:

- **Claude Code** — `ANTHROPIC_API_KEY` ([console.anthropic.com](https://console.anthropic.com))
- **Codex** — `OPENAI_API_KEY`
- **Aider** — `OPENAI_API_KEY` or `ANTHROPIC_API_KEY`

On Linux, also install rsync (`apt install rsync`).

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

Pulls the sandbox image from Docker Hub, picks a smart default tester model for your agent, and saves the credential required:

```
Which agent do you want to use?
  1. Claude Code  (Anthropic, recommended)
  2. Codex        (OpenAI)
  3. Aider        (open-source)
  Choice [1]:

ANTHROPIC_API_KEY: ****

Tester / reviewer model  (runs tests and reviews diffs)
  Default: claude-haiku-4-5-20251001
  Customize? [y/N]:

Setup complete.
  Next: cd your-project && ftl code 'your task'
```

The tester default matches your agent's provider — Anthropic → `claude-haiku-4-5-20251001`, OpenAI → `gpt-4o-mini`. Press Enter to accept it or `y` to pick any [LiteLLM-compatible](https://docs.litellm.ai/docs/providers) model string. The reviewer is always set to the same model as the tester — change it later in `.ftlconfig` if needed.

Your choices are saved globally to `~/.ftl/config.json` and used as defaults for every new project. Credentials are saved to `~/.ftl/credentials` and loaded automatically on every invocation — no need to `export` each session.

**Docker Hub images** — pulled automatically based on your agent selection:

```
vvenne/ftl:latest   — Claude Code
vvenne/ftl:codex    — Codex
vvenne/ftl:aider    — Aider
```

### Step 3 — Initialize your project

```bash
cd your-project
ftl init
```

Creates `.ftlconfig` in your project root:

```json
{
  "agent": "claude-code",
  "tester": "claude-haiku-4-5-20251001",
  "reviewer": "claude-haiku-4-5-20251001"
}
```

The values come from your global `~/.ftl/config.json` set during `ftl setup`. Edit `.ftlconfig` to override per-project.

### Step 4 — Run a task

```bash
ftl code 'create a Stripe payment module'   # use single quotes if the task contains $
```

FTL snapshots your project, boots the sandbox, runs the agent while generating tests in parallel, then shows you a review before the raw diff:

```
  Tests passed.

  Change summary
  payments.py — Adds /webhook endpoint that verifies Stripe signatures and
  writes events to the events table. migration_001.py — Creates events table.

  Security: clean

── CREATED: payments.py ──
  + ...

  Review  1/2 files  |  +42 -3  |  2 new  0 changed  0 deleted
  j/k or ↑/↓ move • i interactive ask • a accept • r reject • q keep coding
```

- `j` / `k` or arrow keys — move between changed files in review
- `i` — enter interactive ask mode and ask the agent a question about the diff
- `a` — approve and merge changes to your project
- `r` — reject and discard all changes
- `q` — leave review and continue coding in the sandbox

The **reviewer** runs in parallel with tests and produces three things before the raw diff: a plain-English summary of what changed in each file, any security findings (RCE, injection, unsafe deserialization, etc.), and a prompt adherence check — flagging if the agent modified files outside the scope of the task or shows signs of having been redirected by injected content in the codebase.

Steps 1–2 are one-time machine setup. Step 3 is once per project.

### Adding credentials later

```bash
ftl auth ANTHROPIC_API_KEY sk-ant-...
ftl auth OPENAI_API_KEY sk-...
ftl auth AWS_ACCESS_KEY_ID AKIA...
```

Or put them in a `.env` file in your project root — FTL reads it automatically.

### Agent authentication

FTL stores agent credentials in `~/.ftl/credentials` and forwards them into the sandbox automatically.

- **Claude Code** uses `ANTHROPIC_API_KEY` directly.
- **Codex** uses `OPENAI_API_KEY`. FTL also bootstraps Codex's local login state inside the sandbox automatically before the first task runs, so no manual `codex login` is required in the container.
- **Aider** uses whichever model credential it needs (`OPENAI_API_KEY` or `ANTHROPIC_API_KEY`).

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

Follow-up instructions continue in the same container. Claude Code uses its native conversation-continue flow. Codex does not expose the same resume primitive, so FTL replays prior instructions plus the current unmerged diff to keep follow-up tasks coherent. No cold boot happens between tasks.

The shell prewarms the sandbox up front, so the first task starts in an already-booted container instead of paying the full boot cost after you type.

---

## Agents

FTL supports three coding agents. Select one during `ftl setup` or set `agent` in `.ftlconfig`.

FTL can verify code in `Python`, `TypeScript`, `Go`, `Java`, and `C++`. It auto-detects the project language from common build files and source extensions. If detection fails, `ftl init` asks you which language the project uses. For mixed-language repos, set `language` explicitly in `.ftlconfig` or add `language_overrides` to map subdirectories like `backend` or `web` to different languages.

| Agent | Key | Requires |
|---|---|---|
| Claude Code | `"claude-code"` | `ANTHROPIC_API_KEY` |
| Codex | `"codex"` | `OPENAI_API_KEY` |
| Aider | `"aider"` | `OPENAI_API_KEY` or `ANTHROPIC_API_KEY` |

### Codex authentication

Codex uses the `OPENAI_API_KEY` saved with `ftl auth OPENAI_API_KEY ...` or collected during `ftl setup`.

Inside the sandbox, FTL forwards `OPENAI_API_KEY` and bootstraps Codex's local login state automatically before the first task runs. No manual `codex login` is required inside the container.

---

## Configuration

`ftl init` creates `.ftlconfig` in your project root with `agent` and `tester`. All supported fields:

```json
{
  "agent": "claude-code",
  "language": "python",
  "language_overrides": {
    "backend": "go",
    "web": "typescript"
  },
  "tester": "claude-haiku-4-5-20251001",
  "reviewer": "claude-haiku-4-5-20251001",

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

| Field | Default | Description |
|---|---|---|
| `agent` | `"claude-code"` | Agent to run: `"claude-code"`, `"codex"`, `"aider"` |
| `language` | auto-detected | Override project language: `"python"`, `"typescript"`, `"go"`, `"java"`, `"cpp"` |
| `language_overrides` | — | Optional path-to-language map for mixed repos, for example `{ "backend": "go", "web": "typescript" }` |
| `tester` | `"claude-haiku-4-5-20251001"` | LiteLLM model string for adversarial test generation |
| `reviewer` | `"claude-haiku-4-5-20251001"` | LiteLLM model for diff review: change summary, security scan (RCE, injection, etc.), and prompt adherence check. Runs in parallel with tests. |
| `shadow_env` | `[]` | Extra env var names to shadow beyond what's in `.env` |
| `agent_env` | `[]` | Extra env vars from your host to forward into the sandbox |
| `setup` | — | Shell command run once on a **fresh container only**, before the agent starts |
| `snapshot_backend` | `"local"` | `"local"` or `"s3"` |
| `s3_bucket` | — | S3 bucket name. Required when `snapshot_backend` is `"s3"` |
| `cloudwatch_log_group` | — | CloudWatch log group for session traces |
| `secrets_manager_prefix` | — | AWS Secrets Manager prefix. When set, replaces `.env` as the secrets source |
| `guardrail_id` | — | Bedrock Guardrail ID. When set, replaces the local lint scan — hard-blocks merge if the guardrail intervenes |
| `guardrail_version` | `"DRAFT"` | Guardrail version to apply |

### Choosing tester and reviewer models

Both `tester` and `reviewer` accept any [LiteLLM-supported model](https://docs.litellm.ai/docs/providers):

```json
{ "tester": "claude-haiku-4-5-20251001" }                        // Anthropic direct (default)
{ "tester": "bedrock/us.anthropic.claude-haiku-4-5-20251001" }   // AWS Bedrock
{ "reviewer": "bedrock/us.amazon.nova-pro-v1:0" }                // Amazon Nova Pro via Bedrock
{ "tester": "openai/gpt-4o-mini" }                               // OpenAI
```

Both run in parallel with the agent (tester) and with tests (reviewer), so model latency doesn't add to wall-clock time. You can use a cheaper model for test generation and a more capable one for the security review — they run concurrently regardless.

### Project dependencies (setup hook)

If your project requires `pip install` or `npm install`, add a `setup` command. It runs once when a fresh container is created:

```json
{
  "setup": "pip install -r requirements.txt 2>/dev/null; npm install --silent 2>/dev/null; true"
}
```

The `true` at the end prevents a missing `requirements.txt` or `package.json` from failing the boot. On warm container reuse this command is skipped — packages persist in `/home/ftl/.local/` across tasks.

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

- Hardcoded shadow values (`ftl_shadow_*` pattern or exact match)
- Known credential patterns: Stripe live/test keys, Anthropic keys, AWS access keys, GitHub PATs, GitLab tokens, Slack tokens, SendGrid keys
- Dangerous SQL: `DROP TABLE`, `DROP DATABASE`, `DROP SCHEMA`, `TRUNCATE`, `DELETE FROM` without `WHERE`
- Dangerous shell: `rm -rf`, `rm -fr`, `shred`, `dd if=`, truncating `/dev/`

Credential findings are always advisory. Dangerous operation findings are **blocking by default** — if the diff contains destructive operations (DROP TABLE, rm -rf, etc.) that were not explicitly requested in the task, merge is hard-blocked. If the task description clearly asks for the destructive behavior, violations are downgraded to warnings and the merge proceeds to review. Bedrock Guardrails replaces the local lint scan when `guardrail_id` is configured.

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

HTTPS traffic is handled via MITM using a per-session ephemeral CA installed in the container's trust store at boot. The CA key is never written to disk.

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

Provisions all four AWS resources and writes config in one step:

1. Reads your account ID and region via STS
2. Creates S3 bucket `ftl-<account>-<region>` (idempotent)
3. Creates CloudWatch log group `/ftl/<project-name>` (idempotent)
4. Creates a Bedrock Guardrail `ftl-<project-name>` with PII and credential blocking
5. Prompts for an optional Secrets Manager prefix
6. Merges all new keys into `.ftlconfig`

Run it again at any time — it will not duplicate existing resources.

### S3 Snapshots

Snapshots are stored as gzipped tarballs at `s3://<bucket>/snapshots/<project-hash>/<id>.tar.gz`. The local cache at `~/.ftl/snapshots/` is kept so the Docker container can mount snapshots without a per-task S3 download.

### Secrets Manager

When `secrets_manager_prefix` is set, FTL fetches secrets from AWS Secrets Manager instead of reading `.env`. Secrets are loaded at session start, shadow values are generated from them, and the credential-swap proxy works identically from that point.

Secrets with JSON object values (e.g. `{"API_KEY": "...", "DB_PASSWORD": "..."}`) are expanded into individual keys. Plain-string secrets use the last path segment as the key name, uppercased.

### Bedrock Guardrails

When `guardrail_id` is set, FTL applies a Bedrock Guardrail to the full diff text before the human review step, replacing the local lint scan.

If the guardrail intervenes (detects an AWS key, API token, or PII), the merge is **hard-blocked** and changes are discarded. If it passes, review proceeds normally. Findings (PII type, content policy category) are printed before the block decision.

### CloudWatch Tracing

When `cloudwatch_log_group` is set, FTL emits structured JSON events to CloudWatch Logs for each session stage (snapshot, boot, agent, tests).

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

Every `litellm.completion()` call (tester, diff review, Q&A) is traced automatically via LiteLLM's Langfuse integration.

---

## Sandbox Internals

```
~/.ftl/
├── snapshots/<id>/     — project state at task start (rsync, respects .ftlignore)
├── containers/<hash>   — persistent container ID per project path
├── config.json         — global defaults set by ftl setup
├── credentials         — ftl auth storage (mode 600)
└── logs.jsonl          — session audit log
```

**Container lifecycle:**
- One persistent container per project path, keyed by a hash of the path
- Workspace (`/workspace`) wiped and restored from snapshot on each task
- Everything outside `/workspace` persists: user-installed packages in `/home/ftl/.local/`, global npm installs, agent conversation history

**What persists across tasks in the same container:**

| Location | On task reset | Notes |
|---|---|---|
| `/workspace/` | Wiped and restored | Project files |
| `/home/ftl/.local/` | Persists | `pip install` packages |
| `/usr/lib/python3/` | Persists | Pre-installed: stripe, requests, httpx, boto3, openai, anthropic, pydantic, python-dotenv, pytest |
| Global node_modules | Persists | `npm install -g` (TypeScript, ts-node, Jest, Claude Code) |
| `/home/ftl/.claude/` | Persists | Claude Code conversation history |
| `/home/ftl/.codex/` | Persists | Codex auth and session state |

**Agent warm start:** On every boot, FTL prewarms the selected agent runtime in the background (`claude --version`, `codex --version`, etc.) so the first task pays less startup cost.

---

## How It Works

```
ftl code "build login component with Supabase auth"
```

```
1. SNAPSHOT        — rsync project state to ~/.ftl/snapshots/<id>
2. BOOT            — reuse persistent container or start fresh (per project)
3. INJECT          — shadow credentials replace real keys inside sandbox
4. AGENT ∥ TESTS   — coding agent runs; adversarial tests generate in parallel
5. RUN TESTS       — pre-generated tests execute the moment the agent finishes
   ∥ REVIEW        — reviewer runs in parallel: change summary, security scan,
                      prompt adherence check (did the agent follow the task?)
6. LINT            — diff scanned for credentials and dangerous operations
7. DIFF            — computed on demand; file-level review of all changes
8. APPROVE         — human reviews summary + findings, asks questions, merges or rejects
```

The agent runs entirely inside Docker. It never sees your real API keys or your host filesystem. Nothing touches your project without explicit approval.

---

## Benchmarking

FTL's safety layer is effectively free in normal dev workflows. On benchmarked edit tasks, total overhead was **~291ms per task** for agent-driven work, or about **14.5%** wall-clock overhead:

| Task | Without FTL | With FTL | FTL Overhead |
|---|---|---|---|
| Create 50-line file | 2.00s | 2.29s | 0.29s |
| Modify 5 files | 2.01s | 2.30s | 0.29s |
| Create 10 files | 2.01s | 2.30s | 0.29s |

The underlying pipeline operations are also cheap. Medium-scale snapshots (100 files) averaged **26.0ms**, diff computation averaged **95.9ms**, and merge preparation averaged **134.3ms** across 5 runs. Docker warm execution averaged **66.3ms**.

The benchmark run also showed that the protection mechanisms are not coming at the cost of quality:

- Shadow credential detection: **100.0%** (`46/46` secrets across 20 `.env` format cases)
- Shadow credential uniqueness: **1000/1000 unique values**, **0 collisions**
- Credential linter detection: **90.9%** (`10/11`) with **0.0% false positives** (`0/20`)
- Destructive command detection: **100.0%** (`13/13`)
- Snapshot, shadow-map, and linter reliability: **100.0% success** across 20 repeated runs
- Container isolation: **0** unexpectedly accessible sensitive host paths

In practice, that means you get sandboxing, credential shadowing, destructive-op blocking, and pre-merge review for roughly the cost of a few hundred milliseconds, which is below the threshold most developers will notice during an agent-driven edit loop.

Full benchmark artifacts live in `ftl_benchmarks.json` and `ftl_benchmarks_summary.md`.

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
├── Dockerfile                   # Base image (Claude Code + common Python/Node packages)
├── scripts/
│   └── publish.sh               # Build and push all Docker Hub tag variants
├── ftl/
│   ├── cli.py                   # CLI entry points, setup wizard, interactive shell
│   ├── orchestrator.py          # Session lifecycle: snapshot → boot → agent ∥ tester → tests ∥ reviewer → merge
│   ├── planner.py               # Tester: parallel test generation + execution
│   ├── proxy.py                 # HTTP/HTTPS credential-swap proxy (optional, requires cryptography)
│   ├── render.py                # Stream-JSON renderer: per-tool live progress counters
│   ├── diff.py                  # Diff computation, display, reviewer (summary + security + adherence), Q&A
│   ├── lint.py                  # Credential + dangerous operation scanner
│   ├── secrets.py               # AWS Secrets Manager loader (AWS mode)
│   ├── guardrails.py            # Bedrock Guardrail apply (AWS mode)
│   ├── cloudwatch.py            # CloudWatch session tracing
│   ├── tracing.py               # Langfuse tracing, StageTimer, AgentHeartbeat
│   ├── config.py                # .ftlconfig loader + ~/.ftl/config.json global defaults
│   ├── credentials.py           # Shadow credential generation, ~/.ftl/credentials store
│   ├── ignore.py                # Shared ignore rules (ALWAYS_IGNORE + .ftlignore)
│   ├── log.py                   # Session audit log (~/.ftl/logs.jsonl)
│   ├── agents/
│   │   ├── base.py              # Abstract agent interface
│   │   ├── claude_code.py       # Claude Code adapter (stream-json output)
│   │   ├── codex.py             # Codex adapter
│   │   └── aider.py             # Aider adapter
│   ├── sandbox/
│   │   ├── base.py              # Abstract sandbox interface
│   │   └── docker.py            # Docker backend: persistent containers, Node.js pre-warm
│   └── snapshot/
│       ├── base.py              # Abstract snapshot interface
│       ├── local.py             # Local rsync-based snapshots
│       └── s3.py                # S3-backed snapshots (requires boto3)
```

---

## Roadmap

**Done:**
- Isolated Docker sandbox with persistent containers (no cold-boot penalty per task)
- Shadow credential injection — real keys never enter the container
- Node.js pre-warm — eliminates 5-8s agent cold-start on first task
- Per-tool live progress display (stream-JSON renderer with elapsed counters)
- Parallel adversarial test generation (tester runs while agent codes)
- Linux-internal diff (runs inside container, no host-side overhead)
- Live streaming agent output (line-by-line, not blocking until completion)
- rsync-based snapshots with `.ftlignore` support
- S3 snapshot backend
- Credential + dangerous operation linter (DROP TABLE, rm -rf, etc.)
- HTTP/HTTPS credential-swap proxy (MITM, ephemeral CA, shadow→real at network layer)
- Session audit log
- AWS Secrets Manager integration — replaces `.env` as secrets source
- Bedrock Guardrails integration — hard-blocks merge on detected secrets or PII
- `ftl config --aws` one-shot wizard — provisions S3, CloudWatch, Guardrail, SM prefix
- CloudWatch session tracing
- Multi-agent support: Claude Code, Codex, Aider
- `ftl setup` wizard — agent selection, tester model, Docker Hub pull
- Published Docker Hub images (`vvenne/ftl:latest`, `:codex`, `:aider`, `:full`)
- Parallel reviewer — change summary, security scan (RCE, injection, deserialization, etc.), and prompt adherence check running in parallel with tests

**Next:**
- Tool dispatch layer — planner routes between coding, GitHub, Slack, email
- Remote execution — Firecracker/Lambda sandbox backend (S3 snapshots already done)
- Multi-agent parallelism — fan out independent subtasks

**Later:**
- Virtualization.framework sandbox (sub-second boot via VM snapshots, no Docker dependency)
- DynamoDB audit log

---

## Philosophy

> Agents are untrustworthy by construction. FTL is the layer that makes them safe to use anyway.

The agent cannot have skin in the game. The human must. Every change requires explicit approval before it touches the real filesystem.

---

## License

MIT
