import json

import pytest

from app.native_connectors import (
    NativeConnectorError,
    normalize_module_arguments,
    normalize_planned_module_arguments,
)
from app.plan_preflight import preflight_plan
from app.schemas import PlanStep, WorkflowPlan


def manifest(operation):
    return {'capabilities': [{'name': operation, 'permission_scope': 'write', 'requires_approval': True,
        'input_schema': {'type': 'object', 'required': ['rows'], 'properties': {'rows': {'type': 'string'}}}}]}


@pytest.mark.parametrize('operation', ['google-sheets.add-multiple-rows', 'google-sheets.update-multiple-rows'])
def test_formula_quotes_are_rejected_before_plan_review(operation):
    invalid = '[["CTR","=IFERROR(C3/C2,"")"]]'
    with pytest.raises(NativeConnectorError, match='Escape quotes inside formula strings'):
        normalize_module_arguments(manifest(operation), operation, {'rows': invalid})
    plan = WorkflowPlan(name='Report', interpretation='Write report', steps=[PlanStep(
        key='write', agent='Sheets', tool_slug='google-sheets', operation=operation,
        arguments={'rows': invalid}, reason='Write saved table', expected_output='Rows', consequential=True)])
    inventory = [{'slug': 'google-sheets', 'connected': True, 'allowed_operations': [operation]}]
    check = preflight_plan(plan, inventory, {'google-sheets': manifest(operation)}, set())
    assert any('valid JSON' in fix for fix in check.fixes)


@pytest.mark.parametrize('encoded', [True, False])
def test_valid_formulas_preserve_empty_string_quotes_and_scalar_values(encoded):
    operation = 'google-sheets.add-multiple-rows'
    rows = [['CTR', '=IFERROR(C3/C2,"")', 0.035, True, None]]
    args = normalize_planned_module_arguments(manifest(operation), operation,
                                      {'rows': json.dumps(rows) if encoded else rows})
    assert json.loads(args['rows']) == rows
    assert normalize_module_arguments(manifest(operation), operation, args) == args


@pytest.mark.parametrize('rows', ['{}', '[]', '["not a row"]', '[[{"formula":"=1"}]]'])
def test_invalid_inner_shapes_are_not_accepted_as_arbitrary_strings(rows):
    operation = 'google-sheets.update-multiple-rows'
    with pytest.raises(NativeConnectorError, match='array of row arrays'):
        normalize_module_arguments(manifest(operation), operation, {'rows': rows})


def test_full_reference_defers_until_resolved_payload_validation():
    operation = 'google-sheets.add-multiple-rows'
    args = {'rows': '{{steps.compose.rows}}'}
    assert normalize_module_arguments(manifest(operation), operation, args) == args
    with pytest.raises(NativeConnectorError, match='valid JSON'):
        normalize_module_arguments(manifest(operation), operation, {'rows': '[["unescaped "quote""]] '})
