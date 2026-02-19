import json
from rich.console import Console
import litellm

from ftl.agents import get_agent, AGENTS
from ftl.diff import compute_diff, diff_to_text

PLANNER_SYSTEM_PROMPT = """\
You are a task planner for a coding agent. You break down coding tasks into steps \
and drive a sandboxed coding agent to complete them.

You can ONLY respond with a single JSON object. No other text. Pick one action:

{"action": "agent", "message": "instruction for the coding agent"}
{"action": "test", "reason": "why you want to run tests now"}
{"action": "done", "summary": "what was accomplished"}
{"action": "clarify", "question": "question for the user"}

Rules:
- You do NOT write code. The agent writes code. You tell it WHAT to build.
- Give the agent clear, specific instructions. One step at a time.
- After the agent completes a step, review its output and decide the next action.
- Call "test" after the agent has written enough code to be testable.
- If tests fail, tell the agent to fix the specific failures.
- Call "done" only when the task is fully complete and tests pass.
- Call "clarify" if the user's request is ambiguous and you need more information.
- Respond with ONLY the JSON object. No markdown, no explanation, no wrapping.
"""


def _parse_action(text):
    """Parse planner response into an action dict. Returns None on failure."""
    text = text.strip()

    # Strip markdown code fences if present
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.startswith("```")]
        text = "\n".join(lines).strip()

    try:
        action = json.loads(text)
    except json.JSONDecodeError:
        return None

    if not isinstance(action, dict) or "action" not in action:
        return None

    if action["action"] not in ("agent", "test", "done", "clarify"):
        return None

    return action


def _run_tests_with_model(diffs, model, sandbox):
    """Generate and run tests using an LLM model via LiteLLM."""
    import re

    diff_text = diff_to_text(diffs)

    try:
        response = litellm.completion(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an adversarial test engineer. Given code changes, generate "
                        "a test script that tries to break the code. Focus on edge cases, "
                        "null inputs, boundary conditions, and unexpected usage. Your goal is "
                        "to find bugs. Output ONLY the test script, no explanation. Use the "
                        "appropriate test framework (pytest for Python, jest/vitest for JS/TS)."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Write tests to find bugs in these changes:\n\n{diff_text}",
                },
            ],
        )
    except Exception as e:
        return 1, "", f"Tester API error: {e}"

    test_code = response.choices[0].message.content

    fence_pattern = re.compile(r"^```\w*\n(.*?)```$", re.DOTALL)
    match = fence_pattern.search(test_code.strip())
    if match:
        test_code = match.group(1)

    sandbox.exec(f"cat > /workspace/_ftl_test.py << 'FTLEOF'\n{test_code}\nFTLEOF")
    exit_code, stdout, stderr = sandbox.exec(
        "cd /workspace && python -m pytest _ftl_test.py -v 2>&1 || node _ftl_test.py 2>&1"
    )
    sandbox.exec("rm -f /workspace/_ftl_test.py")

    return exit_code, stdout, stderr


def _run_tests_with_agent(diffs, agent_name, sandbox):
    """Run tests using a coding agent inside the sandbox."""
    diff_text = diff_to_text(diffs)
    agent = get_agent(agent_name)

    task = (
        "Review the following code changes and write tests that try to break them. "
        "Focus on edge cases, null inputs, boundary conditions, and unexpected usage. "
        "Run the tests and report results.\n\n"
        f"{diff_text}"
    )

    return agent.run(task, "/workspace", sandbox)


def run_verification(diffs, tester, sandbox):
    """Route to model or agent based on tester config."""
    console = Console()
    console.print(f"[bold]Running verification ({tester})...[/bold]")

    if tester in AGENTS:
        exit_code, stdout, stderr = _run_tests_with_agent(diffs, tester, sandbox)
    else:
        exit_code, stdout, stderr = _run_tests_with_model(diffs, tester, sandbox)

    if exit_code == 0:
        console.print("[green]  Tests passed.[/green]")
    else:
        console.print("[yellow]  Tests failed:[/yellow]")
        console.print(f"[dim]{stdout}{stderr}[/dim]")

    return exit_code, stdout, stderr


