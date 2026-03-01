"""Optional CloudWatch Logs tracing for FTL sessions.

Emits structured JSON spans to a CloudWatch log stream so every session
produces a full execution trace queryable via CloudWatch Insights.

Activated when `cloudwatch_log_group` is set in .ftlconfig and boto3 is
installed (`pip install -e ".[aws]"`). Silently no-ops otherwise.

Span types:
    stage   — snapshot, boot, agent, tests (elapsed_ms)
    tool    — each agent tool call: Read, Write, Bash, etc. (name, elapsed_ms)
    session — start, merge, reject (task, result, files_changed, etc.)

CloudWatch Insights query to debug a session:
    filter trace_id = "abc12345" | sort @timestamp asc
"""

import json
import threading
import time
from datetime import datetime, timezone

_client = None
_log_group = None
_log_stream = None
_lock = threading.Lock()


def init(log_group, log_stream):
    """Initialize the CloudWatch singleton for a session.

    Must be called once per session before any emit() calls.
    No-ops if log_group is empty or boto3 is unavailable.
    """
    global _client, _log_group, _log_stream
    if not log_group:
        return
    try:
        import boto3
        _client = boto3.client("logs")
        _log_group = log_group
        _log_stream = log_stream
        _ensure()
    except Exception:
        _client = None


def emit(trace_id, span_type, name, elapsed_ms=None, **meta):
    """Emit a single span to CloudWatch Logs.

    Always returns immediately; never raises. All errors are silently swallowed
    because tracing is optional and must never break the main workflow.
    """
    if not _client:
        return
    event = {
        "trace_id": trace_id,
        "span_type": span_type,
        "name": name,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if elapsed_ms is not None:
        event["elapsed_ms"] = round(elapsed_ms)
    event.update(meta)
    with _lock:
        try:
            _client.put_log_events(
                logGroupName=_log_group,
                logStreamName=_log_stream,
                logEvents=[{"timestamp": int(time.time() * 1000),
                            "message": json.dumps(event)}],
            )
        except Exception:
            pass  # logging is optional, never raise


def _ensure():
    """Create the log group and log stream if they don't already exist."""
    for create, kwargs in [
        (_client.create_log_group, {"logGroupName": _log_group}),
        (_client.create_log_stream, {"logGroupName": _log_group,
                                     "logStreamName": _log_stream}),
    ]:
        try:
            create(**kwargs)
        except Exception:
            pass  # ResourceAlreadyExistsException or no permissions — fine
