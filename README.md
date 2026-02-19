# FTL: Work Faster than Light

**FTL** is a terminal-native, zero-trust control plane for AI coding agents. Run Claude Code, Kiro, or any coding agent inside an isolated sandbox with shadow credentials, automated testing, and human-in-the-loop approval — without giving agents access to your real secrets or filesystem.

> "FTL is the zero-trust security layer for AI development. Run any agent through FTL and get sandbox isolation, shadow credentials, and unified audit trails."

---

## The Problem

AI coding agents (Claude Code, Kiro, Codex, aider) need broad filesystem access to be useful. This means they can read your `.env` files, access API keys, and run destructive commands. Developers are forced to choose between **productivity** and **security**.

FTL removes that tradeoff.

---

## How It Works

```
ftl code "build login component with Supabase auth"
```

```
┌─────────────────────────────────────────────────┐
│  1. SNAPSHOT project state                      │
│  2. BOOT sandbox (Docker container)             │
│  3. INJECT shadow credentials (fake API keys)   │
│  4. PLANNER breaks task into steps              │
│     ├─ Sends step to agent inside sandbox       │
│     ├─ Reads agent output                       │
│     ├─ Triggers tests when ready                │
│     ├─ Feeds failures back to agent             │
│     └─ Loops until task complete                │
│  5. DIFF — file-level review of all changes     │
│  6. APPROVE or REJECT — human decides           │
│  7. MERGE to real project only on approval      │
└─────────────────────────────────────────────────┘
```

The agent runs entirely inside Docker. It never sees your real API keys. Nothing touches your filesystem without your explicit approval.

---

## Architecture: Three Roles

FTL separates concerns into three independently configurable roles:

```json
{
  "planner_model": "bedrock/us.amazon.nova-lite-v1:0",
  "agent": "claude-code",
  "tester": "bedrock/us.amazon.nova-lite-v1:0"
}
```

### Planner (Nova Lite / any LLM)
The orchestration brain. Runs on the **host** via LiteLLM API calls. Breaks tasks into steps, drives the agent, triggers tests, loops on failures. Constrained to a fixed JSON action set — it can only emit `agent`, `test`, `done`, or `clarify` actions. Cannot escape this loop.

### Agent (Claude Code / Kiro)
The coding hands. Runs **inside the Docker sandbox** with `--dangerously-skip-permissions` (safe because Docker IS the permission boundary). Maintains conversation continuity via `-c` flag across steps. Never sees real credentials or the host filesystem.

### Tester (DeepSeek R1 / any LLM or agent)
The adversarial reviewer. Generates tests that try to break the agent's code. Must be a different model/agent than the coding agent. Test results feed back to the planner, which tells the agent to fix failures.

---

## Quick Start

```bash
# Install
pip install -e .

# Build the sandbox image
docker build -t ftl-sandbox:latest .

# Set credentials
export ANTHROPIC_API_KEY=sk-ant-...          # For Claude Code (agent)
export AWS_BEARER_TOKEN_BEDROCK=ABSK...      # For Bedrock (planner/tester)

# Initialize in your project
cd your-project
ftl init

# Run a task (one-shot)
ftl code "create login component"

# Or enter interactive mode
ftl
```

### Interactive Shell

```
ftl> build a login page with email and password
  Planner → Agent → Tests → Done

ftl[active]> add form validation
  Planner → Agent → Tests → Done

ftl[active]> diff
  Shows all changes since snapshot

ftl[active]> test
  Manually trigger tests

ftl[active]> merge
  Interactive review → approve/reject

ftl[active]> reject
  Discard all changes
```

### Configuration

`ftl init` creates a `.ftlconfig` in your project root:

```json
{
  "planner_model": "bedrock/us.amazon.nova-lite-v1:0",
  "agent": "claude-code",
  "tester": "bedrock/us.amazon.nova-lite-v1:0",
  "planner_max_steps": 20
}
```

