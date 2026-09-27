import json

from engine.build.bridge import evaluate_bridge, parse_llm_response


def make_response(**overrides):
    payload = {
        "observable": "Copper inventories at LME warehouses fell 40% over six weeks.",
        "mechanism": "Falling exchange stockpiles tighten the deliverable float against open contracts.",
        "assumption": "Reported warehouse levels reflect actual physical availability, not relocation to unreported storage.",
        "consequence": "Near-term futures curve backwardation deepens, squeezing short positions into expiry.",
        "falsifier": "If LME copper stocks have not fallen further by 2026-12-31, thesis is wrong.",
    }
    payload.update(overrides)
    return json.dumps(payload)


def test_well_formed_response_is_ok():
    result = evaluate_bridge(make_response())
    assert result.ok is True
    assert result.error is None
    assert result.mechanism.startswith("Falling exchange stockpiles")


def test_malformed_not_json():
    result = evaluate_bridge("this is not json at all")
    assert result.ok is False
    assert result.error is not None


def test_malformed_json_but_not_an_object():
    result = evaluate_bridge(json.dumps([1, 2, 3]))
    assert result.ok is False


def test_malformed_missing_required_key():
    payload = json.loads(make_response())
    del payload["falsifier"]
    result = evaluate_bridge(json.dumps(payload))
    assert result.ok is False


def test_malformed_blank_field_rejected():
    result = evaluate_bridge(make_response(falsifier="   "))
    assert result.ok is False


def test_malformed_field_wrong_type():
    payload = json.loads(make_response())
    payload["mechanism"] = 12345
    result = evaluate_bridge(json.dumps(payload))
    assert result.ok is False


def test_evaluate_bridge_never_raises_on_garbage_input():
    garbage_inputs = ["", "{", "null", "true", "42", "[]", "{}", "\x00\x01", "�", "{'single': 'quotes'}"]
    for garbage in garbage_inputs:
        result = evaluate_bridge(garbage)
        assert result.ok is False


def test_parse_llm_response_returns_none_for_malformed():
    assert parse_llm_response("not json") is None
    assert parse_llm_response(json.dumps({"observable": "x"})) is None