class PlannerLoop:
    """Planner-driven orchestration loop.

    The planner (cheap model) breaks a task into steps and drives
    the coding agent (expensive model) inside the sandbox.
    """

    def __init__(self, config, sandbox, snapshot_path, workspace):
        self.config = config
        self.sandbox = sandbox
        self.snapshot_path = snapshot_path
        self.workspace = workspace
        self.console = Console()

        self.planner_model = config.get("planner_model", "bedrock/amazon.nova-lite-v1:0")
        self.agent_name = config.get("agent", "claude-code")
        self.tester = config.get("tester", "bedrock/deepseek-r1")
        self.max_steps = config.get("planner_max_steps", 20)

        self.agent = get_agent(self.agent_name)
        self.agent_calls = 0  # tracks whether to use -c (continue)
        self.messages = []  # planner conversation history

    def run(self, task):
        """Run the planner loop for a task. Returns diffs when done."""
        self.console.print(f"[bold]Planner decomposing task...[/bold]")

        # Only set initial messages if this is a fresh run (not a follow-up)
        if not self.messages:
            self.messages = [
                {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
                {"role": "user", "content": f"User task: {task}"},
            ]

        for step in range(self.max_steps):
            # Ask planner for next action
            try:
                response = litellm.completion(
                    model=self.planner_model,
                    messages=self.messages,
                )
            except Exception as e:
                self.console.print(f"[red]  Planner API error: {e}[/red]")
                self.console.print("[yellow]  Stopping planner loop. Use 'diff' to see current state.[/yellow]")
                break

            raw = response.choices[0].message.content
            self.messages.append({"role": "assistant", "content": raw})

            action = _parse_action(raw)
            if action is None:
                # Bad output — ask planner to try again
                self.console.print("[dim]  Planner returned invalid action, retrying...[/dim]")
                self.messages.append({
                    "role": "user",
                    "content": "Invalid response. Reply with ONLY a JSON object with one of: "
                               '{"action": "agent", "message": "..."}, '
                               '{"action": "test", "reason": "..."}, '
                               '{"action": "done", "summary": "..."}, '
                               '{"action": "clarify", "question": "..."}',
                })
                continue

            # Execute action
            if action["action"] == "agent":
                result = self._do_agent(action["message"])
                self.messages.append({"role": "user", "content": f"Agent result:\n{result}"})

            elif action["action"] == "test":
                result = self._do_test(action.get("reason", ""))
                self.messages.append({"role": "user", "content": f"Test result:\n{result}"})

            elif action["action"] == "done":
                self.console.print(f"[bold green]  Planner: done — {action.get('summary', '')}[/bold green]")
                break

            elif action["action"] == "clarify":
                answer = self._do_clarify(action["question"])
                self.messages.append({"role": "user", "content": f"User answer: {answer}"})

        else:
            self.console.print(f"[yellow]  Planner hit max steps ({self.max_steps}). Stopping.[/yellow]")

        # Compute final diff
        diffs = compute_diff(self.snapshot_path, self.workspace)
        return diffs

    def inject_message(self, message):
        """Inject a user follow-up message into the planner's context.

        Used by the shell when the user types additional instructions
        during an active session.
        """
        self.messages.append({"role": "user", "content": f"User follow-up: {message}"})

    def _do_agent(self, message):
        """Send a message to the coding agent inside the sandbox."""
        self.console.print(f"[bold cyan]  → Agent: {message}[/bold cyan]")

        if self.agent_calls == 0:
            exit_code, stdout, stderr = self.agent.run(message, "/workspace", self.sandbox)
        else:
            exit_code, stdout, stderr = self.agent.continue_run(message, "/workspace", self.sandbox)

        self.agent_calls += 1

        output = stdout or ""
        if stderr:
            output += f"\nSTDERR: {stderr}"
        if exit_code != 0:
            output += f"\n[exit code: {exit_code}]"

        # Truncate long output for planner context
        if len(output) > 4000:
            output = output[:2000] + "\n...[truncated]...\n" + output[-2000:]

        self.console.print(f"[dim]  ← Agent responded ({len(output)} chars)[/dim]")
        return output

    def _do_test(self, reason):
        """Run the tester against current changes."""
        self.console.print(f"[bold]  Running tests ({reason})...[/bold]")

        diffs = compute_diff(self.snapshot_path, self.workspace)
        if not diffs:
            return "No changes detected — nothing to test."

        exit_code, stdout, stderr = run_verification(diffs, self.tester, self.sandbox)

        result = f"Exit code: {exit_code}\n{stdout}"
        if stderr:
            result += f"\nSTDERR: {stderr}"

        if len(result) > 4000:
            result = result[:2000] + "\n...[truncated]...\n" + result[-2000:]

        return result

    def _do_clarify(self, question):
        """Ask the user a clarifying question."""
        self.console.print(f"\n[bold yellow]  Planner asks: {question}[/bold yellow]")
        try:
            answer = input("  > ").strip()
        except (KeyboardInterrupt, EOFError):
            answer = "skip"
        return answer
