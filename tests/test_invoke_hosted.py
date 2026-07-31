from evaluations.invoke_hosted import extract_output_text, response_diagnostic


def test_extract_output_text_returns_response_parts() -> None:
    payload = {
        "output": [
            {"type": "message", "content": [{"type": "output_text", "text": "verified"}]},
            {"type": "tool_call", "content": None},
        ]
    }
    assert extract_output_text(payload) == ["verified"]


def test_extract_output_text_rejects_empty_or_missing_output() -> None:
    assert extract_output_text({}) == []
    assert extract_output_text({"output": []}) == []


def test_response_diagnostic_exposes_only_failure_metadata() -> None:
    diagnostic = response_diagnostic(
        {
            "status": "failed",
            "error": {"code": "bad_request"},
            "incomplete_details": None,
            "output": [{"type": "message", "sensitive": "not included"}],
        }
    )
    assert diagnostic == {
        "status": "failed",
        "error": {"code": "bad_request"},
        "incomplete_details": None,
        "output_types": ["message"],
    }
