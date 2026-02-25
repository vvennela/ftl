# FTL

**Zero-trust control plane for AI coding agents.** Run Claude Code (or any coding agent) inside an isolated Docker sandbox with shadow credentials, parallel adversarial testing, and human-in-the-loop approval — without ever giving the agent access to your real secrets or filesystem.

---

## How It Works

```
ftl code "build login component with Supabase auth"
```

```
1. SNAPSHOT     — rsync project state to ~/.ftl/snapshots/<id>
2. BOOT         — reuse persistent container or start fresh (per project)
3. INJECT       — shadow credentials replace real keys inside sandbox
4. AGENT ∥ TESTS — coding agent runs; adversarial tests generate in parallel
5. RUN TESTS    — pre-generated tests execute the moment the agent finishes
6. DIFF         — computed on demand; file-level review of all changes
7. APPROVE      — human reviews, asks questions, merges or rejects
```

The agent runs entirely inside Docker. It never sees your real API keys. Nothing touches your filesystem without explicit approval.

---

## Architecture

Two roles, not three:

```json
{
  "agent":  "claude-code",
  "tester": "bedrock/us.anthropic.claude-sonnet-4-6"
}
```

### Agent (Claude Code / Kiro)
Runs **inside the Docker sandbox**. Gets the task description and executes it. Streams output live. Maintains conversation continuity via `-c` across follow-up instructions. Never sees real credentials or the host filesystem.

### Tester (any LLM)
Runs **in parallel with the agent** via a separate API call. Generates adversarial tests from the task description — no code needed to start. By the time the agent finishes, tests are ready to run immediately. Must be a different model than the agent.

The former "planner" loop (a cheap LLM orchestrating agent steps) was removed — Claude Code already manages its own execution loop internally. The planner will return when the tool dispatch layer is built (email, Slack, GitHub actions alongside coding).

---

## Quick Start

```bash
# Install
pip install -e .

# Build the sandbox image (one time)
docker build -t ftl-sandbox .

# Set credentials
export ANTHROPIC_API_KEY=sk-ant-...         # for Claude Code (agent)
export AWS_BEARER_TOKEN_BEDROCK=ABSK...     # for Bedrock (tester)

# Initialize in your project
cd your-project
ftl init

# Run a task
ftl code 'create a Stripe payment module'

# Interactive shell
ftl
```

Use single quotes if the task contains `$`.

---

## Interactive Shell

```
ftl> build a login page with email and password

ftl[active]> add form validation

ftl[active]> diff        — show all changes since snapshot
ftl[active]> test        — re-run tests manually
ftl[active]> merge       — review diff, approve/reject, merge to project
ftl[active]> reject      — discard all changes
```

Follow-up instructions continue the same agent conversation (`-c` flag) in the same container. The container persists across `ftl code` invocations for the same project — no cold boot penalty.

---

## Configuration

`ftl init` creates `.ftlconfig` in your project root:

```json
{
  "agent": "claude-code",
  "tester": "bedrock/us.anthropic.claude-sonnet-4-6"
}
```

All models route through [LiteLLM](https://github.com/BerriAI/litellm):

```json
{
  "agent": "claude-code",
  "tester": "anthropic/claude-haiku-4-5-20251001"
}
```

Optional fields:
- **`shadow_env`** — extra env var names to shadow beyond `.env`
- **`agent_env`** — extra env vars to forward for agent auth

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

The agent writes code using these shadow values. Your `.env` never enters the container. Before merge, FTL's credential linter scans the diff for hardcoded shadow values and flags them.

---

## Sandbox

```
~/.ftl/
├── snapshots/<id>/     — project state at task start (rsync, respects .ftlignore)
├── containers/<hash>   — persistent container ID per project path
└── credentials         — ftl auth key=value storage (mode 600)
```

The Docker container:
- **Persists across runs** — keyed by project path, reused on next `ftl code` call
- **Workspace reset per task** — Linux-internal `cp -a` from snapshot, no host-side Python I/O
- **Streams output live** — `exec_stream` with `Popen`, no blocking until completion
- **Non-root user** (`ftl`) — required for Claude Code `--dangerously-skip-permissions`
- **Resource limits** — 2GB RAM, 2 CPUs
- **Diff on demand** — computed inside the container (Linux-side), only when needed

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
│   ├── diff.py                  # Diff computation, display, interactive review with LLM Q&A
│   ├── lint.py                  # Credential leak detection on diffs
│   ├── config.py                # .ftlconfig loader (git-style directory walk)
│   ├── credentials.py           # Shadow credential generation, ~/.ftl/credentials store
│   ├── ignore.py                # Shared ignore rules (ALWAYS_IGNORE + .ftlignore)
│   ├── log.py                   # Session audit log
│   ├── agents/
│   │   ├── base.py              # Abstract agent interface (run, continue_run, callback)
│   │   ├── claude_code.py       # Claude Code adapter
│   │   └── kiro.py              # Kiro adapter
│   ├── sandbox/
│   │   ├── base.py              # Abstract sandbox interface (boot, exec, exec_stream)
│   │   └── docker.py            # Docker backend: persistent containers, workspace reset, streaming
│   └── snapshot/
│       ├── base.py              # Abstract snapshot interface
│       └── local.py             # Local rsync-based snapshots
```

---

## Roadmap

**Next (AWS competition demo):**
- Tool dispatch layer — planner routes between coding, email, Slack, GitHub
- Target: *"Write a Stripe payment module, open a PR, and Slack Brian it's ready."*
- Contact resolution from `~/.ftl/world.yaml` (top email/Slack/iMessage contacts)

**Later:**
- Network proxy — intercept outbound traffic, swap shadow keys for real keys at the boundary
- S3 snapshot backend
- DynamoDB audit log
- Virtualization.framework sandbox (sub-second boot, no Docker dependency)

---

## Philosophy

> Agents are untrustworthy by construction. FTL is the layer that makes them safe to use anyway.

The agent cannot have skin in the game. The human must. Every change requires explicit approval before it touches the real filesystem.

---

## License

MIT
