"""Recognize the reviewed, text-only Claude action covered by plan approval.

Pipedream marks anthropic-chat as a write even though version 0.2.2 only calls
Messages with text. Do not generalize this exception to agents, MCP tools, or
future action versions. Keep the connector contract and approval audit intact.
Source: PipedreamHQ/pipedream/components/anthropic/actions/chat/chat.mjs
"""

from .intelligence_backup import ClaudeTextRequest, supports_claude_backup


def is_text_preparation(manifest: dict, step: dict, arguments: dict) -> bool:
    if manifest.get("provider_type") != "pipedream":
        return False
    if not supports_claude_backup(step, arguments):
        return False
    capability = next((item for item in manifest.get("capabilities", [])
                       if item.get("name") == "anthropic.chat"), {})
    transport = capability.get("transport") or {}
    broker = (capability.get("metadata") or {}).get("connector_broker") or {}
    schema = capability.get("input_schema") or {}
    properties = set((schema.get("properties") or {}).keys())
    return bool(
        transport == {"type": "pipedream_action", "action_id": "anthropic-chat",
                      "version": "0.2.2", "auth_prop": "anthropic"}
        and broker.get("backend") == "pipedream"
        and broker.get("provider") == "anthropic"
        and schema.get("type") == "object"
        and schema.get("additionalProperties") is False
        and {"userMessage", "model", "maxTokensToSample"} <= properties <= set(ClaudeTextRequest.model_fields)
    )
