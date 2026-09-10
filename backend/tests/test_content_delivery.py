import base64
from copy import deepcopy
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock
from email.parser import BytesParser
from email import policy
import pytest
from pptx import Presentation
from app.presentation_content import render_timeline
from app import file_delivery
from app.providers import ProviderExecutor
from app.outcome_checks import build_outcome_check, evaluate_outcome_check

PDF = b'%PDF-1.7\nroadmap fixture\n%%EOF'
URL = 'https://export-download.canva.com/fixture.pdf'


def test_populated_timeline_has_one_slide_and_all_approved_text():
    a = {'title': '90-day roadmap', 'subtitle': 'Product development', 'phases': [
        {'period': 'Days 1–30', 'title': 'Build', 'items': ['Planner and executor', 'Durable execution']},
        {'period': 'Days 31–60', 'title': 'Verify', 'items': ['Connector contracts']},
        {'period': 'Days 61–90', 'title': 'Release', 'items': ['Performance evaluation']}]}
    deck = Presentation(BytesIO(render_timeline(a)))
    assert len(deck.slides) == 1
    texts = [shape.text for shape in deck.slides[0].shapes if shape.has_text_frame]
    assert a['title'] in texts and a['subtitle'] in texts
    for phase in a['phases']:
        assert phase['title'] in texts and phase['period'] in texts
        assert all(item in texts for item in phase['items'])


@pytest.mark.parametrize('url', ['http://export-download.canva.com/x', 'https://canva.com.evil.test/x',
    'https://127.0.0.1/a', 'https://export-download.canva.com@evil.test/x',
    'https://export-download.canva.com:444/x', 'file:///etc/passwd'])
def test_download_rejects_untrusted_destinations(url):
    with pytest.raises(ValueError):
        file_delivery.allowed_download_url(url)


async def test_pdf_must_come_from_this_runs_verified_export(monkeypatch):
    download = AsyncMock(return_value=PDF)
    monkeypatch.setattr(file_delivery, 'download_pdf', download)
    a = {'to': 'me', 'body': 'Attached', 'attachments': [{'filename': 'roadmap.pdf', 'url': URL}]}
    with pytest.raises(ValueError):
        await file_delivery.prepare_attachments(a, set())
    download.assert_not_awaited()
    ready = await file_delivery.prepare_attachments(a, {URL})
    assert ready['attachments'][0]['sha256'] == file_delivery.fingerprint(PDF)['sha256']
    assert 'sha256' not in a['attachments'][0]


async def test_gmail_sends_real_pdf_and_rejects_changed_file_before_post(monkeypatch):
    monkeypatch.setattr(file_delivery, 'download_pdf', AsyncMock(return_value=PDF))
    executor = ProviderExecutor({'access_token': 'test'})
    executor._request = AsyncMock(return_value={'id': 'sent-id'})
    a = {'to': 'owner@example.test', 'subject': 'Roadmap', 'body': 'Attached',
         'attachments': [{'filename': 'roadmap.pdf', 'url': URL, **file_delivery.fingerprint(PDF)}]}
    receipt = await executor._gmail_send(a)
    sent = executor._request.call_args.kwargs['json']['raw']
    message = BytesParser(policy=policy.default).parsebytes(base64.urlsafe_b64decode(sent+'='*(-len(sent)%4)))
    assert list(message.iter_attachments())[0].get_payload(decode=True) == PDF
    executor._request.reset_mock()
    monkeypatch.setattr(file_delivery, 'download_pdf', AsyncMock(return_value=PDF+b'changed'))
    with pytest.raises(ValueError):
        await executor._gmail_send(a)
    executor._request.assert_not_awaited()
    observed = {'id': 'sent-id', 'labelIds': ['SENT'], 'payload': {'headers': [
        {'name': 'To', 'value': a['to']}, {'name': 'Subject', 'value': a['subject']}], 'parts': [
            {'mimeType': 'text/plain', 'body': {'data': base64.urlsafe_b64encode(b'Attached').decode()}},
            {'mimeType': 'application/pdf', 'filename': 'roadmap.pdf', 'body': {'data': base64.urlsafe_b64encode(PDF).decode()}}]}}
    check = build_outcome_check('gmail.send', a, receipt)
    assert evaluate_outcome_check(check, observed)['status'] == 'verified'
    observed['payload']['parts'].pop()
    assert evaluate_outcome_check(check, observed)['status'] == 'failed'


