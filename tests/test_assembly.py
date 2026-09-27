import json

from engine.publish.assembly import evaluate_publication, parse_llm_response


def make_response(**overrides):
    payload = {
        "hook": "Copper's quiet warehouse drain is the real story.",
        "context": "LME stocks have fallen sharply while headlines focus on demand.",
        "falsifier_line": "If LME copper stocks haven't fallen further by Dec 31, this is wrong.",
        "payoff_line": "Watch the weekly LME warehouse report.",
        "carousel_slides": ["Slide 1", "Slide 2", "Slide 3"],
        "caption": "Copper's quiet warehouse drain is the real story. #copper #markets",
    }
    payload.update(overrides)
    return json.dumps(payload)


def test_well_formed_response_is_ok():
    result = evaluate_publication(make_response())
    assert result.ok is True
    assert result.error is None
    assert json.loads(result.carousel_json) == ["Slide 1", "Slide 2", "Slide 3"]


def test_malformed_not_json():
    result = evaluate_publication("this is not json at all")
    assert result.ok is False


def test_malformed_json_but_not_an_object():
    result = evaluate_publication(json.dumps([1, 2, 3]))
    assert result.ok is False


def test_malformed_missing_required_key():
    payload = json.loads(make_response())
    del payload["hook"]
    result = evaluate_publication(json.dumps(payload))
    assert result.ok is False


def test_malformed_blank_field_rejected():
    result = evaluate_publication(make_response(hook="   "))
    assert result.ok is False


def test_malformed_carousel_slides_not_a_list():
    result = evaluate_publication(make_response(carousel_slides="not a list"))
    assert result.ok is False


def test_malformed_carousel_slides_empty():
    result = evaluate_publication(make_response(carousel_slides=[]))
    assert result.ok is False


def test_malformed_carousel_slide_wrong_type():
    result = evaluate_publication(make_response(carousel_slides=["ok", 5]))
    assert result.ok is False


def test_malformed_carousel_slide_blank():
    result = evaluate_publication(make_response(carousel_slides=["ok", "   "]))
    assert result.ok is False


def test_evaluate_publication_never_raises_on_garbage_input():
    garbage_inputs = ["", "{", "null", "true", "42", "[]", "{}", "\x00\x01", "�", "{'single': 'quotes'}"]
    for garbage in garbage_inputs:
        result = evaluate_publication(garbage)
        assert result.ok is False


def test_parse_llm_response_returns_none_for_malformed():
    assert parse_llm_response("not json") is None
    assert parse_llm_response(json.dumps({"hook": "x"})) is None
