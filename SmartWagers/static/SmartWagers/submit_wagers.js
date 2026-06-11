let bet_total = 0;
let wager_value = 0;
let wager_id = '';

function formatNumber(n) {
    return Number(n).toLocaleString('en-US');
}

function stripCommas(str) {
    return String(str).replace(/,/g, '');
}

function getSelectedSide() {
    if (document.getElementById('radio_meron')?.checked) return 'MERON';
    if (document.getElementById('radio_wala')?.checked) return 'WALA';
    return null; /* neutral / no side chosen */
}

function focusBetInput() {
    const textarea = document.getElementById('bet_textinput');
    if (textarea) textarea.focus();
}

function addValue(value) {
    bet_total += value;
    const textarea = document.getElementById('bet_textinput');
    if (textarea) textarea.value = formatNumber(bet_total);
    focusBetInput();
}

function resetBet() {
    bet_total = 0;
    const textarea = document.getElementById('bet_textinput');
    if (textarea) textarea.value = '0';
    /* Return to neutral — no side selected */
    const noneRadio = document.getElementById('radio_none');
    if (noneRadio) noneRadio.checked = true;
    focusBetInput();
}

/* Legacy aliases kept for backward compatibility */
function meron_reset() { resetBet(); }
function wala_reset() { resetBet(); }
function meron_addValue(value) { addValue(value); }
function wala_addValue(value) { addValue(value); }

function check_total(side) {
    const activeSide = side || getSelectedSide();

    if (!activeSide) {
        openInvalidTotalModal('Please select a side (Meron or Wala) before placing a bet.');
        return;
    }

    const textarea = document.getElementById('bet_textinput');
    const raw = stripCommas(textarea ? textarea.value.trim() : '');

    if (!raw || raw === '0' || isNaN(raw) || Number(raw) <= 0) {
        resetBet();
        openInvalidTotalModal('Please make sure the bet amount is a valid number.');
        return;
    }
    openConfirmationModal(raw, activeSide);
}

function resetTotal() {
    resetBet();
    document.getElementById('wager_value').value = '';
    document.getElementById('wager_id').value = '';
}

function openConfirmationModal(total, side) {
    wager_value = total;
    wager_id = side;
    const summaryValue = document.getElementById('summaryValue');
    const confirmside = document.getElementById('confirmside');
    confirmside.innerText = wager_id;
    summaryValue.innerText = 'Total: ' + wager_value; // Display the total in the modal
    document.getElementById('confirmationModal').style.display = 'flex'; // Show the modal
}

function closeModal() {
    document.getElementById('confirmationModal').style.display = 'none';
    resetTotal();
    focusBetInput();
}

function openInvalidTotalModal(message) {
    const msg = document.getElementById('invalidtotal-message');
    if (msg && message) msg.textContent = message;
    document.getElementById('invalidtotalModal').style.display = 'flex';
}

function closeInvalidTotalModal() {
    document.getElementById('invalidtotalModal').style.display = 'none';
    resetTotal();
    focusBetInput();
}

function cancelBet() {
    total = 0;
    wager_id = '';
}

function normalizeWagerStatus(status) {
    return status === "CLOSE" ? "CLOSED" : status;
}

function showClosedBettingModal(side) {
    if (side === "MERON" || side === "BOTH") {
        if (typeof closeMeronUser === "function") {
            closeMeronUser();
        }
    }

    if (side === "WALA" || side === "BOTH") {
        if (typeof closeWalaUser === "function") {
            closeWalaUser();
        }
    }

    if (typeof openbettingdisabledModal === "function") {
        openbettingdisabledModal();
        return;
    }

    const headertext = document.getElementById("modal-header-text");
    const modalmessage = document.getElementById("modal-message");
    const bettingDisabledModal = document.getElementById("bettingdisabled");
    const matchClosedModal = document.getElementById("matchclosedmodal");

    if (headertext && modalmessage && bettingDisabledModal) {
        headertext.innerHTML = "Betting is currently disabled for <strong>" + side + "</strong>.";
        modalmessage.innerHTML = "DO NOT Accept bets for <strong>" + side + "</strong> until the betting is enabled again.";
        bettingDisabledModal.style.display = "flex";
        return;
    }

    if (matchClosedModal) {
        matchClosedModal.style.display = "flex";
        return;
    }

    alert("Betting is currently disabled for " + side + ".");
}

function getLocalPrintAgentUrl() {
    return (localStorage.getItem("smartwagersPrintAgentUrl") || "http://127.0.0.1:8765").replace(/\/$/, "");
}

