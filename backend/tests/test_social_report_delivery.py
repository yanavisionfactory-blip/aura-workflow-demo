from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app import orchestrator
from app.agent_runtime import intent_bounded_tool_inventory
from app.connection_families import synthetic_source_families
from app.main import _record_data, _record_view
from app.native_connectors import NativeConnectorError, native_manifest, validate_module_arguments
from app.presentation_content import render_timeline
from app.sheet_quality import normalize_report_annotations, post_write_cell_errors

PROMPT = ('Only produce fake outcomes from X, TikTok and Meta. '
          'Create the Google Sheets report and Canva presentation for real through AURA.')


def test_synthetic_inputs_do_not_require_social_accounts_or_enter_planner_inventory():
    inventory = [{'slug': slug, 'name': name, 'connected': False, 'allowed_operations': []}
                 for slug, name in [('x', 'X'), ('tiktok', 'TikTok'), ('tiktok-ads', 'TikTok Ads'),
                                    ('meta-ads', 'Meta Ads'), ('google-sheets', 'Google Sheets'), ('canva', 'Canva')]]
    before = deepcopy(inventory)
    assert synthetic_source_families(PROMPT) == {'x', 'tiktok', 'meta-ads'}
    assert orchestrator.explicit_disconnected_capabilities(PROMPT, inventory) == ['sheets', 'canva']
    assert orchestrator.complete_connection_requirements(PROMPT, ['x', 'tiktok-ads', 'meta-ads'], inventory) == ['sheets', 'canva']
    assert [i['slug'] for i in intent_bounded_tool_inventory(PROMPT, inventory)] == ['google-sheets', 'canva']
    assert inventory == before


@pytest.mark.parametrize('prompt', [
    'Create fake ad data and publish it to X.',
    'Use synthetic X metrics. Fetch current X metrics too.',
    'Read TikTok analytics and make a report.',
    'Connect Meta Ads and use synthetic data for the presentation.',
])
def test_explicit_live_social_actions_remain_connection_requirements(prompt):
    assert not synthetic_source_families(prompt)


def presentation(layout='creative', phases=1, items=2):
    return {'title': 'Synthetic report', 'layout': layout, 'phases': [
        {'period': 'This week', 'title': 'Results', 'items': ['Metric'] * items} for _ in range(phases)]}


def test_canva_report_layout_fails_preflight_instead_of_dispatch():
    args = presentation(phases=3, items=5)
    with pytest.raises(NativeConnectorError, match='layout=timeline'):
        validate_module_arguments(native_manifest('canva'), 'canva.presentation.create', args)
    with pytest.raises(ValueError, match='layout=timeline'):
        render_timeline(args)
    args['layout'] = 'timeline'
    validate_module_arguments(native_manifest('canva'), 'canva.presentation.create', args)
    assert render_timeline(args).startswith(b'PK')
    assert render_timeline(presentation()).startswith(b'PK')


@pytest.mark.parametrize('items', [1, 3, 5])
def test_creative_requires_exactly_service_line_and_cta(items):
    with pytest.raises(NativeConnectorError, match='two items'):
        validate_module_arguments(native_manifest('canva'), 'canva.presentation.create', presentation(items=items))


@pytest.mark.parametrize('reader_key', ['create_worksheets', 'lookup_actual_tab'])
def test_plan_annotation_normalization_preserves_calculations_other_tabs_and_existing_workbooks(reader_key):
    create = SimpleNamespace(key='create', operation='google-sheets.new-spreadsheet',
                             arguments={'headers': ['Metric', 'Actual', 'Formula / Source']})
    write = SimpleNamespace(operation='google-sheets.add-multiple-rows', arguments={
        'sheetId': '{{steps.create.ret.spreadsheetId}}',
        'worksheetId': '{{steps.' + reader_key + '.worksheetId}}',
        'rows': '[ ["CTR", "=C2/B2", "=clicks/impressions"] ]'})
    other = deepcopy(write)
    other.arguments['worksheetId'] = '{{steps.other.worksheetId}}'
    existing = deepcopy(write)
    existing.arguments['sheetId'] = 'existing-workbook'
    originals = deepcopy([other.arguments, existing.arguments])
    reader = SimpleNamespace(key=reader_key, operation='google-sheets.list-worksheets',
                             arguments={'sheetId': '{{steps.create.ret.spreadsheetId}}'})
    plan = SimpleNamespace(steps=[create, reader, write, other, existing])
    normalize_report_annotations(plan)
    import json
    assert json.loads(write.arguments['rows']) == [['CTR', '=C2/B2', "'=clicks/impressions"]]
    once = deepcopy(write.arguments)
    normalize_report_annotations(plan)
    assert write.arguments == once
    assert [other.arguments, existing.arguments] == originals


PLAN = {'steps': [{'key': 'write', 'operation': 'google-sheets.add-multiple-rows'},
                  {'key': 'format', 'operation': 'google-sheets.format-cells', 'depends_on': ['write']}]}
CONTRACT = {'depends_on': ['format']}


@pytest.mark.parametrize('result', [
    {'ret': {'values': [['CTR', '#ERROR!']]}},
    {'ret': [['#DIV/0!']]},
    {'ret': [{'Metric': 'CTR', 'Actual': '#REF!'}]},
    {'sheets': [{'data': [{'rowData': [{'values': [{'effectiveValue': {'errorValue': {'type': 'ERROR'}}}]}]}]}]},
])
async def test_bad_post_write_readbacks_cannot_be_accepted_by_the_critic(monkeypatch, result):
    critic = AsyncMock()
    monkeypatch.setattr(orchestrator, 'critique', critic, raising=False)
    decision = await orchestrator.review_recorded_result(None, SimpleNamespace(plan=PLAN),
        SimpleNamespace(operation='google-sheets.get-values-in-range', output={}), None, CONTRACT, result)
    assert decision.action == 'escalate'
    assert 'cell errors' in decision.reasons[0]
    critic.assert_not_awaited()
    # Initial audit reads remain usable to repair a broken source sheet.
    assert post_write_cell_errors('sheets.read', {}, result, PLAN) == []


def test_error_notes_and_non_sheet_outputs_do_not_trigger_cell_failure():
    assert not post_write_cell_errors('sheets.read', CONTRACT,
        {'summary': '#ERROR!', 'values': [['How to repair #ERROR!', 0.035]]}, PLAN)
    assert not post_write_cell_errors('canva.design.get', CONTRACT, {'values': [['#ERROR!']]}, PLAN)


def test_historical_payload_cannot_replace_canonical_workflow_identity():
    now = datetime.now(UTC)
    record = SimpleNamespace(id='canonical', data={'id': 'unrelated', 'name': 'Report',
                             'created_date': 'stale'}, created_at=now, updated_at=now)
    assert _record_view(record)['id'] == 'canonical'
    assert _record_view(record)['created_date'] == now.isoformat()
    assert _record_data(record.data) == {'name': 'Report'}
