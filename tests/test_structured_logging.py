import json

from app.logging import log_event


def test_log_event_serializes_metadata():
    payload = log_event(
        event_id="evt-123",
        action_name="system_status",
        duration_ms=42.5,
        failure_reason=None,
        platform="Darwin",
        model_used="models/gemini-3.1-flash-live-preview",
    )

    data = json.loads(payload)
    assert data["event_id"] == "evt-123"
    assert data["action_name"] == "system_status"
    assert data["duration_ms"] == 42.5
    assert data["platform"] == "Darwin"
    assert data["model_used"] == "models/gemini-3.1-flash-live-preview"
    assert data["failure_reason"] is None
