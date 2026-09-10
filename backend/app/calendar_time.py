"""Deterministic calendar time presentation; preserve the provider's raw values."""
from datetime import datetime, timezone, date, time
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


def calendar_list_errors(arguments: dict, result: dict) -> list[str]:
    """Validate provider collection structure and interval overlap without an LLM.

    This accepts source evidence, not the semantic claim that an appointment was
    found. Event selection and final-request completeness remain separate checks.
    Google timeMin filters event ends; timeMax filters event starts, exclusively.
    """
    def instant(value):
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            raise ValueError('Missing offset')
        return parsed

    def event_instant(value):
        if value.get('dateTime'):
            return instant(value['dateTime'])
        zone = ZoneInfo(result['timeZone'])
        return datetime.combine(date.fromisoformat(value['date']), time(), tzinfo=zone)

    if not isinstance(result, dict) or not isinstance(result.get('items'), list):
        return ['Calendar response has no event collection']
    try:
        lower = instant(arguments['time_min']) if arguments.get('time_min') else None
        upper = instant(arguments['time_max']) if arguments.get('time_max') else None
        if lower and upper and lower >= upper:
            return ['Calendar query interval is invalid']
        for event in result['items']:
            if not isinstance(event, dict) or not event.get('id'):
                return ['Calendar event has no stable identifier']
            if event.get('status') == 'cancelled':
                continue
            start, end = event_instant(event['start']), event_instant(event['end'])
            if end < start:
                return ['Calendar event ends before it starts']
            if (lower and end <= lower) or (upper and start >= upper):
                return ['Calendar event falls outside the approved query interval']
    except (ValueError, KeyError, TypeError, AttributeError, ZoneInfoNotFoundError):
        return ['Calendar event or query has an invalid or unzoned time']
    return []
