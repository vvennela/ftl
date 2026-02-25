# FTL

Zero-trust control plane for AI development. Sandboxed coding agent with credential shadowing, snapshot/diff/review before merge, and a planner loop that orchestrates Claude Code on Bedrock.

## Stack

- **Planner**: `bedrock/us.anthropic.claude-haiku-4-5-20251001-v1:0`
- **Agent**: Claude Code (inside Docker sandbox)
- **Tester**: `bedrock/us.anthropic.claude-sonnet-4-6`
- **Sandbox image**: `ftl-sandbox` (Debian, Python 3.11, Node 22, Claude Code, stripe/requests/httpx/boto3/openai/anthropic/pydantic pre-installed)

## Key files

- `ftl/planner.py` — planner loop, tester, action dispatch
- `ftl/orchestrator.py` — Session, run_task, credential shadowing wiring
- `ftl/diff.py` — diff compute + display + review
- `ftl/lint.py` — credential leak detection on diffs
- `ftl/config.py` — default config (update `.ftlconfig` manually in existing projects)
- `ftl/cli.py` — click CLI: init, code, snapshots, logs, auth
- `Dockerfile` — sandbox image

## Important behaviors

- First agent call always sends the raw user task verbatim (bypasses planner rewrite)
- Tester uses real sandbox credentials — no mocking
- `venv/`, `site-packages/`, `.dist-info/`, `.egg-info/` are excluded from diffs
- Lint flags hardcoded shadow values and known credential strings — reading env vars is allowed
- Bedrock models require `us.` inference profile prefix
- Elapsed time shown at each planner step; macOS notification fires on completion

## CLI

```bash
ftl init
ftl code 'task description'   # use single quotes if task contains $
ftl snapshots                  # list
ftl snapshots clean --last 10
ftl snapshots clean --all -y
ftl logs
```

## Reinstall / rebuild

```bash
pip install -e .
docker build -t ftl-sandbox .
```

## Vision & roadmap

Long-term: natural language computer interface — "write this code, switch to this playlist, email Brian". FTL is the secure execution + review layer.

Immediate next step (AWS competition, ~3 weeks): tool dispatch layer so the planner can invoke real-world actions alongside coding.

```json
{"action": "tool", "name": "email", "params": {"to": "brian@work.com", "message": "..."}}
{"action": "tool", "name": "slack", "params": {"channel": "#eng", "message": "..."}}
{"action": "tool", "name": "github", "params": {"op": "open_pr", "title": "..."}}
```

Contact resolution via `~/.ftl/world.yaml` populated from top 50 email/iMessage/Slack contacts.

Target demo: *"Write a Stripe payment module, open a PR, and Slack Brian it's ready."*
