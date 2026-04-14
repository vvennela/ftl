from ftl.lint import lint_diffs


def test_lint_blocks_python_filesystem_delete_when_task_does_not_request_it():
    diffs = [
        {
            "path": "cleanup.py",
            "status": "created",
            "_content_bytes": b"import os\nos.remove('data.db')\n",
            "lines": [("+", "import os"), ("+", "os.remove('data.db')")],
        }
    ]

    violations = lint_diffs(diffs, task="add a status endpoint")

    assert len(violations) == 1
    assert violations[0].blocking is True
    assert violations[0].severity == "block"
    assert "os.remove" in violations[0].reason


def test_lint_allows_python_filesystem_delete_when_task_requests_cleanup():
    diffs = [
        {
            "path": "cleanup.py",
            "status": "created",
            "_content_bytes": b"from pathlib import Path\nPath('/tmp/cache').unlink()\n",
            "lines": [("+", "from pathlib import Path"), ("+", "Path('/tmp/cache').unlink()")],
        }
    ]

    violations = lint_diffs(diffs, task="delete the cache file after upload completes")

    assert len(violations) == 1
    assert violations[0].blocking is False
    assert violations[0].severity == "warn"


def test_lint_blocks_destructive_sql_in_non_python_files_without_permission():
    diffs = [
        {
            "path": "migration.sql",
            "status": "created",
            "lines": [("+", "DROP TABLE users;")],
        }
    ]

    violations = lint_diffs(diffs, task="add a users table")

    assert len(violations) == 1
    assert violations[0].blocking is True
    assert "DROP TABLE" in violations[0].reason


def test_lint_warns_for_allowed_destructive_sql_when_task_requests_it():
    diffs = [
        {
            "path": "migration.py",
            "status": "created",
            "_content_bytes": (
                b"def migrate(cursor):\n"
                b"    cursor.execute('TRUNCATE TABLE audit_logs')\n"
            ),
            "lines": [
                ("+", "def migrate(cursor):"),
                ("+", "    cursor.execute('TRUNCATE TABLE audit_logs')"),
            ],
        }
    ]

    violations = lint_diffs(diffs, task="truncate the audit_logs table before reseeding fixtures")

    assert len(violations) == 1
    assert violations[0].blocking is False
    assert "TRUNCATE TABLE" in violations[0].reason


def test_lint_blocks_js_filesystem_delete_without_permission():
    diffs = [
        {
            "path": "cleanup.ts",
            "status": "created",
            "_content_bytes": b"import fs from 'fs';\nfs.rm('/tmp/cache', { recursive: true })\n",
            "lines": [
                ("+", "import fs from 'fs';"),
                ("+", "fs.rm('/tmp/cache', { recursive: true })"),
            ],
        }
    ]

    violations = lint_diffs(diffs, task="add a dashboard widget")

    assert len(violations) == 1
    assert violations[0].blocking is True
    assert "fs API" in violations[0].reason


def test_lint_warns_for_allowed_js_sql_drop():
    diffs = [
        {
            "path": "migration.js",
            "status": "created",
            "_content_bytes": b"await db.query('DROP TABLE sessions')\n",
            "lines": [("+", "await db.query('DROP TABLE sessions')")],
        }
    ]

    violations = lint_diffs(diffs, task="drop the sessions table during cleanup")

    assert len(violations) == 1
    assert violations[0].blocking is False
    assert "DROP TABLE" in violations[0].reason


def test_lint_blocks_go_filesystem_delete_without_permission():
    diffs = [
        {
            "path": "cleanup.go",
            "status": "created",
            "_content_bytes": b"package main\nimport \"os\"\nfunc main() { os.RemoveAll(\"/tmp/cache\") }\n",
            "lines": [
                ("+", "package main"),
                ("+", "import \"os\""),
                ("+", "func main() { os.RemoveAll(\"/tmp/cache\") }"),
            ],
        }
    ]

    violations = lint_diffs(diffs, task="add a status endpoint")

    assert len(violations) == 1
    assert violations[0].blocking is True
    assert "Go os.Remove" in violations[0].reason


def test_lint_warns_for_allowed_java_delete():
    diffs = [
        {
            "path": "Cleanup.java",
            "status": "created",
            "_content_bytes": b"import java.nio.file.Files;\nclass Cleanup { void run() throws Exception { Files.deleteIfExists(null); } }\n",
            "lines": [
                ("+", "import java.nio.file.Files;"),
                ("+", "class Cleanup { void run() throws Exception { Files.deleteIfExists(null); } }"),
            ],
        }
    ]

    violations = lint_diffs(diffs, task="delete the cache file after upload completes")

    assert len(violations) == 1
    assert violations[0].blocking is False
    assert "Java Files.delete" in violations[0].reason


def test_lint_blocks_cpp_filesystem_delete_without_permission():
    diffs = [
        {
            "path": "cleanup.cpp",
            "status": "created",
            "_content_bytes": b"#include <filesystem>\nint main() { std::filesystem::remove_all(\"/tmp/cache\"); }\n",
            "lines": [
                ("+", "#include <filesystem>"),
                ("+", "int main() { std::filesystem::remove_all(\"/tmp/cache\"); }"),
            ],
        }
    ]

    violations = lint_diffs(diffs, task="add a dashboard widget")

    assert len(violations) == 1
    assert violations[0].blocking is True
    assert "C++ filesystem remove" in violations[0].reason
