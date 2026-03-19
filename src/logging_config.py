import json
import logging
import re
from datetime import datetime, timezone


SENSITIVE_PATTERNS = re.compile(
    r"(session_token|api_key|openai_api_key|password|secret|authorization|bearer)"
    r"[\s]*[=:]\s*['\"]?([^'\",\s}{]+)",
    re.IGNORECASE,
)


class SensitiveFilter(logging.Filter):
    """Redacts sensitive values from log messages."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = SENSITIVE_PATTERNS.sub(
                lambda m: f"{m.group(1)}=***REDACTED***", record.msg
            )
        if record.args:
            new_args = []
            for arg in record.args:
                if isinstance(arg, str):
                    arg = SENSITIVE_PATTERNS.sub(
                        lambda m: f"{m.group(1)}=***REDACTED***", arg
                    )
                new_args.append(arg)
            record.args = tuple(new_args)
        return True


class JSONFormatter(logging.Formatter):
    """Formats log records as JSON with timestamp, level, message, and extra context."""

    def format(self, record: logging.LogRecord) -> str:
        message = record.getMessage()
        log_entry = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "message": message,
            "logger": record.name,
        }
        if record.exc_info and record.exc_info[0] is not None:
            log_entry["exception"] = self.formatException(record.exc_info)
        # Include extra context fields (skip standard LogRecord attributes)
        standard_attrs = {
            "name", "msg", "args", "created", "relativeCreated", "exc_info",
            "exc_text", "stack_info", "lineno", "funcName", "pathname",
            "filename", "module", "thread", "threadName", "process",
            "processName", "levelname", "levelno", "msecs", "message",
            "taskName",
        }
        for key, value in record.__dict__.items():
            if key not in standard_attrs and not key.startswith("_"):
                log_entry[key] = value
        return json.dumps(log_entry, default=str)


def setup_logging(level: int = logging.INFO) -> None:
    """Configure structured JSON logging for the application."""
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Remove existing handlers to avoid duplicates
    root_logger.handlers.clear()

    handler = logging.StreamHandler()
    handler.setFormatter(JSONFormatter())
    handler.addFilter(SensitiveFilter())
    root_logger.addHandler(handler)
