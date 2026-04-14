from pathlib import Path


SUPPORTED_LANGUAGES = {"python", "typescript", "go", "java", "cpp"}


def _validate_language(language):
    if language not in SUPPORTED_LANGUAGES:
        raise ValueError(f"Unsupported language override: {language}")
    return language


def detect_project_languages(project_path):
    """Return all detected languages for a project, ordered by confidence."""
    root = Path(project_path)
    if not root.exists():
        return []

    markers = [
        ("go", ["go.mod"]),
        ("java", ["pom.xml", "build.gradle", "build.gradle.kts", "gradlew", "mvnw"]),
        ("typescript", ["package.json", "tsconfig.json"]),
        ("python", ["pyproject.toml", "requirements.txt", "setup.py", "setup.cfg"]),
        ("cpp", ["CMakeLists.txt", "Makefile"]),
    ]

    detected = []
    for language, files in markers:
        if any((root / name).exists() for name in files):
            detected.append(language)

    counts = {
        "python": len(list(root.rglob("*.py"))),
        "typescript": len(list(root.rglob("*.ts"))) + len(list(root.rglob("*.tsx"))) + len(list(root.rglob("*.js"))) + len(list(root.rglob("*.jsx"))),
        "go": len(list(root.rglob("*.go"))),
        "java": len(list(root.rglob("*.java"))),
        "cpp": (
            len(list(root.rglob("*.c"))) +
            len(list(root.rglob("*.cc"))) +
            len(list(root.rglob("*.cpp"))) +
            len(list(root.rglob("*.cxx"))) +
            len(list(root.rglob("*.h"))) +
            len(list(root.rglob("*.hpp")))
        ),
    }

    for language, count in sorted(counts.items(), key=lambda item: item[1], reverse=True):
        if count and language not in detected:
            detected.append(language)

    return detected


def detect_top_level_languages(project_path):
    """Return likely top-level folder to language mappings for mixed repos."""
    root = Path(project_path)
    if not root.exists():
        return {}

    suffix_map = {
        ".py": "python",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".js": "typescript",
        ".jsx": "typescript",
        ".go": "go",
        ".java": "java",
        ".c": "cpp",
        ".cc": "cpp",
        ".cpp": "cpp",
        ".cxx": "cpp",
        ".h": "cpp",
        ".hpp": "cpp",
    }

    counts = {}
    for file_path in root.rglob("*"):
        if not file_path.is_file():
            continue
        language = suffix_map.get(file_path.suffix.lower())
        if not language:
            continue
        try:
            rel = file_path.relative_to(root)
        except ValueError:
            continue
        if not rel.parts:
            continue
        top = rel.parts[0]
        if top.startswith("."):
            continue
        counts.setdefault(top, {})
        counts[top][language] = counts[top].get(language, 0) + 1

    resolved = {}
    for top, lang_counts in counts.items():
        language, count = max(lang_counts.items(), key=lambda item: item[1])
        total = sum(lang_counts.values())
        if count and count / total >= 0.75:
            resolved[top] = language
    return resolved


def detect_project_language(project_path, override=None):
    """Detect a single project language, returning None when the repo is ambiguous."""
    if override:
        return _validate_language(override.lower())

    detected = detect_project_languages(project_path)
    return detected[0] if len(detected) == 1 else None


def resolve_language(project_path, configured_language=None, overrides=None, diff_paths=None):
    """Resolve the active language for a session or diff set."""
    return resolve_language_details(project_path, configured_language, overrides, diff_paths)["language"]


def resolve_language_details(project_path, configured_language=None, overrides=None, diff_paths=None):
    """Return the active language and how it was chosen."""
    if configured_language:
        return {
            "language": _validate_language(configured_language.lower()),
            "source": "configured",
            "matched": [],
            "ambiguous": False,
        }

    overrides = overrides or {}
    matched = set()
    matched_prefixes = []
    for rel in diff_paths or []:
        rel = rel.replace("\\", "/")
        for prefix, language in overrides.items():
            normalized = prefix.strip("/").replace("\\", "/")
            if rel == normalized or rel.startswith(normalized + "/"):
                matched.add(_validate_language(language.lower()))
                matched_prefixes.append(normalized)
    if len(matched) == 1:
        return {
            "language": next(iter(matched)),
            "source": "override",
            "matched": sorted(set(matched_prefixes)),
            "ambiguous": False,
        }
    if len(matched) > 1:
        return {
            "language": None,
            "source": "override",
            "matched": sorted(set(matched_prefixes)),
            "ambiguous": True,
        }

    detected = detect_project_language(project_path)
    return {
        "language": detected,
        "source": "detected" if detected else "unknown",
        "matched": [],
        "ambiguous": False,
    }


def language_test_instructions(language):
    prompts = {
        "python": "Output ONLY the test script. Use pytest.",
        "typescript": (
            "Output ONLY the test script. Use a single self-contained TypeScript file that can run with ts-node. "
            "Do not rely on jest or vitest configuration unless the task explicitly requires it."
        ),
        "go": (
            "Output ONLY a single self-contained Go validation program with package main and a main() function. "
            "Use explicit checks and exit non-zero on failure."
        ),
        "java": (
            "Output ONLY a single self-contained Java source file named FtlGeneratedTest.java. "
            "Define class FtlGeneratedTest with a main(String[] args) entrypoint and fail by throwing exceptions."
        ),
        "cpp": (
            "Output ONLY a single self-contained C++17 source file with a main() function. "
            "Use assertions or explicit error exits and keep it runnable with g++."
        ),
    }
    return prompts[language]


def language_test_runtime(language, project_path=None):
    runtimes = {
        "python": {
            "path": "/workspace/_ftl_test.py",
            "run": "cd /workspace && python -m pytest _ftl_test.py -v 2>&1",
            "cleanup": "rm -f /workspace/_ftl_test.py",
        },
        "typescript": {
            "path": "/workspace/_ftl_test.ts",
            "run": "cd /workspace && ts-node _ftl_test.ts 2>&1",
            "cleanup": "rm -f /workspace/_ftl_test.ts",
        },
        "go": {
            "path": "/workspace/ftl_generated_check.go",
            "run": "cd /workspace && go run ./ftl_generated_check.go 2>&1",
            "cleanup": "rm -f /workspace/ftl_generated_check.go",
        },
        "java": {
            "path": "/workspace/FtlGeneratedTest.java",
            "run": "cd /workspace && java ./FtlGeneratedTest.java 2>&1",
            "cleanup": "rm -f /workspace/FtlGeneratedTest.java /workspace/src/test/java/FtlGeneratedTest.java",
        },
        "cpp": {
            "path": "/workspace/_ftl_test.cpp",
            "run": "cd /workspace && g++ -std=c++17 -O2 -Wall _ftl_test.cpp -o /tmp/ftl_test_bin && /tmp/ftl_test_bin 2>&1",
            "cleanup": "rm -f /workspace/_ftl_test.cpp /tmp/ftl_test_bin",
        },
    }
    return runtimes[language]
