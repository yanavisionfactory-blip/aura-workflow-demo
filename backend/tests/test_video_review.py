import asyncio
import base64
import json
import shutil
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from app import frameio, frameio_screen
from app import video_review as video
from app.agent_runtime import intent_bounded_tool_inventory
from app.config import Settings
from app.native_connectors import native_manifest
from app.operation_contracts import output_errors
from app.providers import ProviderExecutor

ACCOUNT = "11111111-1111-4111-8111-111111111111"
FILE = "22222222-2222-4222-8222-222222222222"


def draft(time=0.5):
    return video.ReviewDraft(summary="The title needs a spelling correction.", limitations=[], findings=[
        video.Finding(timestamp_seconds=time, end_seconds=time, category="spelling", severity="error",
                      issue="Title says 'Welcom'.", correction="Change it to 'Welcome'.",
                      evidence="The supplied title frame shows 'Welcom'.")])


@pytest.fixture
def intelligence(monkeypatch):
    monkeypatch.setattr(video, "get_settings", lambda: Settings(openai_api_key="test-key"))


@pytest.fixture
async def clip(tmp_path):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("FFmpeg runtime is required for real decoder integration")
    path = tmp_path / "test.mp4"
    await video._command("ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=red:s=320x240:r=24:d=2",
                         "-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-c:v", "libx264",
                         "-c:a", "aac", "-shortest", str(path))
    return path.read_bytes()


@pytest.mark.parametrize("value", ["https://example.com/video.mp4", "file:///etc/passwd",
    "data:video/mp4;base64,???", "data:text/plain;base64,SGVsbG8=", "data:video/mp4;base64,"])
def test_upload_requires_real_supported_binary(value):
    with pytest.raises(ValueError):
        video._upload_bytes(value)


def test_upload_bounds_binary_and_accepts_valid_input(monkeypatch):
    assert video._upload_bytes("data:video/mp4;base64,YWJj") == b"abc"
    monkeypatch.setattr(video, "MAX_BYTES", 2)
    with pytest.raises(ValueError, match="50 MB"):
        video._upload_bytes("data:video/mp4;base64,YWJj")


async def test_real_decoder_covers_first_last_frames_and_actual_audio(clip, tmp_path):
    media = await video._extract(clip, tmp_path)
    assert 1.9 <= media["duration"] <= 2.1
    assert media["frames"][0][0] == 0
    assert media["frames"][-1][0] >= 1.9
    assert len(media["frames"]) >= 4
    assert all(path.read_bytes().startswith(b"\xff\xd8") for _, path in media["frames"])
    assert media["audio_chunks"][0][2].read_bytes().startswith(b"RIFF")
    assert media["audio_streams"] == 1


async def test_decoder_preserves_video_offset_relative_to_audio(tmp_path):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("FFmpeg runtime required")
    path = tmp_path / "offset.mp4"
    await video._command("ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
                         "-itsoffset", "1", "-f", "lavfi", "-i", "color=c=red:s=320x240:r=24:d=2",
                         "-c:v", "libx264", "-fps_mode", "vfr", "-c:a", "aac", str(path))
    media = await video._extract(path.read_bytes(), tmp_path)
    assert media["frames"][0][0] == pytest.approx(1.0, abs=0.05)
    assert media["frames"][-1][0] >= 2.9
    assert media["audio_chunks"][0][0] == 0


async def test_models_receive_images_and_real_audio_not_file_metadata(clip, tmp_path, intelligence, monkeypatch):
    media = await video._extract(clip, tmp_path)
    calls = []

    class Client:
        def __init__(self, **kwargs):
            self.responses = SimpleNamespace(parse=self.parse)
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.listen))

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def parse(self, **kwargs):
            calls.append(("vision" if isinstance(kwargs["input"], list) else "merge", kwargs))
            return SimpleNamespace(output_parsed=draft())

        async def listen(self, **kwargs):
            calls.append(("audio", kwargs))
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="0–2s: steady tone, no audible glitches."))])

    monkeypatch.setattr(video, "AsyncOpenAI", Client)
    result = await video._analyze(media, "Review carefully")
    assert result.findings[0].timestamp_seconds == 0.5
    by_kind = dict(calls)
    images = by_kind["vision"]["input"][0]["content"]
    assert sum(part["type"] == "input_image" for part in images) == len(media["frames"])
    assert all(part["image_url"].startswith("data:image/jpeg;base64,") for part in images if part["type"] == "input_image")
    audio = by_kind["audio"]["messages"][1]["content"][1]["input_audio"]
    assert base64.b64decode(audio["data"]).startswith(b"RIFF")
    assert audio["format"] == "wav"
    assert all(call["store"] is False for _, call in calls)
    assert "steady tone" in by_kind["merge"]["input"]


async def test_review_receipt_keeps_timing_hash_and_report_without_binary_or_temp_paths(clip, intelligence, monkeypatch):
    monkeypatch.setattr(video, "_analyze", AsyncMock(return_value=draft()))
    result = await video.review_upload({"file_url": "data:video/mp4;base64," + base64.b64encode(clip).decode(), "filename": "test.mp4"})
    assert result["coverage"]["audio_status"] == "reviewed"
    assert result["media_analyzed"] is True
    assert result["source"]["provider"] == "user_upload"
    assert result["source"]["size_bytes"] == len(clip)
    assert "00:00.500" in result["body"] and "Welcome" in result["body"]
    assert output_errors("intelligence.video.review", result) == []
    assert all(value not in json.dumps(result) for value in ("base64", "test-key", "/tmp/", "playback_url"))
    corrupt = {**result, "media_analyzed": False}
    assert output_errors("intelligence.video.review", corrupt)


