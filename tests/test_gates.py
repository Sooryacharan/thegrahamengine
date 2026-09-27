import json

from engine.triage.gates import (
    GATE1_MECHANISM,
    GATE2_NON_CONSENSUS,
    GATE3_REUSABLE_LENS,
    MALFORMED,
    evaluate_gates,
    gate1_mechanism,
    gate2_non_consensus,
    gate3_reusable_lens,
    parse_llm_response,
)


def make_response(g1=True, g2=True, g3=True, confidence=0.8, **overrides):
    payload = {
        "gate1_pass": g1,
        "gate2_pass": g2,
        "gate3_pass": g3,
        "reasoning": "some reasoning",
        "second_order_read": "some second-order read",
        "suggested_falsifier": "if X has not happened by 2026-12-31, thesis is wrong",
        "confidence": confidence,
    }
    payload.update(overrides)
    return json.dumps(payload)


# --- overall pass/fail cases -----------------------------------------------

def test_all_gates_pass():
    result = evaluate_gates(make_response(True, True, True))
    assert result.passed is True
    assert result.malformed is False
    assert result.failing_gate is None
    assert result.confidence == 0.8


def test_fails_gate1_first():
    result = evaluate_gates(make_response(False, True, True))
    assert result.passed is False
    assert result.failing_gate == GATE1_MECHANISM


def test_fails_gate2():
    result = evaluate_gates(make_response(True, False, True))
    assert result.passed is False
    assert result.failing_gate == GATE2_NON_CONSENSUS


def test_fails_gate3():
    result = evaluate_gates(make_response(True, True, False))
    assert result.passed is False
    assert result.failing_gate == GATE3_REUSABLE_LENS


def test_gate1_failure_takes_priority_over_later_gates():
    # all three gates fail — gate1 should be reported, not gate2 or gate3
    result = evaluate_gates(make_response(False, False, False))
    assert result.failing_gate == GATE1_MECHANISM


# --- malformed LLM output cases --------------------------------------------

def test_malformed_not_json():
    result = evaluate_gates("this is not json at all")
    assert result.malformed is True
    assert result.passed is False
    assert result.failing_gate == MALFORMED


def test_malformed_empty_string():
    result = evaluate_gates("")
    assert result.malformed is True
    assert result.failing_gate == MALFORMED


def test_malformed_json_but_not_an_object():
    result = evaluate_gates(json.dumps([1, 2, 3]))
    assert result.malformed is True


def test_malformed_missing_required_key():
    payload = json.loads(make_response())
    del payload["suggested_falsifier"]
    result = evaluate_gates(json.dumps(payload))
    assert result.malformed is True
    assert result.failing_gate == MALFORMED


def test_malformed_gate_field_wrong_type():
    payload = json.loads(make_response())
    payload["gate1_pass"] = "yes"  # string instead of bool
    result = evaluate_gates(json.dumps(payload))
    assert result.malformed is True


def test_malformed_confidence_out_of_range():
    result = evaluate_gates(make_response(confidence=1.5))
    assert result.malformed is True


def test_malformed_confidence_wrong_type():
    result = evaluate_gates(make_response(confidence="high"))
    assert result.malformed is True


def test_malformed_confidence_bool_rejected():
    # bool is a subclass of int in Python — must not silently pass as a number
    result = evaluate_gates(make_response(confidence=True))
    assert result.malformed is True


def test_malformed_reasoning_wrong_type():
    payload = json.loads(make_response())
    payload["reasoning"] = 12345
    result = evaluate_gates(json.dumps(payload))
    assert result.malformed is True


def test_evaluate_gates_never_raises_on_garbage_input():
    garbage_inputs = ["", "{", "null", "true", "42", "[]", "{}", "\x00\x01", "�", "{'single': 'quotes'}"]
    for garbage in garbage_inputs:
        result = evaluate_gates(garbage)
        assert result.passed is False
        assert result.malformed is True


# --- individual gate predicates --------------------------------------------

def test_gate_predicates_read_correct_fields():
    parsed = parse_llm_response(make_response(True, False, True))
    assert parsed is not None
    assert gate1_mechanism(parsed) is True
    assert gate2_non_consensus(parsed) is False
    assert gate3_reusable_lens(parsed) is True


def test_parse_llm_response_returns_none_for_malformed():
    assert parse_llm_response("not json") is None
    assert parse_llm_response(json.dumps({"gate1_pass": True})) is None
