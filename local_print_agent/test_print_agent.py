import importlib.util
import json
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("print_agent.py")
SPEC = importlib.util.spec_from_file_location("print_agent_for_test", MODULE_PATH)
assert SPEC and SPEC.loader
print_agent = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(print_agent)


def test_load_config_migrates_only_unversioned_left_layout(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    monkeypatch.setattr(print_agent, "CONFIG_PATH", config_path)

    config_path.write_text(json.dumps({"text_align": "left"}), encoding="utf-8")
    assert print_agent.load_config()["text_align"] == "center"

    config_path.write_text(
        json.dumps({"text_align": "left", "receipt_layout_version": 2}),
        encoding="utf-8",
    )
    assert print_agent.load_config()["text_align"] == "left"


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


def test_double_width_amount_is_centered():
    payload = print_agent.escpos_receipt(
        {
            "receipt_type": "wager",
            "side": "MERON",
            "amount": "1000",
        },
        text_align="center",
    )

    # 16 double-width columns. "Amount: 1,000" is 13, so one leading space.
    assert b"\x1d!\x11\x1ba\x00 Amount: 1,000\n" in payload
    assert b"\x1ba\x01" not in payload
    assert b"\x1b$" not in payload


def test_layout_uses_same_normalized_width_for_setup_and_centering():
    payload = print_agent.escpos_receipt(
        {"receipt_type": "wager", "side": "X", "amount": "1"},
        paper_width_dots=100,
    )

    assert b"\x1dW\xc0\x00" in payload
    assert b"\x1d!\x11\x1ba\x00   X\n" in payload


def test_escpos_receipt_centers_event_when_body_is_left():
    payload = print_agent.escpos_receipt(
        {
            "receipt_type": "wager",
            "event_name": "Sunday Derby",
            "side": "MERON",
            "amount": "100.00",
        },
        text_align="left",
    )

    assert b"\x1dL\x00\x00\x1dW" in payload
    assert b"\x1ba\x00\x1bE\x01\x1ba\x00          Sunday Derby\n" in payload
    assert b"\x1dL\x00\x00\x1ba\x00\x1bE\x01\x1ba\x00BET RECEIPT\n" in payload
    assert b"\x1d!\x11\x1ba\x00MERON\n" in payload
    assert b"\x1ba\x01" not in payload
    assert b"\x1b$" not in payload
    assert b"Amount: 100\n" in payload


def test_escpos_receipt_centers_text_and_barcode():
    payload = print_agent.escpos_receipt(
        {
            "receipt_type": "wager",
            "transaction_id": "42",
            "event_name": "Sunday Derby",
            "side": "MERON",
            "amount": "100.00",
            "fightnum": 3,
        },
        text_align="center",
    )

    assert b"\x1dL\x00\x00\x1dW" in payload
    assert b"\x1ba\x00\x1bE\x01\x1ba\x00          Sunday Derby\n" in payload
    assert b"\x1ba\x00\x1bE\x01\x1ba\x00        Fight Number: 3\n" in payload
    assert b"\x1d!\x11\x1ba\x00     MERON\n" in payload
    assert b"\x1d!\x11\x1ba\x00  Amount: 100\n" in payload
    assert b"\x1ba\x01" not in payload
    assert b"\x1b$" not in payload
    assert b"\x1dk\x49" in payload


def test_payout_receipt_shows_amount_won_under_bet():
    payload = print_agent.escpos_receipt(
        {
            "receipt_type": "payout",
            "side": "MERON",
            "odds": "Llamado",
            "amount": "100.00",
            "multiplier": "1.9000",
            "Total_Payout": "190",
            "fightnum": 3,
            "cashier": "teller1",
        }
    )
    text = payload.decode("cp437", errors="replace")
    amount_at = text.index("Amount: 100")
    won_at = text.index("Amount Won: 190")
    odds_at = text.index("Odds: 1.9000")
    assert amount_at < won_at < odds_at


def test_refund_receipt_omits_amount_won():
    payload = print_agent.escpos_receipt(
        {
            "receipt_type": "draw_refund",
            "side": "DRAW",
            "odds": "FULL REFUND",
            "amount": "100.00",
            "multiplier": "1.00",
            "Total_Payout": "100.00",
        }
    )
    assert b"Amount Won:" not in payload
    assert b"Refund Amount:" in payload


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
    assert b"\x1ba\x00\x1bE\x00\x1ba\x00    Event    : Sunday Derby\n" in payload
    assert payload.rfind(b"\x1ba\x00", first_event, first_amount) != -1
    assert b"\x1ba\x00\x1bE\x00\x1ba\x00Amount   : 1,250\n" in payload
    assert b"Balance  : 2,000\n" in payload


def test_escpos_remit_receipt_prints_fight_number_on_both_copies():
    advance = print_agent.escpos_remit_receipt(
        {
            "transaction_type": "REMIT",
            "transaction_id": "R123",
            "amount": 100,
            "fightnum": 7,
        }
    )
    borrow = print_agent.escpos_remit_receipt(
        {
            "receipt_scope": "admin_bank",
            "transaction_type": "BORROW",
            "transaction_id": "B000004",
            "amount": 500,
            "fightnum": 0,
        }
    )

    assert advance.count(b"Fight Number: 7") == 2
    assert borrow.count(b"Fight Number: 0") == 2
    assert borrow.count(b"ADMIN COPY") == 1
    assert borrow.count(b"BANK COPY") == 1


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
