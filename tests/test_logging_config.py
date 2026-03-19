import json
import logging

from src.logging_config import JSONFormatter, SensitiveFilter, setup_logging


class TestJSONFormatter:
    def test_formats_as_valid_json(self):
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="Hello world", args=(), exc_info=None,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert parsed["level"] == "INFO"
        assert parsed["message"] == "Hello world"
        assert parsed["logger"] == "test"
        assert "timestamp" in parsed

    def test_includes_exception_info(self):
        formatter = JSONFormatter()
        try:
            raise ValueError("test error")
        except ValueError:
            import sys
            exc_info = sys.exc_info()
        record = logging.LogRecord(
            name="test", level=logging.ERROR, pathname="", lineno=0,
            msg="Something failed", args=(), exc_info=exc_info,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert "exception" in parsed
        assert "ValueError" in parsed["exception"]

    def test_includes_extra_context(self):
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="With extra", args=(), exc_info=None,
        )
        record.request_id = "abc-123"
        output = formatter.format(record)
        parsed = json.loads(output)
        assert parsed["request_id"] == "abc-123"


class TestSensitiveFilter:
    def test_redacts_session_token(self):
        filt = SensitiveFilter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="session_token=super-secret-token", args=(), exc_info=None,
        )
        filt.filter(record)
        assert "super-secret-token" not in record.msg
        assert "REDACTED" in record.msg

    def test_redacts_api_key(self):
        filt = SensitiveFilter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="api_key=my-key-123", args=(), exc_info=None,
        )
        filt.filter(record)
        assert "my-key-123" not in record.msg
        assert "REDACTED" in record.msg

    def test_redacts_in_args(self):
        filt = SensitiveFilter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="Connecting with %s", args=("password=hunter2",), exc_info=None,
        )
        filt.filter(record)
        assert "hunter2" not in record.args[0]
        assert "REDACTED" in record.args[0]

    def test_passes_safe_messages(self):
        filt = SensitiveFilter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="GET /employee -> 200", args=(), exc_info=None,
        )
        result = filt.filter(record)
        assert result is True
        assert record.msg == "GET /employee -> 200"


class TestSetupLogging:
    def test_configures_root_logger(self):
        setup_logging()
        root = logging.getLogger()
        assert len(root.handlers) >= 1
        handler = root.handlers[0]
        assert isinstance(handler.formatter, JSONFormatter)
        # Check that filter is applied
        assert any(isinstance(f, SensitiveFilter) for f in handler.filters)
