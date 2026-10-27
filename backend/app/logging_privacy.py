"""Keep request metadata useful without retaining URL credentials in access logs."""

import logging


class AccessLogPrivacyFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # Uvicorn supplies (client, method, full_path, HTTP version, status).
        # OAuth codes, signed state, and other credentials can occur in queries.
        # Strip every query rather than maintaining an incomplete secret-name list.
        if isinstance(record.args, tuple) and len(record.args) == 5:
            client, method, target, version, status = record.args
            if isinstance(target, str):
                record.args = (client, method, target.partition("?")[0], version, status)
        return True


def protect_access_logs() -> None:
    access_logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(item, AccessLogPrivacyFilter) for item in access_logger.filters):
        access_logger.addFilter(AccessLogPrivacyFilter())