All models are routed through [LiteLLM](https://github.com/BerriAI/litellm), so you can swap to any provider:

```json
{"planner_model": "ollama/llama3", "agent": "kiro", "tester": "anthropic/claude-haiku-4-5-20251001"}
```

Optional config fields:
- **shadow_env** — extra env var names to shadow (beyond `.env`)
- **agent_env** — extra env vars to forward for agent auth
- **planner_max_steps** — safety limit on planner iterations (default: 20)

---

## Key Design Principles

- **Containment, not detection.** FTL doesn't promise to catch malicious code. It ensures malicious code can't escape the sandbox or access real secrets.
- **Agent-agnostic.** FTL is infrastructure, not another coding agent. It wraps Claude Code, Kiro, aider, or any CLI agent.
- **Human-in-the-loop.** The agent cannot have skin in the game. The human must. Every change requires explicit approval.
- **Local-first.** Works fully offline. Cloud services (S3, DynamoDB, Bedrock) are optional backends for teams and enterprise.

---

## Shadow Credentials

FTL's core security feature. Your `.env` contains real keys:

```
STRIPE_SECRET_KEY=sk_live_abc123
SUPABASE_KEY=eyJhbGciOi...
```

FTL generates shadow keys and injects them into the sandbox:

```
STRIPE_SECRET_KEY=ftl_shadow_stripe_secret_key_7f8a2b3c
SUPABASE_KEY=ftl_shadow_supabase_key_9d4e1f6a
```

The agent writes code using these shadow keys. The `.env` file never enters the sandbox — it's stripped during workspace copy via shared ignore rules. Real credentials only exist on the host.

---

## Sandbox Isolation

The agent runs inside a Docker container with:

- **Resource limits**: 2GB RAM, 2 CPUs
- **Non-root user**: `ftl` user (Claude Code requires non-root for `--dangerously-skip-permissions`)
- **Filtered workspace**: `.env`, `.git`, `node_modules`, `__pycache__` are stripped before mounting
- **Shadow credentials**: Injected via env vars, not files
- **Agent auth**: `ANTHROPIC_API_KEY` forwarded separately from project secrets
- **Warm pool**: Container boots once, goes to standby between tasks, reuses on next invocation
- **Diff-driven merge**: Only changed files (create/modify/delete) are merged back — not a blind copy

---

## Progress

### Done

- [x] CLI framework (`ftl init`, `ftl code "task"`, interactive shell)
- [x] Project-level config (`.ftlconfig` with git-style directory walking)
- [x] Shadow credential generation (`.env` scanning + configurable extras via python-dotenv)
- [x] Docker sandbox with warm pool (boot once, reuse across tasks)
- [x] Non-root sandbox user (required for Claude Code permissions)
- [x] Pluggable sandbox interface (Docker MVP, Virtualization.framework future)
- [x] Agent adapters running inside sandbox (Claude Code, Kiro — via `sandbox.exec()`)
- [x] Agent conversation continuity (`-c` flag for follow-up messages)
- [x] Agent auth forwarding (`ANTHROPIC_API_KEY` into container, separate from shadow creds)
- [x] Filtered workspace copy (shared ignore rules — no `.env`, `.git`, `node_modules`)
- [x] Filesystem snapshot/restore (local storage, `.ftlignore` support)
- [x] Pluggable snapshot interface (local MVP, S3 future)
- [x] File-level diff display (Rich terminal UI, green/red, binary detection)
- [x] Interactive diff review with LLM Q&A (ask questions about changes)
- [x] Diff-driven merge (surgical — only creates/modifies/deletes changed files)
- [x] Planner loop (constrained JSON actions, drives agent + tester, max step safety)
- [x] Session-aware shell (follow-up instructions, test/diff/merge/reject commands)
- [x] Configurable test verification (any agent or model as tester)
- [x] Bedrock integration (Nova Lite via inference profiles)
- [x] Claude Code installed in sandbox image
- [x] Dockerfile (Debian slim, Node.js 22, Python 3.11, TypeScript, Claude Code)
- [x] End-to-end tested: planner → agent → diff → review flow working

### To Do

- [ ] Network proxy layer (intercept outbound traffic, swap shadow keys for real keys)
- [ ] Install pytest/jest in sandbox image for tester
- [ ] Audit logging (local SQLite default, DynamoDB optional)
- [ ] S3 snapshot adapter
- [ ] DynamoDB audit adapter
- [ ] Virtualization.framework sandbox backend (Alpine Linux, sub-second boot)
- [ ] Kiro CLI installed in sandbox image
- [ ] `ftl logs` command for audit trail
- [ ] Enterprise features (team audit trails, custom credential patterns)

---

## Project Structure

```
FTL/
├── pyproject.toml              # Project config, dependencies, CLI entry point
├── Dockerfile                  # Sandbox image (Debian slim + Node + Python + Claude Code)
├── .gitignore
├── ftl/
│   ├── cli.py                  # CLI: ftl init, ftl code, interactive shell with sessions
│   ├── config.py               # .ftlconfig reader (git-style directory walk)
│   ├── credentials.py          # Shadow credential generation + mapping (python-dotenv)
│   ├── orchestrator.py         # Session management, workspace copy, merge
│   ├── planner.py              # Planner loop (constrained JSON actions, drives agent)
│   ├── diff.py                 # Diff computation, display, interactive review
│   ├── ignore.py               # Shared ignore rules (ALWAYS_IGNORE + .ftlignore)
│   ├── agents/
│   │   ├── base.py             # Abstract agent interface (run + continue_run)
│   │   ├── claude_code.py      # Claude Code adapter (sandbox.exec, -c continuation)
│   │   └── kiro.py             # Kiro CLI adapter
│   ├── sandbox/
│   │   ├── base.py             # Abstract sandbox interface
│   │   └── docker.py           # Docker implementation with warm pool + agent auth
│   └── snapshot/
│       ├── base.py             # Abstract snapshot interface
│       └── local.py            # Local filesystem implementation
```

---

## Competition

FTL is a semi-finalist in the [AWS 10,000 AIdeas Competition](https://builder.aws.com/content/347b02koQ6TVBUruiirsO4c9JAl/10000-aideas-competition) ($250K prize pool). The competition build uses AWS Bedrock (Nova Lite + DeepSeek R1), S3, and DynamoDB as pluggable backends, with Kiro as the primary agent.

---

## Philosophy

> Agents are untrustworthy. You want fewer of them, not more. Humans must stay accountable.

FTL is not a better AI agent — it's the security infrastructure that makes AI agents safe to use in production. While everyone else builds "agent swarms," FTL ensures one human, one secure environment, minimal agent exposure.

The human must have skin in the game. The agent cannot.

---

## License

MIT
