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


def test_teller_alert_panel_has_real_collapse_behavior():
    template = read_project_file(
        'SmartWagers/templates/SmartWagers/administrator.html'
    )

    assert '#teller-alert-panel.collapsed #tap-body' in template
    assert "panel.classList.toggle('collapsed')" in template