async function printWagerReceipt(receipt) {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 5000);

    try {
        const response = await fetch(`${getLocalPrintAgentUrl()}/print-wager`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify(receipt),
            signal: controller.signal,
        });
        let result = {};
        try {
            result = await response.json();
        } catch (error) {
            result = {};
        }

        if (!response.ok || !result.ok) {
            return {
                ok: false,
                message: result.error || `Local print agent returned HTTP ${response.status}.`,
            };
        }

        return {
            ok: true,
            message: result.message || "Bet receipt sent to local printer.",
        };
    } catch (error) {
        return {
            ok: false,
            message: error.name === "AbortError"
                ? "Local print agent did not respond."
                : "Local print agent is not running or is blocked.",
        };
    } finally {
        clearTimeout(timeoutId);
    }
}

async function postWagerAction(form, action, transactionId) {
    const formData = new FormData(form);
    formData.set("action", action);
    formData.set("transaction_id", transactionId);

    const response = await fetch(form.action || window.location.href, {
        method: "POST",
        body: formData,
        headers: {
            "X-Requested-With": "XMLHttpRequest",
        },
    });
    const result = await response.json();

    return { response, result };
}

async function isBettingOpen(side) {
    try {
        const response = await fetch(`/get_fight_status_view/`);
        const data = await response.json();

        if (data.overall_status !== "OPEN") {
            return false;
        }

        if (side === "MERON") {
            return normalizeWagerStatus(data.meron_status) === "OPEN";
        }

        if (side === "WALA") {
            return normalizeWagerStatus(data.wala_status) === "OPEN";
        }

        return false;
    } catch (error) {
        console.error("Unable to verify betting status:", error);
        return false;
    }
}

function shouldBlockClosedBettingForCurrentPage() {
    return Boolean(
        document.getElementById("Usersubmit") ||
        document.getElementById("Musersubmit") ||
        document.getElementById("Wusersubmit")
    );
}

async function submitValue() {
    if (shouldBlockClosedBettingForCurrentPage() && !(await isBettingOpen(wager_id))) {
        const blockedSide = wager_id;
        closeModal();
        showClosedBettingModal(blockedSide);
        resetTotal();
        return;
    }

    const wager_val = document.getElementById('wager_value');
    wager_val.value = wager_value;

    const wager_side = document.getElementById('wager_id');
    wager_side.value = wager_id;

    /* Reset textarea immediately — values already captured in the hidden fields above */
    resetBet();

    const form = document.getElementById('submitwagerForm');
    const submitButton = document.getElementById('submitvalue');
    if (submitButton) {
        submitButton.disabled = true;
        submitButton.innerText = "Submitting...";
    }

    try {
        const response = await fetch(form.action || window.location.href, {
            method: "POST",
            body: new FormData(form),
            headers: {
                "X-Requested-With": "XMLHttpRequest",
            },
        });
        const result = await response.json();

        if (!response.ok || !result.ok) {
            closeModal();
            if (result.error === "betting_closed") {
                showClosedBettingModal(result.blocked_betting_side || wager_id);
                return;
            }
            alert(result.error || "Unable to submit wager.");
            return;
        }

        if (!result.pending || result.print_required === false) {
            window.location.reload();
            return;
        }

        const printResult = await printWagerReceipt(result.receipt);
        if (!printResult.ok) {
            await postWagerAction(form, "cancel_pending", result.receipt.transaction_id);
            alert("Receipt print failed. Bet was not registered: " + printResult.message);
            closeModal();
            resetTotal();
            return;
        }

        const confirmation = await postWagerAction(form, "confirm_print", result.receipt.transaction_id);
        if (!confirmation.response.ok || !confirmation.result.ok) {
            alert("Receipt printed, but bet could not be registered. Please contact the administrator.");
            closeModal();
            resetTotal();
            return;
        }

        window.location.reload();
    } catch (error) {
        alert("Unable to submit wager. Please check the connection and try again.");
    } finally {
        if (submitButton) {
            submitButton.disabled = false;
            submitButton.innerText = "Confirm";
        }
    }

    resetTotal();
}

window.onload = function() {
    document.getElementById('wager_value').value = '';
    document.getElementById('wager_id').value = '';
};

