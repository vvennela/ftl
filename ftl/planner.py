import re
import litellm
litellm.suppress_debug_info = True
litellm.set_verbose = False
from rich.console import Console

from ftl.agents import get_agent, AGENTS
from ftl.languages import language_test_instructions, language_test_runtime


def _extract_missing_modules(output):
    """Return top-level package names from ModuleNotFoundError lines."""
    pattern = re.compile(r"ModuleNotFoundError: No module named '([^']+)'")
    return {m.split(".")[0] for m in pattern.findall(output)}


_FENCE_RE = re.compile(r"^```\w*\n(.*?)```$", re.DOTALL)

_TASK_TESTER_SYSTEM = (
    "You are an adversarial test engineer. Given a coding task description, "
    "generate a runnable test script that verifies the implementation is correct "
    "and tries to break it.\n\n"
    "Use terse, high-signal language. No filler, no motivational framing, no repeated setup. "
    "Output only what is needed to produce and explain the tests.\n\n"
    "Cover multiple test categories whenever they are relevant: happy path, edge cases, "
    "null/empty inputs, boundary values, malformed inputs, idempotency, error handling, "
    "permission/auth behavior, serialization/deserialization, filesystem behavior, "
    "network failure behavior, data integrity, and regression checks for the main requested behavior.\n\n"
    "Prefer a compact but comprehensive suite rather than a single smoke test. "
    "If the task implies an API, include request/response validation and failure cases. "
    "If it implies persistence or migrations, verify destructive and non-destructive paths. "
    "If it implies UI logic, verify validation and state transitions. "
    "If it implies background jobs or retries, verify retry limits and duplicate handling.\n\n"
    "IMPORTANT: Real API credentials are available as environment variables in the test environment. "
    "Use them directly when the task requires real integrations — do NOT mock or stub external API calls unless the task clearly does not involve live services."
)

_DIFF_TESTER_SYSTEM = (
    "You are an adversarial test engineer. Given code changes, generate a runnable test script "
    "that tries to break the implementation.\n\n"
    "Use terse, high-signal language. No filler, no throat-clearing, no repeated framing. "
    "Output only what is needed to produce and explain the tests.\n\n"
    "Cover multiple relevant categories: regression checks for the changed behavior, edge cases, "
    "boundary values, malformed inputs, error handling, idempotency, permission/auth behavior, "
    "filesystem or persistence effects, and failure recovery. Prefer concise but meaningful coverage.\n\n"
    "IMPORTANT: Real API credentials are available as environment variables. Do NOT mock external API calls when the changes rely on real integrations."
)


def _strip_fence(code):
    """Strip markdown code fences if present."""
    match = _FENCE_RE.search(code.strip())
    return match.group(1) if match else code


def _task_tester_system(language):
    return f"{_TASK_TESTER_SYSTEM}\n\n{language_test_instructions(language)}"


def _diff_tester_system(language):
    return f"{_DIFF_TESTER_SYSTEM}\n\n{language_test_instructions(language)}"


def generate_tests_from_task(task, model, language="python"):
    """Generate adversarial test code from a task description.

    Designed to run in parallel with the coding agent — doesn't need to see
    the implementation, just the task. Returns test code string, or None on failure.
    """
    try:
        response = litellm.completion(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": _task_tester_system(language),
                },
                {
                    "role": "user",
                    "content": f"Target language: {language}\n\nWrite tests for this coding task:\n\n{task}",
                },
            ],
        )
        return _strip_fence(response.choices[0].message.content)
    except Exception:
        return None


def run_test_code(test_code, sandbox, console, language="python", project_path=None):
    """Write test code into the sandbox and run it. Returns (exit_code, output)."""
    test_code = _strip_fence(test_code)
    runtime = language_test_runtime(language, project_path=project_path)
    test_file = runtime["path"]
    run_cmd = runtime["run"]
    cleanup_cmd = runtime["cleanup"]

    sandbox.exec(f"mkdir -p $(dirname {test_file}) && cat > {test_file} << 'FTLEOF'\n{test_code}\nFTLEOF")

    exit_code, stdout, stderr = sandbox.exec(run_cmd)

    # If tests failed due to missing modules, install them and retry once.
    missing = _extract_missing_modules(stdout + stderr)
    if missing and exit_code != 0 and language == "python":
        sandbox.exec(f"pip install {' '.join(missing)} -q")
        exit_code, stdout, stderr = sandbox.exec(run_cmd)

    sandbox.exec(cleanup_cmd)

    if exit_code == 0:
        console.print("[green]  Tests passed.[/green]")
    else:
        console.print("[yellow]  Tests failed:[/yellow]")
        console.print(f"[dim]{stdout}{stderr}[/dim]")

    return exit_code, stdout + stderr


def run_verification(diffs, tester, sandbox, language="python", project_path=None):
    """Manual test trigger: generate tests from diff and run them."""
    from ftl.diff import diff_to_text

    console = Console()
    console.print(f"[bold]Running verification ({tester})...[/bold]")

    if tester in AGENTS:
        agent = get_agent(tester)
        diff_text = diff_to_text(diffs)
        task = (
            "Review the following code changes and write tests that try to break them. "
            "Focus on edge cases, null inputs, boundary conditions, and unexpected usage. "
            f"Target language: {language}. Run the tests and report results.\n\n"
            f"{diff_text}"
        )
        exit_code, stdout, stderr = agent.run(task, "/workspace", sandbox)
        output = stdout + stderr
    else:
        diff_text = diff_to_text(diffs)
        try:
            response = litellm.completion(
                model=tester,
                messages=[
                    {
                        "role": "system",
                        "content": _diff_tester_system(language),
                    },
                    {
                        "role": "user",
                        "content": f"Target language: {language}\n\nWrite tests to find bugs in these changes:\n\n{diff_text}",
                    },
                ],
            )
        except Exception as e:
            console.print(f"[red]  Tester API error: {e}[/red]")
            return 1, "", str(e)

        test_code = response.choices[0].message.content
        exit_code, output = run_test_code(test_code, sandbox, console, language=language, project_path=project_path)
        stdout, stderr = output, ""

    if tester in AGENTS:
        if exit_code == 0:
            console.print("[green]  Tests passed.[/green]")
        else:
            console.print("[yellow]  Tests failed:[/yellow]")
            console.print(f"[dim]{output}[/dim]")

    return exit_code, stdout, stderr
