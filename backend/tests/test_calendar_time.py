from app.calendar_time import annotate_calendar_times, event_time_summary


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
