"""Unit tests for receipt barcode encoding (run: python -m pytest local_print_agent/test_barcode.py)."""
import importlib.util
from pathlib import Path

_MODULE_PATH = Path(__file__).resolve().parent / "print_agent.py"
_spec = importlib.util.spec_from_file_location("print_agent", _MODULE_PATH)
print_agent = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(print_agent)


def test_normalize_wager_id_zero_pads():
    assert print_agent.normalize_receipt_transaction_id("123") == "000123"
    assert print_agent.normalize_receipt_transaction_id(123) == "000123"
    assert print_agent.normalize_receipt_transaction_id("000123") == "000123"


def test_normalize_remit_id_zero_pads():
    assert print_agent.normalize_receipt_transaction_id("R123") == "R000123"
    assert print_agent.normalize_receipt_transaction_id("r000123") == "R000123"


def test_barcode_payload_uses_code_set_b_and_matches_normalized_id():
    for raw, expected in [
        ("123", "000123"),
        ("000123", "000123"),
        ("R123", "R000123"),
        ("SABC123DEF", "SABC123DEF"),
    ]:
        payload = print_agent.escpos_barcode_payload(raw)
        assert payload == ("{B" + expected).encode("ascii"), raw


def test_barcode_payload_never_uses_code_set_c():
    payload = print_agent.escpos_barcode_payload("000123")
    assert payload.startswith(b"{B")
    assert not payload.startswith(b"{C")
