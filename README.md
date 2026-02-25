# FTL

**Zero-trust control plane for AI agents.** Run Claude Code (or any coding agent) inside an isolated Docker sandbox with shadow credentials, parallel adversarial testing, and human-in-the-loop approval — without ever giving the agent access to your real secrets or filesystem.

FTL is the foundation for a natural-language computer interface. Today: coding tasks reviewed before they touch your project. Soon: *"Write a Stripe payment module, open a PR, and Slack Brian it's ready."* — one instruction, multiple real-world actions, all gated behind human approval.

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

## FTL Cockpit

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
- **`snapshot_backend`** — `"local"` (default) or `"s3"`
- **`s3_bucket`** — required when `snapshot_backend` is `"s3"`
- **`setup`** — shell command to run after workspace is populated on a **fresh container only**

S3 snapshot config:

```json
{
  "agent": "claude-code",
  "tester": "bedrock/us.anthropic.claude-sonnet-4-6",
  "snapshot_backend": "s3",
  "s3_bucket": "my-ftl-snapshots"
}
```

Install the S3 extra: `pip install -e ".[aws]"`

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

### Network Proxy (optional)

Install `cryptography` to enable the credential-swap proxy:

```bash
pip install -e ".[proxy]"
```

When active, FTL starts an HTTP/HTTPS intercepting proxy on the host before the agent runs. The container routes all outbound traffic through it via `HTTP_PROXY`/`HTTPS_PROXY` env vars — respected automatically by Python `requests`, Node `https`, curl, and most HTTP libraries.

**How the swap works:**

For every outgoing request, the proxy replaces any shadow credential bytes with the corresponding real value before the data reaches the upstream server. The upstream server sees only real keys and responds normally. The agent sees only shadow values throughout.

```
Container code:   Authorization: Bearer ftl_shadow_stripe_secret_key_7f8a2b3c
Proxy rewrites:   Authorization: Bearer sk_live_abc123
Stripe receives:  Authorization: Bearer sk_live_abc123  ✓
```

**HTTP requests** are forwarded directly — the proxy receives the full request, swaps in headers and body, then forwards.

**HTTPS requests** use MITM:
1. Container sends `CONNECT api.stripe.com:443` to the proxy
2. Proxy responds `200 Connection Established`
3. Proxy generates a leaf TLS cert for `api.stripe.com` signed by an ephemeral CA
4. Container completes TLS handshake with the proxy (cert validates — CA is trusted)
5. Proxy opens a separate real TLS connection to `api.stripe.com`
6. Proxy relays the decrypted request, swapping shadow→real, then re-encrypts to the real server

The ephemeral CA is generated fresh each session and installed into the container's trust store at boot (`update-ca-certificates`). It is never written to disk on the host and is discarded when the session ends. Leaf certs are cached per hostname for the session's duration.

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
- **Proxy-aware** — routes through credential-swap proxy when `cryptography` is installed

**What the workspace reset does and doesn't touch:**

The reset runs `find /workspace -mindepth 1 -delete` then restores from snapshot. It only affects `/workspace`. The rest of the container filesystem is untouched, which means:

| Location | On reset | Example |
|---|---|---|
| `/workspace/` | Wiped and restored from snapshot | Project files, `/workspace/venv/` |
| `/home/ftl/.local/` | **Persists** | `pip install foo` as the `ftl` user |
| `/usr/lib/python3/` | **Persists** (baked into image) | `stripe`, `requests`, `boto3`, pre-installed |
| Global `node_modules` | **Persists** | `npm install -g foo` |
| `/workspace/node_modules/` | Wiped | `npm install` inside project |

Packages the agent installs with `pip install foo` (user-local, `/home/ftl/.local/`) accumulate on the warm container across tasks. This means a package installed in task 1 is available in task 2 without reinstalling — but they disappear when a fresh container is created for the project. Pre-installed packages (stripe, requests, httpx, boto3, openai, anthropic, pydantic, pytest) are always available regardless.

To ensure project dependencies are always present on a fresh container, add a `setup` command to `.ftlconfig`:

```json
{
  "agent": "claude-code",
  "tester": "bedrock/us.anthropic.claude-sonnet-4-6",
  "setup": "pip install -r requirements.txt 2>/dev/null; npm install --silent 2>/dev/null; true"
}
```

This runs once when a fresh container is created — not on warm reuse, where the packages already exist. The `true` at the end ensures a missing `requirements.txt` or `package.json` doesn't fail the boot.

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
│   ├── proxy.py                 # HTTP/HTTPS credential-swap proxy (optional, requires cryptography)
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
│   │   ├── base.py              # Abstract sandbox interface (boot, exec, exec_stream, exec_as_root)
│   │   └── docker.py            # Docker backend: persistent containers, workspace reset, streaming
│   └── snapshot/
│       ├── base.py              # Abstract snapshot interface
│       ├── local.py             # Local rsync-based snapshots
│       └── s3.py                # S3-backed snapshots (requires boto3, pip install -e ".[aws]")
```

---

## Objectives

**Done:**
- Isolated Docker sandbox with persistent containers (no cold-boot penalty per task)
- Shadow credential injection — real keys never enter the container
- Parallel adversarial test generation (tester runs while agent codes)
- Linux-internal diff (runs inside container, no host-side Python/VirtioFS overhead)
- Lazy diff computation — only computed when you ask for it
- Live streaming agent output (Popen line-by-line, not blocking until completion)
- rsync-based snapshots with ignore rules
- Credential linter — flags hardcoded shadow values in diffs before merge
- Session audit log

**Next (AWS competition demo):**
- Tool dispatch layer — planner routes between coding, email, Slack, GitHub
- Contact resolution from `~/.ftl/world.yaml` (top email/Slack/iMessage contacts)
- AWS-native execution: S3 snapshot backend, Firecracker/Lambda containers

**Later:**
- Network proxy — intercept outbound traffic, swap shadow keys for real keys at the boundary
- DynamoDB audit log
- Virtualization.framework sandbox (sub-second boot, no Docker dependency)
- Multi-agent parallelism — planner fans out independent tasks

---

## Philosophy

> Agents are untrustworthy by construction. FTL is the layer that makes them safe to use anyway.

The agent cannot have skin in the game. The human must. Every change requires explicit approval before it touches the real filesystem.

---

## License

MIT