async def test_verified_async_job_result_reaches_downstream_without_another_write(monkeypatch):
    from app import orchestrator
    result = {'job': {'id': 'job-1', 'status': 'in_progress'}}
    terminal = {'job': {'id': 'job-1', 'status': 'success', 'urls': [URL]}}
    step = SimpleNamespace(operation='canva.export.create', output={'provider_result': deepcopy(result)})
    monkeypatch.setattr(orchestrator, 'check_provider_outcome', AsyncMock(return_value={'status': 'verified', 'observed': terminal}))
    session = SimpleNamespace(commit=AsyncMock())
    decision = await orchestrator.review_recorded_result(session, None, step, None, {}, result)
    assert decision.action == 'accept'
    assert result['job']['urls'] == [URL] and step.output['provider_result']['job']['status'] == 'success'


def test_canva_import_polls_saved_job_and_checks_design_identity():
    check = build_outcome_check('canva.presentation.create', {'title': 'Roadmap'}, {'job': {'id': 'job-1'}})
    assert evaluate_outcome_check(check, {'job': {'id': 'job-1', 'status': 'in_progress'}})['status'] == 'pending'
    result = {'job': {'id': 'job-1', 'status': 'success', 'result': {'designs': [{'id': 'design-1', 'title': 'Roadmap'}]}}}
    assert evaluate_outcome_check(check, result)['status'] == 'verified'
    result['job']['id'] = 'wrong-job'
    assert evaluate_outcome_check(check, result)['status'] == 'failed'


async def test_download_redirect_cannot_escape_canva_and_html_is_not_a_pdf(monkeypatch):
    import httpx
    real_client = httpx.AsyncClient
    calls = []
    def redirect(request):
        calls.append(request)
        return httpx.Response(302, headers={'location': 'http://127.0.0.1/private'})
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: real_client(**kw, transport=httpx.MockTransport(redirect)))
    with pytest.raises(ValueError):
        await file_delivery.download_pdf(URL)
    assert len(calls) == 1 and 'authorization' not in calls[0].headers
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: real_client(**kw, transport=httpx.MockTransport(lambda req: httpx.Response(200, content=b'<html>expired link</html>'))))
    with pytest.raises(ValueError):
        await file_delivery.download_pdf(URL)


async def test_canva_import_posts_real_populated_presentation_once(monkeypatch):
    import httpx, json
    calls = []
    def handler(request):
        calls.append(request)
        assert request.url.path == '/rest/v1/imports'
        assert request.headers['content-type'] == 'application/octet-stream'
        metadata = json.loads(request.headers['import-metadata'])
        assert base64.b64decode(metadata['title_base64']) == b'Roadmap'
        assert len(Presentation(BytesIO(request.content)).slides) == 1
        return httpx.Response(200, json={'job': {'id': 'import-1', 'status': 'in_progress'}})
    real_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: real_client(**kw, transport=httpx.MockTransport(handler)))
    result = await ProviderExecutor({'access_token': 'private'})._canva_presentation_create(
        {'title': 'Roadmap', 'phases': [{'period': 'Day 1', 'title': 'Build', 'items': ['First milestone']}]})
    assert result['job']['id'] == 'import-1' and len(calls) == 1


async def test_gmail_receipt_reads_attachment_bytes_only_when_requested(monkeypatch):
    executor = ProviderExecutor({'access_token': 'private'})
    payload = {'id': 'm1', 'payload': {'parts': [{'filename': 'roadmap.pdf', 'body': {'attachmentId': 'a1', 'size': len(PDF)}}]}}
    executor._request = AsyncMock(side_effect=[deepcopy(payload), {'data': base64.urlsafe_b64encode(PDF).decode(), 'size': len(PDF)}])
    result = await executor._gmail_get({'message_id': 'm1', 'verify_attachments': True})
    assert file_delivery.gmail_attachment_fingerprints(result['payload'])[0]['sha256'] == file_delivery.fingerprint(PDF)['sha256']
    assert executor._request.call_args.args[1].endswith('/m1/attachments/a1')
