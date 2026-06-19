"""Tests pour core/utils.py — sans MikroTik."""

import sys
sys.path.insert(0, ".")

from core.utils import now_iso, parse_bytes, validate_mac, parse_routeros_output


class TestNowIso:
    def test_returns_string(self):
        result = now_iso()
        assert isinstance(result, str)
        assert "T" in result  # ISO format contains T

    def test_ends_with_z_or_offset(self):
        result = now_iso()
        assert "+" in result or result.endswith("Z") or result.endswith("00:00")


class TestParseBytes:
    def test_none_returns_default(self):
        assert parse_bytes(None) == 0
        assert parse_bytes(None, default=100) == 100

    def test_int_passthrough(self):
        assert parse_bytes(1024) == 1024
        assert parse_bytes(0) == 0

    def test_bytes_no_suffix(self):
        assert parse_bytes("500") == 500
        assert parse_bytes("0") == 0

    def test_kibibytes(self):
        assert parse_bytes("1.0 KiB") == 1024
        assert parse_bytes("2.5 KiB") == 2560

    def test_mebibytes(self):
        assert parse_bytes("1.0 MiB") == 1048576
        assert parse_bytes("10.0 MiB") == 10485760

    def test_gibibytes(self):
        assert parse_bytes("1.0 GiB") == 1073741824

    def test_case_insensitive(self):
        assert parse_bytes("1 MIB") == 1048576
        assert parse_bytes("1 kib") == 1024
        assert parse_bytes("1 MiB") == 1048576

    def test_empty_string(self):
        assert parse_bytes("") == 0

    def test_invalid_string(self):
        assert parse_bytes("not_a_number") == 0


class TestValidateMac:
    def test_valid_colon_format(self):
        assert validate_mac("00:11:22:33:44:55") is True
        assert validate_mac("AA:BB:CC:DD:EE:FF") is True
        assert validate_mac("aa:bb:cc:dd:ee:ff") is True

    def test_valid_hyphen_format(self):
        assert validate_mac("00-11-22-33-44-55") is True
        assert validate_mac("AA-BB-CC-DD-EE-FF") is True

    def test_invalid_macs(self):
        assert validate_mac("") is False
        assert validate_mac("invalid") is False
        assert validate_mac("00:11:22:33:44") is False       # trop court
        assert validate_mac("00:11:22:33:44:55:66") is False  # trop long
        assert validate_mac("00:11:22:33:44:GG") is False     # GG invalide
        assert validate_mac("0:11:22:33:44:55") is False      # 0 au lieu de 00


class TestParseRouterosOutput:
    def test_empty_output(self):
        assert parse_routeros_output("") == []

    def test_single_record(self):
        output = """name: admin
            mac-address: 00:11:22:33:44:55
            uptime: 1d2h3m"""
        result = parse_routeros_output(output)
        assert len(result) == 1
        assert result[0]["name"] == "admin"
        assert result[0]["mac_address"] == "00:11:22:33:44:55"  # tiret remplacé

    def test_multiple_records(self):
        output = """name: user1
            bytes: 1024

            name: user2
            bytes: 2048"""
        result = parse_routeros_output(output)
        assert len(result) == 2
        assert result[0]["name"] == "user1"
        assert result[1]["name"] == "user2"

    def test_empty_value_skipped(self):
        output = """name: test
            empty_val:"""
        result = parse_routeros_output(output)
        assert len(result) == 1
        assert "empty_val" not in result[0]

    def test_line_without_colon_skipped(self):
        output = """name: test
            just some text without colon"""
        result = parse_routeros_output(output)
        assert len(result) == 1
        assert result[0]["name"] == "test"