async def test_analysis_failure_is_never_a_completed_review(clip, intelligence, monkeypatch):
    monkeypatch.setattr(video, "_analyze", AsyncMock(side_effect=TimeoutError("model timeout")))
    with pytest.raises(TimeoutError):
        await video.review_bytes(clip, "test.mp4", "review", {"provider": "user_upload"})


def test_invalid_or_out_of_bounds_timestamps_fail_instead_of_fabricating_precision():
    with pytest.raises(ValueError):
        video._checked_draft(draft(4), 2)
    invalid = draft(1)
    invalid.findings[0].end_seconds = 0.5
    with pytest.raises(ValueError):
        video._checked_draft(invalid, 2)


async def test_frameio_uses_fresh_exact_version_and_retains_identity_not_signed_url(monkeypatch):
    reader = AsyncMock(return_value={"name": "campaign.mp4", "playback_url": "https://assets.frame.io/video?signature=PRIVATE", "silent_preview": False})
    review = AsyncMock(return_value={"body": "review"})
    monkeypatch.setattr(frameio_screen, "read_media", reader)
    monkeypatch.setattr(video, "_download", AsyncMock(return_value=b"video"))
    monkeypatch.setattr(video, "review_bytes", review)
    result = await frameio.execute({"access_token": "TOKEN"}, "frameio.video.review", {"account_id": ACCOUNT, "file_id": FILE})
    reader.assert_awaited_once_with({"access_token": "TOKEN"}, ACCOUNT, FILE)
    assert result == {"body": "review"}
    source = review.call_args.args[3]
    assert source["asset_id"] == source["version_id"] == FILE
    assert source["account_id"] == ACCOUNT
    assert source["vendor_api_called"] is True
    assert "PRIVATE" not in json.dumps(source) and "TOKEN" not in json.dumps(source)


@pytest.mark.parametrize("media", [{"playback_url": None}, {"playback_url": "https://assets.frame.io/silent", "silent_preview": True}])
async def test_frameio_rejects_missing_or_silent_preview_before_analysis(monkeypatch, media):
    monkeypatch.setattr(frameio_screen, "read_media", AsyncMock(return_value=media))
    downloader = AsyncMock()
    monkeypatch.setattr(video, "_download", downloader)
    with pytest.raises(ValueError, match="complete review rendition"):
        await video.review_frameio({}, {"account_id": ACCOUNT, "file_id": FILE})
    downloader.assert_not_called()


async def test_media_rejects_untrusted_or_private_destinations(monkeypatch):
    for address in ("http://assets.frame.io/x", "https://frame.io.evil.test/x", "https://user:secret@assets.frame.io/x", "https://127.0.0.1/x"):
        with pytest.raises(ValueError):
            await video._public_media_url(address)
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", AsyncMock(return_value=[(2, 1, 6, "", ("127.0.0.1", 443))]))
    with pytest.raises(ValueError, match="not public"):
        await video._public_media_url("https://assets.frame.io/video")


async def test_streaming_download_bounds_bytes_and_revalidates_redirect_without_auth(monkeypatch):
    original = httpx.AsyncClient
    requests = []
    checked = []

    async def validate(url):
        checked.append(url)
        if "evil.test" in url:
            raise ValueError("untrusted redirect")
        return url

    def handle(request):
        requests.append(request)
        assert "authorization" not in request.headers
        return httpx.Response(302, headers={"location": "https://evil.test/steal"})

    monkeypatch.setattr(video, "_public_media_url", validate)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(handle), **kwargs))
    with pytest.raises(ValueError, match="untrusted redirect"):
        await video._download("https://assets.frame.io/video")
    assert len(requests) == 1 and len(checked) == 2
    monkeypatch.setattr(video, "MAX_BYTES", 2)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"abcd")), **kwargs))
    with pytest.raises(ValueError, match="50 MB"):
        await video._download("https://assets.frame.io/video")


async def test_decoder_cancellation_reaps_subprocess(monkeypatch):
    process = SimpleNamespace(returncode=None, kill=lambda: setattr(process, "returncode", -9))

    async def communicate():
        if process.returncode is None:
            await asyncio.sleep(10)
        return b"", b""

    process.communicate = communicate
    monkeypatch.setattr(asyncio, "create_subprocess_exec", AsyncMock(return_value=process))
    monkeypatch.setattr(shutil, "which", lambda _: "/usr/bin/ffmpeg")
    with pytest.raises(TimeoutError):
        await video._command("ffmpeg", timeout=0.01)
    assert process.returncode == -9


async def test_typed_native_operation_routes_to_analysis_and_cannot_use_other_account(monkeypatch):
    upload = AsyncMock(return_value={"body": "review"})
    monkeypatch.setattr(video, "review_upload", upload)
    executor = ProviderExecutor({}, "provider-managed", capability_manifest=native_manifest("aura"))
    await executor.execute("intelligence.video.review", {"file_url": "data:video/mp4;base64,YWJj", "filename": "test.mp4"})
    upload.assert_awaited_once()
    with pytest.raises(ValueError):
        await executor.execute("frameio.video.review", {"account_id": ACCOUNT, "file_id": FILE})


def test_video_intent_exposes_analysis_operation():
    inventory = [{"slug": "aura", "display_name": "AURA Intelligence", "connected": True,
                  "allowed_operations": ["intelligence.video.review"]}]
    assert intent_bounded_tool_inventory("Review this video for errors", inventory) == inventory

