"""Tests for the schema validation check."""

from engine.schema_validator import validate


def test_valid_schema_passes():
    output = {"name": "Alice", "age": 30}
    schema = {
        "type": "object",
        "required": ["name", "age"],
        "properties": {
            "name": {"type": "string"},
            "age": {"type": "integer"},
        },
    }
    result = validate(output, schema)
    assert result.check_type == "schema"
    assert result.score == 1.0
    assert result.passed is True
    assert result.details["errors"] == []


def test_invalid_schema_fails():
    output = {"name": "Alice"}
    schema = {
        "type": "object",
        "required": ["name", "age"],
        "properties": {
            "name": {"type": "string"},
            "age": {"type": "integer"},
        },
    }
    result = validate(output, schema)
    assert result.check_type == "schema"
    assert result.score == 0.0
    assert result.passed is False
    assert len(result.details["errors"]) > 0


def test_no_schema_skips():
    result = validate({"any": "data"}, None)
    assert result.check_type == "schema"
    assert result.score == 1.0
    assert result.passed is True
    assert result.details["skipped"] is True


def test_wrong_type_fails():
    output = "not an object"
    schema = {"type": "object"}
    result = validate(output, schema)
    assert result.score == 0.0
    assert result.passed is False


def test_string_output_parsed_as_json():
    output = '{"name": "Alice", "age": 30}'
    schema = {
        "type": "object",
        "required": ["name"],
        "properties": {"name": {"type": "string"}},
    }
    result = validate(output, schema)
    assert result.score == 1.0
    assert result.passed is True


def test_additional_properties_allowed_by_default():
    output = {"name": "Alice", "extra": "field"}
    schema = {
        "type": "object",
        "required": ["name"],
        "properties": {"name": {"type": "string"}},
    }
    result = validate(output, schema)
    assert result.passed is True
