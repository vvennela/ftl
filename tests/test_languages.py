from pathlib import Path

from ftl.languages import detect_project_language, detect_project_languages, language_test_runtime, resolve_language


def test_detect_project_language_prefers_go_mod(tmp_path):
    (tmp_path / "go.mod").write_text("module example.com/app\n")
    assert detect_project_language(tmp_path) == "go"


def test_detect_project_language_prefers_java_build_file(tmp_path):
    (tmp_path / "pom.xml").write_text("<project />\n")
    assert detect_project_language(tmp_path) == "java"


def test_detect_project_language_falls_back_to_cpp_extensions(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.cpp").write_text("int main() { return 0; }\n")
    assert detect_project_language(tmp_path) == "cpp"


def test_language_test_runtime_for_java_uses_single_file_runner():
    runtime = language_test_runtime("java")
    assert runtime["path"].endswith("FtlGeneratedTest.java")
    assert "java ./FtlGeneratedTest.java" in runtime["run"]


def test_detect_project_language_returns_none_for_empty_project(tmp_path):
    assert detect_project_language(tmp_path) is None


def test_detect_project_language_returns_none_for_multi_language_repo(tmp_path):
    (tmp_path / "go.mod").write_text("module example.com/app\n")
    (tmp_path / "package.json").write_text("{}\n")
    assert detect_project_language(tmp_path) is None
    assert detect_project_languages(tmp_path)[:2] == ["go", "typescript"]


def test_resolve_language_uses_path_overrides_for_diff_paths(tmp_path):
    language = resolve_language(
        tmp_path,
        overrides={"backend": "go", "web": "typescript"},
        diff_paths=["backend/service/main.go"],
    )
    assert language == "go"


def test_language_test_runtime_for_maven_project_falls_back_to_single_file_runner(tmp_path):
    (tmp_path / "pom.xml").write_text("<project />\n")
    runtime = language_test_runtime("java", project_path=tmp_path)
    assert runtime["path"].endswith("FtlGeneratedTest.java")
    assert "java ./FtlGeneratedTest.java" in runtime["run"]
