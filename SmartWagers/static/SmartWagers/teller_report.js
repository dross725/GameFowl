(function () {
    const cfg = window.TELLER_REPORT || {};
    let activeCloseOut = cfg.closeOut;

    function formatMoney(value) {
        const num = Number(value) || 0;
        return '₱ ' + num.toLocaleString(undefined, {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
        });
    }

    function getCsrfToken() {
        return document.querySelector('[name=csrfmiddlewaretoken]')?.value || '';
    }

    function buildSummaryRows(data) {
        return [
            ['Event', data.event_name || cfg.activeEvent || '—'],
            ['Teller', cfg.tellerName || '—'],
            ['Closed Fight #', String(data.fightnum ?? cfg.currentFightnum ?? '—')],
            ['Gross Bets Collected', formatMoney(data.grand_total)],
            ['Advanced', formatMoney(data.remit_total)],
            ['Borrowed', formatMoney(data.collect_total)],
            ['Payouts', formatMoney(data.payout_total)],
            ['Expected Cash On Hand', formatMoney(data.expected_cash_on_hand)],
        ];
    }

    function renderSummary(container, data) {
        if (!container) return;
        container.innerHTML = buildSummaryRows(data).map(([label, value]) => {
            const highlight = label === 'Expected Cash On Hand' ? ' highlight' : '';
            return `<div class="close-summary-row${highlight}"><span>${label}</span><strong>${value}</strong></div>`;
        }).join('');
    }

    window.openCloseStationModal = function openCloseStationModal() {
        const modal = document.getElementById('close-station-modal');
        const status = document.getElementById('close-station-status');
        const preview = document.getElementById('close-station-preview');
        if (!modal || !cfg.breakdown) return;

        const previewData = {
            event_name: cfg.activeEvent,
            fightnum: cfg.currentFightnum,
            grand_total: cfg.breakdown.grand_total,
            remit_total: cfg.breakdown.remit_total,
            collect_total: cfg.breakdown.collect_total,
            payout_total: cfg.breakdown.payout_total,
            expected_cash_on_hand: cfg.expectedBalance,
        };
        renderSummary(preview, previewData);
        if (status) {
            status.className = '';
            status.textContent = '';
        }
        modal.classList.add('open');
    };

    window.closeCloseStationModal = function closeCloseStationModal(event) {
        if (event && event.target !== event.currentTarget) return;
        const modal = document.getElementById('close-station-modal');
        if (modal) modal.classList.remove('open');
    };

    window.openCloseSummaryModal = function openCloseSummaryModal() {
        const modal = document.getElementById('close-summary-modal');
        const content = document.getElementById('close-summary-content');
        if (!modal || !activeCloseOut) return;
        renderSummary(content, activeCloseOut);
        modal.classList.add('open');
    };

    window.closeCloseSummaryModal = function closeCloseSummaryModal(event) {
        if (event && event.target !== event.currentTarget) return;
        const modal = document.getElementById('close-summary-modal');
        if (modal) modal.classList.remove('open');
    };

    window.printCloseSummary = function printCloseSummary() {
        if (!activeCloseOut) return;
        const rows = buildSummaryRows(activeCloseOut);
        const html = `
            <html><head><title>Station Close Summary</title>
            <style>
              body { font-family: Arial, sans-serif; padding: 24px; }
              h1 { font-size: 18px; margin-bottom: 12px; }
              table { width: 100%; border-collapse: collapse; }
              td { padding: 6px 0; border-bottom: 1px solid #ddd; }
              td:last-child { text-align: right; font-weight: bold; }
            </style></head><body>
            <h1>Station Close Summary</h1>
            <table>${rows.map(([label, value]) =>
                `<tr><td>${label}</td><td>${value}</td></tr>`
            ).join('')}</table>
            </body></html>`;
        const win = window.open('', '_blank', 'width=480,height=640');
        if (!win) return;
        win.document.write(html);
        win.document.close();
        win.focus();
        win.print();
    };

    window.confirmCloseStation = async function confirmCloseStation() {
        const btn = document.getElementById('close-station-confirm-btn');
        const status = document.getElementById('close-station-status');
        if (!btn || !cfg.closeStationUrl) return;

        btn.disabled = true;
        if (status) {
            status.className = '';
            status.textContent = 'Closing station…';
        }

        try {
            const response = await fetch(cfg.closeStationUrl, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded',
                    'X-CSRFToken': getCsrfToken(),
                    'X-Requested-With': 'XMLHttpRequest',
                },
                body: '',
            });
            const data = await response.json();
            if (!data.ok) {
                const message = data.error === 'no_active_event'
                    ? 'No active event. Close station is unavailable.'
                    : data.error === 'already_closed'
                        ? 'Station is already closed.'
                        : 'Failed to close station. Please try again.';
                if (status) {
                    status.className = 'error';
                    status.textContent = message;
                }
                btn.disabled = false;
                return;
            }

            activeCloseOut = data.close_out;
            cfg.stationClosed = true;
            closeCloseStationModal();
            openCloseSummaryModal();
            window.location.reload();
        } catch (err) {
            console.error('Close station error:', err);
            if (status) {
                status.className = 'error';
                status.textContent = 'Network error. Please try again.';
            }
            btn.disabled = false;
        }
    };
})();
