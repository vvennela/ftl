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
│  4. RUN agent inside sandbox                    │
│  5. PROXY outbound calls — swap shadow keys     │
│     for real keys at the wire level             │
│  6. TEST — second model generates + runs tests  │
│     ├─ Pass → continue                          │
│     └─ Fail → human intervention                │
│  7. DIFF — git-style review of all changes      │
│  8. APPROVE or REJECT — human decides           │
│  9. MERGE to real project only on approval      │
│ 10. AUDIT — log everything                      │
└─────────────────────────────────────────────────┘
```

The agent never sees your real API keys. Tests run in the sandbox. Nothing touches your filesystem without your explicit approval.

---

## Architecture: Fortress + Cockpit

FTL has two layers:

### Fortress (The Sandbox)
The security infrastructure. Runs agents in isolated Docker containers (Virtualization.framework VMs on the roadmap). Handles shadow credential injection, network proxy for key swapping, snapshot/restore, and audit logging. **This is what the MVP delivers.**

### Cockpit (The Shell)
The natural language interface. An interactive shell where you issue commands, review diffs, ask questions about changes, manage snapshots, and control the full workflow. Future versions will include intent parsing via LLM planners (Nova Lite, Claude, GPT, Ollama) to break complex tasks into executable steps.

---

## Quick Start

```bash
# Install
pip install -e .

# Build the sandbox image
docker build -t ftl-sandbox:latest .

# Initialize in your project
cd your-project
ftl init

# Run a task
ftl code "create login component"

# Or enter interactive mode
ftl
```

### Configuration

`ftl init` creates a `.ftlconfig` in your project root:

```json
{
  "planner_model": "bedrock/amazon.nova-lite-v1:0",
  "agent": "claude-code",
  "tester": "bedrock/deepseek-r1"
}
```

- **agent** — the coding agent that runs inside the sandbox (`claude-code`, `kiro`)
- **tester** — a different agent or model that generates adversarial tests (must differ from agent)
- **planner_model** — LLM for intent parsing and diff Q&A (via LiteLLM — any provider)

All models are routed through [LiteLLM](https://github.com/BerriAI/litellm), so you can swap to any provider:

```json
{"agent": "kiro", "tester": "ollama/deepseek-r1", "planner_model": "gpt-4o"}
```

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

The agent writes code using these shadow keys. When the code makes an outbound API call, FTL's network proxy intercepts the request, swaps the shadow key for the real key at the wire level, and forwards the request. The agent never sees the real value.

---

## Progress

### Done

- [x] CLI framework (`ftl init`, `ftl code "task"`, interactive shell)
- [x] Project-level config (`.ftlconfig` with git-style directory walking)
- [x] Shadow credential generation (`.env` scanning + configurable extras)
- [x] Docker sandbox with warm pool (boot once, reuse across tasks)
- [x] Pluggable sandbox interface (Docker MVP, Virtualization.framework future)
- [x] Agent adapters (Claude Code, Kiro — pluggable, ~10 lines per agent)
- [x] Filesystem snapshot/restore (local storage, `.ftlignore` support)
- [x] Pluggable snapshot interface (local MVP, S3 future)
- [x] Git-style diff display (Rich terminal UI, green/red, file summaries)
- [x] Interactive diff review with LLM Q&A (ask questions about changes)
- [x] Configurable test verification (any agent or model as tester)
- [x] Orchestrator wiring (snapshot → sandbox → agent → test → diff → approve → merge)
- [x] Dockerfile (Debian slim, Node.js 22, Python 3.11, TypeScript)

### To Do

- [ ] Network proxy layer (intercept outbound traffic, swap shadow keys for real keys)
- [ ] Agent → test → retry loop (human intervenes only on test failure)
- [ ] Audit logging (local SQLite default, DynamoDB optional)
- [ ] S3 snapshot adapter
- [ ] DynamoDB audit adapter
- [ ] Bedrock integration for Nova Lite / DeepSeek R1
- [ ] Virtualization.framework sandbox backend (Alpine Linux, sub-second boot)
- [ ] Cockpit: LLM planner for intent parsing and task decomposition
- [ ] Claude Code + Kiro pre-installed in sandbox image
- [ ] `ftl logs` command for audit trail
- [ ] Enterprise features (team audit trails, custom credential patterns)

---

## Project Structure

```
FTL/
├── pyproject.toml              # Project config, dependencies, CLI entry point
├── Dockerfile                  # Sandbox image (Debian slim + Node + Python)
├── .gitignore
├── ftl/
│   ├── cli.py                  # CLI: ftl init, ftl code, interactive shell
│   ├── config.py               # .ftlconfig reader (git-style directory walk)
│   ├── credentials.py          # Shadow credential generation + mapping
│   ├── orchestrator.py         # Full execution flow
│   ├── diff.py                 # Diff computation, display, interactive review
│   ├── agents/
│   │   ├── base.py             # Abstract agent interface
│   │   ├── claude_code.py      # Claude Code adapter
│   │   └── kiro.py             # Kiro CLI adapter
│   ├── sandbox/
│   │   ├── base.py             # Abstract sandbox interface
│   │   └── docker.py           # Docker implementation with warm pool
│   └── snapshot/
│       ├── base.py             # Abstract snapshot interface
│       └── local.py            # Local filesystem implementation
└── tests/
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
