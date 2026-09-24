import asyncio
from unittest.mock import AsyncMock

from app.calendar_time import annotate_calendar_times, event_time_summary
from app.providers import ProviderExecutor


def test_mixed_offset_and_named_timezone_uses_the_actual_instant():
    event = {'start': {'dateTime': '2026-09-11T02:15:00-05:00', 'timeZone': 'Europe/Berlin'},
             'end': {'dateTime': '2026-09-11T03:15:00-05:00'}, 'endTimeUnspecified': True}
    result = annotate_calendar_times({'items': [event]})
    summary = result['items'][0]['canonical_time_summary']
    assert summary['start'] == '2026-09-11 07:15 UTC (2026-09-11 09:15 CEST, Europe/Berlin)'
    assert summary['end'] is None
    assert 'canonical_time_summary' not in event
    assert result['items'][0]['start'] == event['start']


def test_dst_and_all_day_events_are_not_guessed():
    result = event_time_summary({'start': {'dateTime': '2026-12-11T07:15:00Z', 'timeZone': 'Europe/Berlin'}})
    assert result['start'] == '2026-12-11 07:15 UTC (2026-12-11 08:15 CET, Europe/Berlin)'
    assert event_time_summary({'start': {'date': '2026-09-11'}})['start'] == '2026-09-11 (all day)'
    assert event_time_summary({'start': {'dateTime': '2026-09-11T07:15:00'}})['start'] is None


def test_calendar_create_and_readback_present_equivalent_offsets_as_one_meeting(monkeypatch):
    event = {
        'id': 'event-1',
        'start': {'dateTime': '2026-09-24T03:00:00-05:00', 'timeZone': 'Europe/Berlin'},
        'end': {'dateTime': '2026-09-24T03:30:00-05:00', 'timeZone': 'Europe/Berlin'},
    }
    executor = ProviderExecutor({'access_token': 'test-token'})
    request = AsyncMock(return_value=event)
    monkeypatch.setattr(executor, '_request', request)
    approved = {
        'title': 'Discuss story',
        'start': {'dateTime': '2026-09-24T10:00:00+02:00', 'timeZone': 'Europe/Berlin'},
        'end': {'dateTime': '2026-09-24T10:30:00+02:00', 'timeZone': 'Europe/Berlin'},
    }
    created = asyncio.run(executor._calendar_create(approved))
    observed = asyncio.run(executor._calendar_get({'event_id': 'event-1'}))
    for result in (created, observed):
        assert result['canonical_time_summary']['start'] == '2026-09-24 08:00 UTC (2026-09-24 10:00 CEST, Europe/Berlin)'
        assert result['canonical_time_summary']['end'] == '2026-09-24 08:30 UTC (2026-09-24 10:30 CEST, Europe/Berlin)'
        assert result['start'] == event['start']
    assert 'canonical_time_summary' not in event
