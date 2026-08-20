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
