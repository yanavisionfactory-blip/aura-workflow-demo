import base64

from app.orchestrator import _planning_prompt_with_documents
from app.schemas import RunCreate


def data_url(value: str, media_type: str = "text/plain") -> str:
    encoded = base64.b64encode(value.encode()).decode()
    return f"data:{media_type};base64,{encoded}"


def test_attached_text_is_available_to_planning_without_data_url_leakage():
    url = data_url("Revenue target: 42")
    prompt = _planning_prompt_with_documents(
        "Build the report",
        {"documents": [{"name": "target.txt", "file_url": url, "size": 18}]},
    )

    assert "Revenue target: 42" in prompt
    assert "target.txt" in prompt
    assert url not in prompt


def test_run_create_rejects_non_aura_document_references():
    try:
        RunCreate(
            prompt="Build the report",
            inputs={"documents": [{"name": "secret.txt", "file_url": "https://evil.test"}]},
        )
    except ValueError as error:
        assert "AURA upload reference" in str(error)
    else:
        raise AssertionError("external attachment URL should be rejected")
