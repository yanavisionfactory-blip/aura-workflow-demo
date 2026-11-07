"""Allowlisted diagnostics for Ads errors wrapped by the connector broker.

Never retain upstream messages, queries, headers, credentials or customer data.
Only fixed error codes and HTTP statuses may cross the provider boundary.
"""
import json
import re

AUTH_CODES = {
    "OAUTH_TOKEN_EXPIRED", "OAUTH_TOKEN_REVOKED", "OAUTH_TOKEN_DISABLED",
    "OAUTH_TOKEN_INVALID", "OAUTH_TOKEN_HEADER_INVALID", "INVALID_GRANT",
    "ACCESS_TOKEN_SCOPE_INSUFFICIENT",
}
CONFIG_CODES = {
    "DEVELOPER_TOKEN_INVALID", "DEVELOPER_TOKEN_NOT_APPROVED",
    "DEVELOPER_TOKEN_PROHIBITED", "DEVELOPER_TOKEN_NOT_ON_ALLOWLIST",
    "CLOUD_PROJECT_NOT_APPROVED_FOR_PRODUCTION", "PROJECT_DISABLED",
    "PROJECT_NOT_PERMITTED", "API_VERSION_UNSUPPORTED", "UNIMPLEMENTED",
}
ACCOUNT_CODES = {
    "USER_PERMISSION_DENIED", "CUSTOMER_NOT_ENABLED", "CUSTOMER_NOT_FOUND",
    "CLIENT_CUSTOMER_ID_INVALID", "NOT_ADS_USER", "ACTION_NOT_PERMITTED",
    "INVALID_LOGIN_CUSTOMER_ID_SERVING_CUSTOMER_ID_COMBINATION",
}
QUERY_CODES = {
    "UNRECOGNIZED_FIELD", "PROHIBITED_RESOURCE_TYPE_IN_SELECT_CLAUSE",
    "PROHIBITED_FIELD_COMBINATION_IN_SELECT_CLAUSE", "INVALID_DATE_FORMAT",
    "INVALID_DATE_RANGE", "REQUESTED_METRICS_FOR_MANAGER",
    "INVALID_VALUE_WITH_DURING_OPERATOR", "INVALID_VALUE_WITH_BETWEEN_OPERATOR",
    "EXPECTED_AND", "EXPECTED_FILTERS_ON_DATE_RANGE", "UNEXPECTED_INPUT",
    "BAD_FIELD_NAME", "BAD_ENUM_CONSTANT", "BAD_RESOURCE_TYPE_IN_FROM_CLAUSE",
    "PROHIBITED_FIELD_IN_SELECT_CLAUSE", "PROHIBITED_FIELD_OR_SEGMENT_WITH_METRIC",
    "PROHIBITED_METRIC_IN_SELECT_OR_WHERE_CLAUSE",
    "PROHIBITED_SEGMENT_IN_SELECT_OR_WHERE_CLAUSE",
    "PROHIBITED_SEGMENT_WITH_METRIC_IN_SELECT_OR_WHERE_CLAUSE",
    "DATE_RANGE_TOO_NARROW", "DATE_RANGE_TOO_WIDE", "MISALIGNED_DATE_FOR_FILTER",
    "INVALID_DATE", "START_DATE_AFTER_END_DATE", "REQUESTED_DATE_GRANULARITY_NOT_SUPPORTED",
}
CANONICAL_CODES = {
    "PERMISSION_DENIED", "UNAUTHENTICATED", "NOT_FOUND", "RESOURCE_EXHAUSTED",
    "FAILED_PRECONDITION", "INTERNAL", "UNAVAILABLE", "DEADLINE_EXCEEDED", "INVALID_ARGUMENT",
}
RUNTIME_CODES = {"TYPEERROR", "REFERENCEERROR", "SYNTAXERROR", "AXIOSERROR"}
CODES = AUTH_CODES | CONFIG_CODES | ACCOUNT_CODES | QUERY_CODES | CANONICAL_CODES | RUNTIME_CODES
_CODE = re.compile(r"(?<![A-Z0-9_])(" + "|".join(sorted(CODES)) + r")(?![A-Z0-9_])")
_HTTP = re.compile(r"(?:status code|HTTP(?:/\d(?:\.\d)?)?)\s*[:=]?\s*([45]\d\d)\b", re.IGNORECASE)
_KEYS = {"error", "errors", "errorCode", "error_code", "details", "response", "data",
         "message", "name", "type", "code", "status", "cause", "authenticationError",
         "authorizationError", "queryError", "requestError", "headerError",
         "dateRangeError", "dateError", "fieldError"}


