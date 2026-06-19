"""Tests pour core/validator.py — sans MikroTik."""
import sys
sys.path.insert(0, ".")

from core.validator import validate_params, ValidationError


# Le validateur attend action_def = {"params": [liste de definitions]}
SAMPLE_ACTION = {
    "params": [
        {"name": "username", "required": True, "type": "string", "max_length": 50},
        {"name": "count",    "required": False, "type": "int", "min": 0, "max": 100},
        {"name": "mac",      "required": False, "type": "string",
         "pattern": r"^([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}$"},
        {"name": "enabled",  "required": False, "type": "bool"},
        {"name": "ttl",      "required": False, "type": "string",
         "pattern": r"^\d+[smhd]$"},
    ]
}


class TestValidateParams:
    def test_valid_required_params(self):
        result = validate_params({"username": "test-user"}, SAMPLE_ACTION)
        assert result["username"] == "test-user"

    def test_missing_required_raises(self):
        try:
            validate_params({}, SAMPLE_ACTION)
            assert False, "Should have raised ValidationError"
        except ValidationError as e:
            assert "required" in str(e).lower() or "username" in str(e)

    def test_max_length(self):
        try:
            validate_params({"username": "a" * 100}, SAMPLE_ACTION)
            assert False, "Should have raised"
        except ValidationError:
            pass

    def test_integer_validation(self):
        result = validate_params({"username": "test", "count": 42}, SAMPLE_ACTION)
        assert result["count"] == 42

    def test_integer_min(self):
        try:
            validate_params({"username": "test", "count": -5}, SAMPLE_ACTION)
            assert False, "Should have raised"
        except ValidationError:
            pass

    def test_integer_max(self):
        try:
            validate_params({"username": "test", "count": 999}, SAMPLE_ACTION)
            assert False, "Should have raised"
        except ValidationError:
            pass

    def test_invalid_type_raises(self):
        try:
            validate_params({"username": "test", "count": "not_a_number"}, SAMPLE_ACTION)
            assert False, "Should have raised"
        except ValidationError:
            pass

    def test_pattern_matching(self):
        result = validate_params({
            "username": "test", "mac": "AA:BB:CC:DD:EE:FF"
        }, SAMPLE_ACTION)
        assert result["mac"] == "AA:BB:CC:DD:EE:FF"

    def test_pattern_mismatch_raises(self):
        try:
            validate_params({"username": "test", "mac": "invalid_mac"}, SAMPLE_ACTION)
            assert False, "Should have raised"
        except ValidationError:
            pass

    def test_boolean_validation(self):
        result = validate_params({"username": "test", "enabled": True}, SAMPLE_ACTION)
        assert result["enabled"] is True

        result = validate_params({"username": "test", "enabled": False}, SAMPLE_ACTION)
        assert result["enabled"] is False

    def test_optional_params_not_required(self):
        result = validate_params({"username": "test"}, SAMPLE_ACTION)
        assert "count" not in result

    def test_unknown_params_are_ignored(self):
        result = validate_params({
            "username": "test", "extra_param": "should_be_ignored"
        }, SAMPLE_ACTION)
        assert "extra_param" not in result

    def test_default_values(self):
        action_with_defaults = {
            "params": [
                {"name": "username", "required": True, "type": "string"},
                {"name": "timeout", "type": "int", "default": 30},
            ]
        }
        result = validate_params({"username": "test"}, action_with_defaults)
        assert result["timeout"] == 30
        assert result["username"] == "test"

    def test_ttl_pattern(self):
        result = validate_params({"username": "test", "ttl": "30m"}, SAMPLE_ACTION)
        assert result["ttl"] == "30m"
        result = validate_params({"username": "test", "ttl": "2h"}, SAMPLE_ACTION)
        assert result["ttl"] == "2h"

    def test_invalid_ttl_pattern_raises(self):
        try:
            validate_params({"username": "test", "ttl": "invalid"}, SAMPLE_ACTION)
            assert False, "Should have raised for invalid format"
        except ValidationError:
            pass
