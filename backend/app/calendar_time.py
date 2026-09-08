"""Deterministic calendar time presentation; preserve the provider's raw values."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def event_time_summary(event: dict) -> dict:
    def display(value):
        if not isinstance(value, dict):
            return None
        if value.get('date') and not value.get('dateTime'):
            return f"{value['date']} (all day)"
        try:
            instant = datetime.fromisoformat(str(value.get('dateTime', '')).replace('Z', '+00:00'))
            if instant.tzinfo is None:
                return None  # A provider timestamp with no offset is not a known instant.
            utc = instant.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
            name = value.get('timeZone')
            if not name:
                return utc
            try:
                local = instant.astimezone(ZoneInfo(name)).strftime('%Y-%m-%d %H:%M %Z')
            except (ZoneInfoNotFoundError, ValueError):
                return utc
            return f'{utc} ({local}, {name})'
        except (ValueError, TypeError):
            return None
    return {'start': display(event.get('start')),
            'end': None if event.get('endTimeUnspecified') else display(event.get('end')),
            'end_time_unspecified': bool(event.get('endTimeUnspecified'))}


def annotate_calendar_times(result: dict) -> dict:
    if not isinstance(result, dict) or not isinstance(result.get('items'), list):
        return result
    return {**result, 'items': [{**event, 'canonical_time_summary': event_time_summary(event)}
                              if isinstance(event, dict) else event for event in result['items']]}
