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


def test_init_prompts_for_language_when_detection_fails(monkeypatch, tmp_path):
    prompts = []

    def fake_prompt(text, **kwargs):
        prompts.append(text)
        return "go"

    monkeypatch.setattr(cli, "find_config", lambda: None)
    monkeypatch.setattr(cli, "detect_project_language", lambda path: None)
    monkeypatch.setattr(cli.click, "prompt", fake_prompt)
    monkeypatch.setattr(cli, "init_config", lambda language=None, **kwargs: tmp_path / ".ftlconfig")
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(cli.main, ["init"])

    assert result.exit_code == 0
    assert "Project language could not be detected" in prompts[0]


def test_init_uses_detected_language_without_prompt(monkeypatch, tmp_path):
    captured = {}

    monkeypatch.setattr(cli, "find_config", lambda: None)
    monkeypatch.setattr(cli, "detect_project_language", lambda path: "java")
    monkeypatch.setattr(cli.click, "prompt", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("prompt should not be called")))
    monkeypatch.setattr(cli, "init_config", lambda language=None, **kwargs: captured.setdefault("language", language) or (tmp_path / ".ftlconfig"))
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(cli.main, ["init"])

    assert result.exit_code == 0
    assert captured["language"] == "java"


def test_init_prompts_for_primary_language_when_multiple_detected(monkeypatch, tmp_path):
    prompts = []

    def fake_prompt(text, **kwargs):
        prompts.append(text)
        if text == "This repo looks mixed. Setup mode":
            return "primary"
        return "typescript"

    monkeypatch.setattr(cli, "find_config", lambda: None)
    monkeypatch.setattr(cli, "detect_project_language", lambda path: None)
    monkeypatch.setattr(cli, "detect_project_languages", lambda path: ["go", "typescript"])
    monkeypatch.setattr(cli.click, "prompt", fake_prompt)
    monkeypatch.setattr(cli, "init_config", lambda language=None, **kwargs: tmp_path / ".ftlconfig")
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(cli.main, ["init"])

    assert result.exit_code == 0
    assert prompts[0] == "This repo looks mixed. Setup mode"
    assert "Multiple project languages detected" in prompts[1]


def test_root_config_aws_shortcut_runs_one_shot_config(monkeypatch):
    called = []

    monkeypatch.setattr(cli, "_configure_aws", lambda: called.append("aws"))

    result = CliRunner().invoke(cli.main, ["--config", "aws"])

    assert result.exit_code == 0
    assert called == ["aws"]
