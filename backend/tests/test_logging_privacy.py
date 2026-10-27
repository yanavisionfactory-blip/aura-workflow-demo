import logging

import pytest
from uvicorn.logging import AccessFormatter

from app import main  # noqa: F401 — exercises installation during API import
from app.logging_privacy import AccessLogPrivacyFilter, protect_access_logs


@pytest.mark.parametrize("target", [
    "/v1/oauth/frameio/callback?code=private-code&state=private-state",
    "/v1/oauth/mcp-agent/callback?error_description=private-detail&state=private-state",
    "/v1/health?unknown-credential=private-value",
])
def test_access_logs_omit_query_values_and_preserve_request_metadata(target):
    logger = logging.getLogger("uvicorn.access")
    record = logger.makeRecord(
        logger.name, logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:1234", "GET", target, "1.1", 307), None,
    )
    assert logger.filter(record)
    rendered = AccessFormatter(
        '%(client_addr)s - "%(request_line)s" %(status_code)s', use_colors=False,
    ).format(record)
    assert "private-" not in rendered + record.getMessage()
    assert "?" not in rendered
    assert target.partition("?")[0] in rendered
    assert "GET" in rendered and "307" in rendered and "127.0.0.1:1234" in rendered


def test_access_log_protection_is_idempotent_and_retains_queryless_requests():
    logger = logging.getLogger("uvicorn.access")
    protect_access_logs()
    protect_access_logs()
    assert sum(isinstance(item, AccessLogPrivacyFilter) for item in logger.filters) == 1
    record = logger.makeRecord(
        logger.name, logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:1234", "GET", "/ready", "1.1", 200), None,
    )
    assert logger.filter(record)
    assert record.getMessage() == '127.0.0.1:1234 - "GET /ready HTTP/1.1" 200'
