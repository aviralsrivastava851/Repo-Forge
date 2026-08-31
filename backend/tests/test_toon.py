from app.services.toon import dumps, loads, validate, estimate_tokens

def test_toon_roundtrip():
    obj = {
        "failure_class": "stale_context",
        "suspected_step": 7,
        "evidence": ["tool result at step 5 conflicts"],
        "confidence": 0.81
    }
    text = dumps(obj)
    assert validate(text)
    parsed = loads(text)
    assert parsed["failure_class"] == "stale_context"
    assert parsed["suspected_step"] == 7
    assert parsed["evidence"][0] == "tool result at step 5 conflicts"
    assert parsed["confidence"] == 0.81

def test_toon_savings():
    import json
    obj = {"orders": [{"id": 102, "created_at": "2026-08-20"}, {"id": 101, "created_at": "2026-08-21"}]}
    json_text = json.dumps(obj)
    toon_text = dumps(obj)
    jt = estimate_tokens(json_text)
    tt = estimate_tokens(toon_text)
    assert tt <= jt

def test_event_list_storage_roundtrip():
    from app.services.supabase import _prepare, _restore
    events = [{"step": 1, "type": "user_task"}, {"step": 2, "type": "tool_result", "files": ["README.md"]}]
    stored = _prepare({"id": "trace_test", "events": events})
    restored = _restore(stored)
    assert restored["events"] == events
