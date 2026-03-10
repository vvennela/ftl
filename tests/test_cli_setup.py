from types import SimpleNamespace

from click.testing import CliRunner

from ftl import cli


def _docker_ok(stdout=""):
    return SimpleNamespace(returncode=0, stdout=stdout, stderr="")


def test_setup_prompts_for_openai_key_when_codex_selected(monkeypatch):
    prompts = []
    saved_credentials = []
    saved_config = []

    def fake_run(cmd, capture_output=True, check=False, text=False):
        if cmd[:2] == ["docker", "info"]:
            return _docker_ok()
        if cmd[:3] == ["docker", "images", "-q"]:
            return _docker_ok("")
        raise AssertionError(f"Unexpected subprocess.run call: {cmd}")

    def fake_prompt(text, **kwargs):
        prompts.append(text.strip())
        if text.strip() == "Choice":
            return "2"
        if text.strip() == "OPENAI_API_KEY":
            return "sk-openai"
        raise AssertionError(f"Unexpected prompt: {text}")

    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    monkeypatch.setattr(cli, "_pull_or_build", lambda console, hub_tag, local_agents: None)
    monkeypatch.setattr(cli, "_prompt_model", lambda console, role, saved_keys: (f"{role}-model", saved_keys))
    monkeypatch.setattr(cli.click, "prompt", fake_prompt)
    monkeypatch.setattr(cli.click, "confirm", lambda *args, **kwargs: True)
    monkeypatch.setattr(cli, "save_ftl_credential", lambda key, value: saved_credentials.append((key, value)))
    monkeypatch.setattr(cli, "save_global_config", lambda updates: saved_config.append(updates))
    monkeypatch.setattr(cli, "_has_saved_credential", lambda key: False)
    monkeypatch.setattr(cli, "load_global_config", lambda: {})

    result = CliRunner().invoke(cli.main, ["setup"])

    assert result.exit_code == 0
    assert ("OPENAI_API_KEY", "sk-openai") in saved_credentials
    assert all(key != "ANTHROPIC_API_KEY" for key, _ in saved_credentials)
    assert prompts[:2] == ["Choice", "OPENAI_API_KEY"]
    assert {"agent": "codex"} in saved_config


def test_setup_prompts_for_anthropic_key_when_claude_selected(monkeypatch):
    prompts = []
    saved_credentials = []

    def fake_run(cmd, capture_output=True, check=False, text=False):
        if cmd[:2] == ["docker", "info"]:
            return _docker_ok()
        if cmd[:3] == ["docker", "images", "-q"]:
            return _docker_ok("")
        raise AssertionError(f"Unexpected subprocess.run call: {cmd}")

    def fake_prompt(text, **kwargs):
        prompts.append(text.strip())
        if text.strip() == "Choice":
            return "1"
        if text.strip() == "ANTHROPIC_API_KEY":
            return "sk-ant-test"
        raise AssertionError(f"Unexpected prompt: {text}")

    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    monkeypatch.setattr(cli, "_pull_or_build", lambda console, hub_tag, local_agents: None)
    monkeypatch.setattr(cli, "_prompt_model", lambda console, role, saved_keys: (f"{role}-model", saved_keys))
    monkeypatch.setattr(cli.click, "prompt", fake_prompt)
    monkeypatch.setattr(cli.click, "confirm", lambda *args, **kwargs: True)
    monkeypatch.setattr(cli, "save_ftl_credential", lambda key, value: saved_credentials.append((key, value)))
    monkeypatch.setattr(cli, "save_global_config", lambda updates: None)
    monkeypatch.setattr(cli, "_has_saved_credential", lambda key: False)
    monkeypatch.setattr(cli, "load_global_config", lambda: {})

    result = CliRunner().invoke(cli.main, ["setup"])

    assert result.exit_code == 0
    assert ("ANTHROPIC_API_KEY", "sk-ant-test") in saved_credentials
    assert prompts[:2] == ["Choice", "ANTHROPIC_API_KEY"]