def diagnose(errors):
    """Bounded traversal of known error envelopes, including JSON in messages."""
    pending = [(errors, 0)]
    codes, statuses = set(), set()
    for _ in range(256):
        if not pending:
            break
        value, depth = pending.pop()
        if depth > 16:
            continue
        if isinstance(value, dict):
            for key in ("status", "code"):
                status = value.get(key)
                if type(status) is int and 400 <= status <= 599:
                    statuses.add(status)
            pending.extend((item, depth + 1) for key, item in value.items() if key in _KEYS)
        elif isinstance(value, list):
            pending.extend((item, depth + 1) for item in value[:100])
        elif isinstance(value, str):
            value = value[:32768]
            codes.update(_CODE.findall(value.upper()))
            statuses.update(int(status) for status in _HTTP.findall(value))
            # Axios and broker wrappers sometimes prefix the JSON error body.
            start = value.find("{")
            if start >= 0:
                try:
                    payload, _ = json.JSONDecoder().raw_decode(value[start:])
                except (ValueError, TypeError):
                    pass
                else:
                    pending.append((payload, depth + 1))
    # Prefer the specific Ads reason to generic HTTP or JavaScript wrappers.
    for group in (AUTH_CODES, CONFIG_CODES, ACCOUNT_CODES, QUERY_CODES, CANONICAL_CODES, RUNTIME_CODES):
        matches = sorted(codes & group)
        if matches:
            return matches[0], min(statuses) if statuses else None
    status = min(statuses) if statuses else None
    return f"HTTP_{status}" if status else "ACTION_FAILED", status


def message(code):
    if code == "RESOURCE_EXHAUSTED":
        detail = ("Google Ads API quota is temporarily exhausted. AURA preserves the connection "
                  "and waits before retrying the read. Persistent quota limits need review in "
                  "the OAuth application's Google Cloud project; signing in again does not raise them.")
    elif code in AUTH_CODES:
        detail = "Google rejected the saved authorization. Reauthorize the same Google Ads account."
    elif code in CONFIG_CODES:
        detail = "The Google Ads API configuration needs repair by the connector operator; signing in again will not fix this error."
    elif code in ACCOUNT_CODES:
        detail = "Google rejected access to the selected advertising account. Check its enabled status, user access and manager-account selection."
    elif code == "REQUESTED_METRICS_FOR_MANAGER":
        detail = "Performance metrics cannot be read for a manager account. Select the advertising client account in the Google Ads account picker."
    elif code in {"INVALID_VALUE_WITH_DURING_OPERATOR", "EXPECTED_FILTERS_ON_DATE_RANGE"}:
        detail = "The report's date range is invalid or missing. Use a supported date range or explicit start and end dates; full-period totals must omit the date range and date segments."
    elif code in {"INVALID_DATE", "INVALID_DATE_FORMAT", "START_DATE_AFTER_END_DATE"}:
        detail = "The report dates are invalid. Use YYYY-MM-DD dates with the start on or before the end."
    elif code in QUERY_CODES or code == "INVALID_ARGUMENT":
        detail = "Google rejected the reporting query. Correct its fields, dates or account type before retrying."
    elif code in RUNTIME_CODES:
        detail = "The Google Ads connector action failed. Its implementation or upstream response needs investigation; authorization expiry is not established."
    else:
        detail = "Google Ads did not complete the request. The saved connection is preserved; this error alone does not establish that sign-in must be repeated."
    return f"Google Ads [{code}]: {detail}"


def public_message(error):
    """Reconstruct static text from our diagnostic marker, never echo its suffix."""
    match = re.search(r"(?:\[google_ads:|Google Ads \[)([A-Z0-9_]+)\]", error or "")
    if not match:
        return None
    code = match[1]
    if code in CODES or code == "ACTION_FAILED" or re.fullmatch(r"HTTP_[45]\d\d", code):
        return message(code)
    return None
