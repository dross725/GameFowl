from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def read_project_file(relative_path):
    return (PROJECT_ROOT / relative_path).read_text(encoding='utf-8')


def test_display_page_does_not_load_admin_runtime():
    template = read_project_file('SmartWagers/templates/SmartWagers/index.html')
    signals = read_project_file('SmartWagers/static/SmartWagers/signals.js')

    assert 'administrator.js' not in template
    assert 'signals.js' in template
    assert '|| "index"' in signals
    assert 'async function update_trends()' in signals


def test_cash_count_flow_contains_no_cursor_debug_transport():
    view = read_project_file('SmartWagers/views.py')
    template = read_project_file(
        'SmartWagers/templates/SmartWagers/admin_tellers.html'
    )
    combined = view + template

    assert 'debug-752381' not in combined
    assert '127.0.0.1:7881' not in combined
    assert '#region agent log' not in combined


def test_teller_report_honors_printing_contract_and_safe_shared_script():
    report = read_project_file(
        'SmartWagers/templates/SmartWagers/teller_report.html'
    )
    wagers_script = read_project_file(
        'SmartWagers/static/SmartWagers/submit_wagers.js'
    )

    assert 'data.print_required === false || !data.receipt' in report
    assert 'if (!wagerValue || !wagerId) return;' in wagers_script
    assert 'wrong-punch-rank-card' in report
    assert 'Butterfingers Rank' in report


def test_wrong_punch_guard_is_wired_in_bet_entry():
    wagers_script = read_project_file(
        'SmartWagers/static/SmartWagers/submit_wagers.js'
    )
    user_template = read_project_file(
        'SmartWagers/templates/SmartWagers/user.html'
    )
    admin_template = read_project_file(
        'SmartWagers/templates/SmartWagers/administrator.html'
    )
    settings_template = read_project_file(
        'SmartWagers/templates/SmartWagers/admin_settings.html'
    )

    assert 'isWrongPunchAmount' in wagers_script
    assert 'openWrongPunchModal' in wagers_script
    assert 'recordAndShowWrongPunch' in wagers_script
    assert 'isRecordingWrongPunch' in wagers_script
    assert "result.error === \"wrong_punch\"" in wagers_script
    assert "setAmountSource('button')" in wagers_script
    assert "setAmountSource('manual')" in wagers_script
    assert "name='amount_source'" in user_template
    assert "name='amount_source'" in admin_template
    assert 'wrongpunchModal' in user_template
    assert 'wrongpunchModal' in admin_template
    assert 'wrongpunchwinnermodal' in admin_template
    assert 'showWrongPunchWinnerModal' in admin_template
    assert 'wrongpunch-count' in user_template
    assert 'wrongpunch-rank' in user_template
    assert 'DISCARD_TRAILING_3_6' in user_template
    assert 'DISCARD_TRAILING_3_6' in admin_template
    assert 'saveDiscardTrailing36' in settings_template


def test_teller_alert_panel_has_real_collapse_behavior():
    template = read_project_file(
        'SmartWagers/templates/SmartWagers/administrator.html'
    )

    assert '#teller-alert-panel.collapsed #tap-body' in template
    assert "panel.classList.toggle('collapsed')" in template


def test_payout_hold_control_is_wired():
    admin_template = read_project_file(
        'SmartWagers/templates/SmartWagers/administrator.html'
    )
    user_template = read_project_file(
        'SmartWagers/templates/SmartWagers/user.html'
    )
    admin_js = read_project_file(
        'SmartWagers/static/SmartWagers/administrator.js'
    )
    user_js = read_project_file(
        'SmartWagers/static/SmartWagers/user.js'
    )
    wagers_js = read_project_file(
        'SmartWagers/static/SmartWagers/submit_wagers.js'
    )

    assert 'id=\'payout_hold_button\'' in admin_template or 'id="payout_hold_button"' in admin_template
    assert 'togglePayoutHold()' in admin_template
    assert 'PAYOUTS_HELD' in admin_template
    assert 'PAYOUTS_HOLD_URL' in admin_template
    assert 'payout-hold-banner' in admin_template
    assert 'PAYOUTS_HELD' in user_template
    assert 'payout-hold-banner' in user_template
    assert 'openPayoutModal()' in admin_template
    assert 'openPayoutModal()' in user_template

    assert 'payouts_held:' in admin_js
    assert 'Payouts are temporarily on hold by the administrator.' in admin_js
    assert 'function applyPayoutHoldUI' in admin_js
    assert 'function togglePayoutHold' in admin_js
    assert 'function openPayoutModal' in admin_js
    assert '"payouts_held" in data' in admin_js
    assert '"payouts_held" in data' in user_js
    assert 'openPayoutModal()' in wagers_js
    assert "'payouts_held': payouts_held" in read_project_file('SmartWagers/views.py') \
        or '"payouts_held": payouts_held' in read_project_file('SmartWagers/views.py')
