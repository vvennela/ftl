import re
import litellm
from rich.console import Console

from ftl.agents import get_agent, AGENTS


def _extract_missing_modules(output):
    """Return top-level package names from ModuleNotFoundError lines."""
    pattern = re.compile(r"ModuleNotFoundError: No module named '([^']+)'")
    return {m.split(".")[0] for m in pattern.findall(output)}


_FENCE_RE = re.compile(r"^```\w*\n(.*?)```$", re.DOTALL)


def _strip_fence(code):
    """Strip markdown code fences if present."""
    match = _FENCE_RE.search(code.strip())
    return match.group(1) if match else code


def generate_tests_from_task(task, model):
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
                    "content": (
                        "You are an adversarial test engineer. Given a coding task description, "
                        "generate a test script that verifies the implementation is correct "
                        "and tries to break it. Focus on edge cases, null inputs, boundary "
                        "conditions, and unexpected usage. Your goal is to find bugs.\n\n"
                        "Output ONLY the test script, no explanation. Use pytest for Python, "
                        "jest/vitest for JS/TS.\n\n"
                        "IMPORTANT: Real API credentials are available as environment variables "
                        "in the test environment. Use them directly — do NOT mock or stub "
                        "external API calls."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Write tests for this coding task:\n\n{task}",
                },
            ],
        )
        return _strip_fence(response.choices[0].message.content)
    except Exception:
        return None


def run_test_code(test_code, sandbox, console):
    """Write test code into the sandbox and run it. Returns (exit_code, output)."""
    test_code = _strip_fence(test_code)

    is_js = test_code.strip().startswith(("import ", "const ", "describe(", "test(", "it(", "require("))
    test_file = "/workspace/_ftl_test." + ("js" if is_js else "py")

    sandbox.exec(f"cat > {test_file} << 'FTLEOF'\n{test_code}\nFTLEOF")

    if is_js:
        run_cmd = f"cd /workspace && node {test_file} 2>&1"
    else:
        run_cmd = f"cd /workspace && python -m pytest {test_file} -v 2>&1"

    exit_code, stdout, stderr = sandbox.exec(run_cmd)

    # If tests failed due to missing modules, install them and retry once.
    missing = _extract_missing_modules(stdout + stderr)
    if missing and exit_code != 0:
        sandbox.exec(f"pip install {' '.join(missing)} -q")
        exit_code, stdout, stderr = sandbox.exec(run_cmd)

    sandbox.exec(f"rm -f {test_file}")

    if exit_code == 0:
        console.print("[green]  Tests passed.[/green]")
    else:
        console.print("[yellow]  Tests failed:[/yellow]")
        console.print(f"[dim]{stdout}{stderr}[/dim]")

    return exit_code, stdout + stderr


def run_verification(diffs, tester, sandbox):
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
            "Run the tests and report results.\n\n"
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
                        "content": (
                            "You are an adversarial test engineer. Given code changes, generate "
                            "a test script that tries to break the code. Output ONLY the test "
                            "script. Use pytest for Python, jest/vitest for JS/TS.\n\n"
                            "IMPORTANT: Real API credentials are available as environment "
                            "variables. Do NOT mock external API calls."
                        ),
                    },
                    {
                        "role": "user",
                        "content": f"Write tests to find bugs in these changes:\n\n{diff_text}",
                    },
                ],
            )
        except Exception as e:
            console.print(f"[red]  Tester API error: {e}[/red]")
            return 1, "", str(e)

        test_code = response.choices[0].message.content
        exit_code, output = run_test_code(test_code, sandbox, console)
        stdout, stderr = output, ""

    if tester in AGENTS:
        if exit_code == 0:
            console.print("[green]  Tests passed.[/green]")
        else:
            console.print("[yellow]  Tests failed:[/yellow]")
            console.print(f"[dim]{output}[/dim]")

    return exit_code, stdout, stderr