document.addEventListener('DOMContentLoaded', () => {
    const textarea = document.getElementById('bet_textinput');
    if (!textarea) return;

    /* Auto-focus on page load */
    textarea.focus();

    /* Auto-format with commas as the user types */
    textarea.addEventListener('input', () => {
        const digits = stripCommas(textarea.value).replace(/\D/g, '');
        const num = digits === '' ? 0 : parseInt(digits, 10);
        bet_total = num;
        const formatted = num === 0 ? '' : formatNumber(num);
        /* Preserve a trailing empty state so the field feels natural to clear */
        textarea.value = digits === '' ? '' : formatted;
    });

    /* Enter key → submit instead of newline, but only when no modal is open */
    textarea.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            const hasOpenModal = [...document.querySelectorAll('.modal')].some(m => m.style.display === 'flex');
            if (!hasOpenModal) {
                e.stopPropagation(); /* consumed here — don't let document handler also fire */
                check_total();
            }
        }
    });

    /* Re-focus after switching sides with the radio buttons */
    document.querySelectorAll('input[name="bet_side"]').forEach(radio => {
        radio.addEventListener('change', () => focusBetInput());
    });

    /* M / W hotkeys to toggle Meron / Wala radio buttons */
    document.addEventListener('keydown', (e) => {
        if (e.key !== 'm' && e.key !== 'w') return;

        /* Skip when a modifier is held or focus is in any editable field */
        if (e.ctrlKey || e.altKey || e.metaKey) return;
        const tag = document.activeElement?.tagName;
        if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;

        /* Skip when any modal is open */
        const hasOpenModal = [...document.querySelectorAll('.modal')].some(m => m.style.display === 'flex');
        if (hasOpenModal) return;

        e.preventDefault();

        const meronRadio = document.getElementById('radio_meron');
        const walaRadio  = document.getElementById('radio_wala');
        const noneRadio  = document.getElementById('radio_none');

        if (e.key === 'm' && meronRadio) {
            if (meronRadio.checked) {
                if (noneRadio) noneRadio.checked = true;
            } else {
                meronRadio.checked = true;
                meronRadio.dispatchEvent(new Event('change'));
            }
        } else if (e.key === 'w' && walaRadio) {
            if (walaRadio.checked) {
                if (noneRadio) noneRadio.checked = true;
            } else {
                walaRadio.checked = true;
                walaRadio.dispatchEvent(new Event('change'));
            }
        }

        focusBetInput();
    });
});

/* ── Global modal keyboard shortcuts ─────────────────────── *
 * Enter = primary action (Confirm / Yes / Search / Close)    *
 * Esc   = secondary action (Cancel / No / Close)             *
 * ─────────────────────────────────────────────────────────── */
document.addEventListener('keydown', (e) => {
    if (e.key !== 'Enter' && e.key !== 'Escape') return;

    /* Let the bet textarea handle Enter only when no modal is currently open */
    if (e.key === 'Enter' && document.activeElement === document.getElementById('bet_textinput')) {
        const hasOpenModal = [...document.querySelectorAll('.modal')].some(m => m.style.display === 'flex');
        if (!hasOpenModal) return;
    }

    const click = (id) => { const b = document.getElementById(id); if (b) b.click(); };
    const call  = (fn) => { if (typeof fn === 'function') fn(); };

    /* Ordered by priority — first visible modal wins */
    const modals = [
        /* id                      Enter action                           Esc action */
        ['confirmationModal',      () => click('submitvalue'),            () => call(closeModal)],
        ['invalidtotalModal',      () => call(closeInvalidTotalModal),    () => call(closeInvalidTotalModal)],
        ['control_confirmationModal', () => click('cm-yes-button'),       () => click('cm-no-button')],
        ['adminbetcontrol',        () => click('confirmopen'),            () => { if (typeof closemodal === 'function') closemodal('adminbetcontrol'); }],
        ['whowonmodal',            null,                                  () => { if (typeof closemodal === 'function') closemodal('whowonmodal'); }],
        ['payoutmodal',            () => click('payout_yes'),             () => click('payout_no')],
        ['cancelbetmodal',         () => click('cancelbet_yes'),          () => click('cancelbet_no')],
        ['payout_error_modal',     () => click('payout_error_button'),    () => click('payout_error_button')],
        ['payout_print_modal',     () => click('payout_success_button'),  () => click('payout_success_button')],
        ['matchclosedmodal',       () => { if (typeof closemodal === 'function') closemodal('matchclosedmodal'); }, () => { if (typeof closemodal === 'function') closemodal('matchclosedmodal'); }],
        ['bettingdisabled',        () => click('bettingdisabled-close-button'), () => click('bettingdisabled-close-button')],
        ['reprintmodal',           () => click('reprint_search_button'),   () => click('reprint_cancel_button')],
    ];

    for (const [id, enterAction, escAction] of modals) {
        const el = document.getElementById(id);
        if (!el || el.style.display !== 'flex') continue;

        const action = e.key === 'Enter' ? enterAction : escAction;
        if (action) {
            e.preventDefault();
            action();
        }
        break; /* Only the topmost visible modal gets the keystroke */
    }
});