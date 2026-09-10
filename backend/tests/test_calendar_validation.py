from copy import deepcopy
from types import SimpleNamespace

import pytest
from app.calendar_time import annotate_calendar_times, calendar_list_errors


BOUNDS = {'time_min': '2026-09-11T00:00:00Z', 'time_max': '2026-09-12T00:00:00Z'}


def evidence():
    return annotate_calendar_times({'timeZone': 'America/Chicago', 'items': [
        {'id': 'event', 'start': {'dateTime': '2026-09-11T02:15:00-05:00', 'timeZone': 'America/Chicago'},
         'end': {'dateTime': '2026-09-11T03:15:00-05:00'}, 'endTimeUnspecified': True}]})


def test_september_cdt_and_minus_five_are_consistent():
    result = evidence()
    assert '02:15 CDT' in result['items'][0]['canonical_time_summary']['start']
    assert '07:15 UTC' in result['items'][0]['canonical_time_summary']['start']
    assert calendar_list_errors(BOUNDS, result) == []


@pytest.mark.parametrize('start,end', [
    ('2026-09-10T01:00:00Z', '2026-09-10T02:00:00Z'),
    ('2026-09-12T00:00:00Z', '2026-09-12T01:00:00Z'),
    ('2026-09-11T09:00:00', '2026-09-11T10:00:00Z'),
    ('2026-09-11T09:00:00Z', '2026-09-11T08:00:00Z'),
])
def test_invalid_or_out_of_scope_events_are_rejected(start, end):
    result = evidence()
    result['items'][0].update(start={'dateTime': start}, end={'dateTime': end})
    assert calendar_list_errors(BOUNDS, result)


def test_overlap_all_day_and_empty_search_are_valid_source_evidence():
    result = evidence()
    result['items'][0].update(start={'date': '2026-09-10'}, end={'date': '2026-09-12'})
    assert calendar_list_errors(BOUNDS, result) == []
    assert calendar_list_errors(BOUNDS, {'items': []}) == []
    assert calendar_list_errors(BOUNDS, {'items': [{}]})


async def test_calendar_read_review_never_calls_model_but_enforces_completeness(monkeypatch):
    from app import orchestrator
    async def forbidden(*args, **kwargs):
        raise AssertionError('Calendar structure and time checks must not invoke a model or write verifier')
    monkeypatch.setattr(orchestrator, 'critique_step', forbidden)
    monkeypatch.setattr(orchestrator, 'check_provider_outcome', forbidden)
    step = SimpleNamespace(operation='calendar.list', output={})
    contract = {'arguments': BOUNDS, 'required_evidence': ['complete_collection']}
    result = evidence()
    decision = await orchestrator.review_recorded_result(None, None, step, None, contract, result)
    assert decision.action == 'accept'
    partial = deepcopy(result)
    partial['nextPageToken'] = 'page-two'
    decision = await orchestrator.review_recorded_result(None, None, step, None, contract, partial)
    assert decision.action == 'escalate'
