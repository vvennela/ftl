"""Session audit logging.

Appends structured JSON entries to ~/.ftl/logs.jsonl.
Each entry records a session event (start, merge, reject) with timestamp,
task description, snapshot ID, and project path.
"""

import json
from datetime import datetime
from pathlib import Path

LOGS_FILE = Path.home() / ".ftl" / "logs.jsonl"


def write_log(entry):
    """Append a session log entry."""
    LOGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    entry["timestamp"] = datetime.now().isoformat()
    with open(LOGS_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")
