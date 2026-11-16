import pytest

from app.native_connectors import native_manifest
from app.request_contracts import requested_effects, requested_external_operations


def effects(prompt):
    slugs = ("google", "slack", "jira")
    manifests = {slug: native_manifest(slug) for slug in slugs}
    inventory = [{"slug": slug, "name": slug, "allowed_operations": [
        m["name"] for m in manifests[slug]["capabilities"]]} for slug in slugs]
    return {item["effect"] for item in requested_effects(prompt, inventory, manifests)}


@pytest.mark.parametrize("prompt", [
    "Do not access or modify any external app, send messages, create calendar events, share anything or schedule anything.",
    "Do not access external apps, send email via Gmail or create events in Google Calendar.",
    "Never send a Slack message, create a Jira issue or create a Google Doc.",
    "Prepare a report without changing files, creating events or send email via Gmail.",
    "Do not call calendar.create or call docs.create.",
    "Don't create an event in Google Calendar or create a Google Doc.",
    "Don’t create an event in Google Calendar or create a Google Doc.",
])
def test_prohibition_applies_to_every_coordinated_action(prompt):
    assert effects(prompt) == set()
    assert requested_external_operations(prompt) == set()


@pytest.mark.parametrize("prompt", [
    "Do not modify files, but create a meeting in Google Calendar.",
    "Do not modify files. Create a meeting in Google Calendar.",
    "Do not modify files; create a meeting in Google Calendar.",
    "Do not modify files, instead create a meeting in Google Calendar.",
    "Create a meeting in Google Calendar without modifying files.",
])
def test_separate_affirmative_action_remains_required(prompt):
    assert effects(prompt) == {"calendar create"}


def test_unrelated_negative_following_required_action_preserves_it():
    assert effects("Create a Google Doc, but do not send email or create calendar events.") == {"docs create"}
