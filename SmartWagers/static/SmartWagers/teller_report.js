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

    function formatAmount(value) {
        return '₱ ' + Number(value || 0).toLocaleString('en-PH', {
            maximumFractionDigits: 0,
        });
    }

    function getCsrfToken() {
        return document.querySelector('[name=csrfmiddlewaretoken]')?.value || '';
    }

    function stripCommas(str) {
        return String(str).replace(/,/g, '');
    }

    function statusBadgeHtml(status) {
        if (status === 'cancelled') {
            return '<span class="fund-status-badge cancelled">Cancelled</span>';
        }
        if (status === 'received') {
            return '<span class="fund-status-badge received">Received</span>';
        }
        if (status === 'edited') {
            return '<span class="fund-status-badge edited">Edited</span>';
        }
        if (status === 'pending') {
            return '<span class="fund-status-badge pending">Pending</span>';
        }
        return '<span class="fund-status-badge issued">Issued</span>';
    }

    function pendingActionsHtml(txnId, amount) {
        return `
            <button type="button" class="fund-action-btn edit-btn"
                    onclick="openEditRemitModal('${txnId}', ${Number(amount)})">
              Edit
            </button>
            <button type="button" class="fund-action-btn cancel-btn"
                    onclick="cancelOwnRemit('${txnId}')">
              Cancel
            </button>
        `;
    }

    function updateFundRow(data) {
        const txnId = data.transaction_id;
        const row = document.getElementById(`fund-row-${txnId}`);
        if (!row) return;

        const status = data.status
            || (data.cancelled ? 'cancelled'
                : data.received ? 'received'
                : data.edited ? 'edited'
                : 'pending');

        row.dataset.status = status;
        row.dataset.amount = data.amount;
        row.classList.toggle('row-cancelled', status === 'cancelled');

        const amountEl = document.getElementById(`fund-amount-${txnId}`);
        if (amountEl) amountEl.textContent = formatAmount(data.amount);

        const statusEl = document.getElementById(`fund-status-${txnId}`);
        if (statusEl) statusEl.innerHTML = statusBadgeHtml(status);

        const actionsEl = document.getElementById(`fund-actions-${txnId}`);
        if (actionsEl) {
            if (status === 'pending' || status === 'edited') {
                actionsEl.innerHTML = pendingActionsHtml(txnId, data.amount);
            } else {
                actionsEl.innerHTML = '<span class="fund-action-none">—</span>';
            }
        }

        if (typeof data.balance === 'number') {
            cfg.expectedBalance = data.balance;
        }
    }

    window.openEditRemitModal = function openEditRemitModal(txnId, amount) {
        const modal = document.getElementById('edit-remit-modal');
        const status = document.getElementById('edit-remit-status');
        const input = document.getElementById('edit-remit-amount');
        const sub = document.getElementById('edit-remit-sub');
        const btn = document.getElementById('edit-remit-confirm-btn');
        if (!modal || !input) return;

        document.getElementById('edit-remit-txn-id').value = txnId;
        input.value = Number(amount).toLocaleString('en-US');
        if (sub) sub.textContent = `Transaction ${txnId}`;
        if (status) {
            status.className = '';
            status.textContent = '';
        }
        if (btn) btn.disabled = false;
        modal.classList.add('open');
        setTimeout(() => {
            input.focus();
            input.select();
        }, 80);
    };

    window.closeEditRemitModal = function closeEditRemitModal(event) {
        if (event && event.target !== event.currentTarget) return;
        const modal = document.getElementById('edit-remit-modal');
        if (modal) modal.classList.remove('open');
    };

    window.submitEditRemit = async function submitEditRemit() {
        const txnId = document.getElementById('edit-remit-txn-id').value;
        const input = document.getElementById('edit-remit-amount');
        const status = document.getElementById('edit-remit-status');
        const btn = document.getElementById('edit-remit-confirm-btn');
        const amount = parseFloat(stripCommas(input.value));

        if (!amount || amount <= 0 || isNaN(amount)) {
            if (status) {
                status.className = 'error';
                status.textContent = 'Please enter a valid amount.';
            }
            return;
        }

        if (btn) btn.disabled = true;
        if (status) {
            status.className = '';
            status.textContent = 'Saving…';
        }

        const fd = new FormData();
        fd.append('transaction_id', txnId);
        fd.append('amount', amount);
        fd.append('csrfmiddlewaretoken', getCsrfToken());

        try {
            const res = await fetch(cfg.editTxnUrl, { method: 'POST', body: fd });
            const data = await res.json();
            if (!data.ok) {
                const messages = {
                    exceeds_cash_on_hand: 'Advance amount cannot exceed available cash.',
                    already_received: 'This advance was already received.',
                    cancelled: 'This advance was already cancelled.',
                    not_found: 'Advance not found.',
                    invalid_amount: 'Please enter a valid amount.',
                };
                if (status) {
                    status.className = 'error';
                    status.textContent = messages[data.error] || `Error: ${data.error || 'Unknown'}`;
                }
                if (btn) btn.disabled = false;
                return;
            }
            updateFundRow(data);
            closeEditRemitModal();
        } catch (err) {
            if (status) {
                status.className = 'error';
                status.textContent = 'Network error. Please try again.';
            }
            if (btn) btn.disabled = false;
        }
    };

    window.cancelOwnRemit = async function cancelOwnRemit(txnId) {
        if (!confirm(`Cancel advance ${txnId}? This pending advance will be voided.`)) {
            return;
        }

        const fd = new FormData();
        fd.append('transaction_id', txnId);
        fd.append('csrfmiddlewaretoken', getCsrfToken());

        try {
            const res = await fetch(cfg.cancelTxnUrl, { method: 'POST', body: fd });
            const data = await res.json();
            if (!data.ok) {
                const messages = {
                    already_received: 'This advance was already received.',
                    cancelled: 'This advance was already cancelled.',
                    not_found: 'Advance not found.',
                };
                alert(messages[data.error] || `Error: ${data.error || 'Unknown'}`);
                return;
            }
            updateFundRow(data);
        } catch (err) {
            alert('Network error. Please try again.');
        }
    };

    (function attachAmountFormatter() {
        const input = document.getElementById('edit-remit-amount');
        if (!input || input._fmtAttached) return;
        input._fmtAttached = true;
        input.addEventListener('input', () => {
            const digits = stripCommas(input.value).replace(/\D/g, '');
            input.value = digits === '' ? '' : Number(digits).toLocaleString('en-US');
        });
    })();

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            closeEditRemitModal();
            closeCloseStationModal();
            closeCloseSummaryModal();
        }
    });

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
