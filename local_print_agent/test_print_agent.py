import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("print_agent.py")
SPEC = importlib.util.spec_from_file_location("print_agent_for_test", MODULE_PATH)
assert SPEC and SPEC.loader
print_agent = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(print_agent)


def test_transaction_receipt_copies_for_teller():
    assert print_agent.transaction_receipt_copies({}) == (
        "TELLERS COPY",
        "ADMIN COPY",
    )


def test_transaction_receipt_copies_for_admin_bank():
    assert print_agent.transaction_receipt_copies({"receipt_scope": "admin_bank"}) == (
        "ADMIN COPY",
        "BANK COPY",
    )


def test_money_shows_whole_pesos_without_rounding():
    assert print_agent.money("165.50") == "165"
    assert print_agent.money(200.99) == "200"
    assert print_agent.money(1000) == "1,000"
    assert print_agent.money("1,250.75") == "1,250"


def test_escpos_receipt_centers_event_then_restores_configured_alignment():
    payload = print_agent.escpos_receipt(
        {
            "receipt_type": "wager",
            "event_name": "Sunday Derby",
            "amount": "100.00",
        },
        text_align="left",
    )

    event = payload.index(b"Sunday Derby")
    title = payload.index(b"BET RECEIPT")
    assert b"\x1bE\x01\x1ba\x01Sunday Derby\n" in payload
    assert payload.rfind(b"\x1ba\x00", event, title) != -1
    assert b"Amount: 100\n" in payload


def test_escpos_remit_receipt_centers_event_and_uses_whole_amounts():
    payload = print_agent.escpos_remit_receipt(
        {
            "transaction_type": "REMIT",
            "event_name": "Sunday Derby",
            "amount": "1,250.75",
            "balance": "2,000.00",
        }
    )

    first_event = payload.index(b"Event    : Sunday Derby")
    first_amount = payload.index(b"Amount   : 1,250")
    assert payload.rfind(b"\x1ba\x01", 0, first_event) != -1
    assert payload.rfind(b"\x1ba\x00", first_event, first_amount) != -1
    assert b"Balance  : 2,000\n" in payload


def test_escpos_remit_receipt_contains_both_copy_labels():
    payload = print_agent.escpos_remit_receipt(
        {
            "transaction_type": "REMIT",
            "transaction_id": "R123",
            "amount": 100,
            "balance": 500,
            "cashier": "Teller One",
        }
    )

    assert payload.count(b"TELLERS COPY") == 1
    assert payload.count(b"ADMIN COPY") == 1
