const userWebsocketProtocol = window.location.protocol === "https:" ? "wss" : "ws";
const userSocket = new WebSocket(`${userWebsocketProtocol}://${window.location.host}/ws/user/`);

userSocket.onmessage = (event) => {
    const data = JSON.parse(event.data);
    console.log("Data received from server: ", data);
    console.log("This is the user.js file");

    // Update left and right values
    if ("mtotal" in data && "wtotal" in data) {
        document.getElementById("M_total_bet").innerText = data.mtotal;
        document.getElementById("M_payout").innerText = "PAYOUT: " + data.mpayout;
        document.getElementById("W_total_bet").innerText = data.wtotal;
        document.getElementById("W_payout").innerText = "PAYOUT: " + data.wpayout;
        document.getElementById("ws_status").innerText = "Status: Connected";
        updateStatus("Connected");
        updateFightnum(data.fightnum)
        console.log("Data received:", data);
    }

    if ("side" in data && "side_status" in data) {
        const side = data.side;
        const status = normalizeBettingStatus(data.side_status);
        console.log("Changing status of ", side + " to " + status);
        updateUserBettingStatus(status, side);
        if (status === "CLOSED") {
            bettingReopenedUser = false;
            openbettingdisabledModal();
        } else if (status === "OPEN") {
            bettingReopenedUser = true;
            update_disp_FightStatus("OPEN");
        }
    }

    if ("meron_status" in data && "wala_status" in data) {
        updateUserBettingStatus(data.meron_status, "MERON");
        updateUserBettingStatus(data.wala_status, "WALA");
        updateFightnum(data.fightnum);
    }

    if ("fight_status" in data) {
        get_fightstatus();
        if (data.fight_status === "END" || data.fight_status === "CANCEL") {
            update_trends();
            // A result was just declared — check for newly payable tickets
            fetchPendingPayouts();
        }
    }

    if ("overall_status" in data) {
        update_disp_FightStatus(data.overall_status);
    }

    if ("payout" in data) {
        console.log("[user.js] payout message received:", data);
        handlePayoutMessage(data);
        // Payout processed — refresh pending count and balance
        fetchPendingPayouts();
        fetchTellerBalance();
    }

    if ("cancel_bet" in data) {
        console.log("[user.js] cancel_bet message received:", data);
        if ("error" in data) {
            document.getElementById('payout_error_header').innerText = "Cancel Bet Error";
            openmodal('payout_error_modal', data.error);
        } else if ("transaction_id" in data && "amount" in data) {
            document.getElementById('payout_success_header').innerText = "Cancel Bet";
            document.getElementById('payout_message1').innerText = "Transaction ID: " + data.transaction_id;
            document.getElementById('payout_message2').innerText = "Please refund: ₱ " + data.amount;
            document.getElementById('payout_message3').innerText = "";
            document.getElementById('payout_print_modal').style.display = 'flex';
        }
        // Refresh balance and per-fight totals — cancel reverses collected cash
        fetchTellerBalance();
        fetchFightTotals();
    }
}; 

userSocket.onopen = () => {
    console.log("WebSocket connected!");
    userSocket.send(JSON.stringify({ update: true }));
    console.log("Initial data request sent.");
    updateStatus("Connected");
    get_fightstatus();
};

userSocket.onerror = (error) => {
    console.error("WebSocket Error:", error);
};

userSocket.onclose = () => {
    console.log("WebSocket disconnected!");
    updateStatus("Disconnected");
};
// });

function updateStatus(status) {
    document.getElementById("ws_status").innerText = "Status: " + status;
    document.getElementById("ws_status").style.color = status === "Connected" ? "green" : "red";
    document.getElementById("ws_status").style.fontWeight = "bold";
};

let _lastFightnum = null;

function updateFightnum(fightnum){
    document.getElementById("currentmatchnum").innerText = fightnum;
    // When the fight number changes, reset and refetch per-fight totals
    if (fightnum !== _lastFightnum) {
        _lastFightnum = fightnum;
        updateFightTotals(0, 0);
        fetchFightTotals();
    }
};

function normalizeBettingStatus(status) {
    return status === "CLOSE" ? "CLOSED" : status;
}

function updateUserBettingStatus(status, side) {
    status = normalizeBettingStatus(status);

    if (status === "CLOSED") {
        if (side === "MERON" || side === "BOTH") {
            closeMeronUser();
        }
        if (side === "WALA" || side === "BOTH") {
            closeWalaUser();
        }
        resetTotal();
        return;
    }

    if (status === "OPEN") {
        if (side === "MERON" || side === "BOTH") {
            openMeronUser();
        }
        if (side === "WALA" || side === "BOTH") {
            openWalaUser();
        }
        resetTotal();
    }
}

function setBettingStatusText(element, status) {
    element.innerHTML = status;
    element.style.backgroundColor = status === "OPEN" ? "rgba(7, 248, 2, 0.573)" : "rgba(248, 7, 7, 0.573)";
    element.style.textAlign = "center";
}

let meronBettingOpen = false;
let walaBettingOpen = false;

// Mirrors the admin's bettingReopened flag so the teller page stays in sync
// when the admin re-opens betting on a server-CLOSED fight.
let bettingReopenedUser = false;

// Disable/enable all bet input buttons and the amount textarea.
// Defined here so it works even if administrator.js is cached at an old version.
function setBetInputsDisabled(disabled) {
    const container = document.getElementById('unified-wagers');
    if (!container) return;
    container.querySelectorAll('.button').forEach(btn => {
        if (disabled) {
            btn.classList.add('btn-bet-disabled');
        } else {
            btn.classList.remove('btn-bet-disabled');
        }
    });
    const textarea = document.getElementById('bet_textinput');
    if (textarea) textarea.disabled = disabled;
}

function updateUserSubmitButton() {
    const submitButton = document.getElementById("Usersubmit");
    if (!submitButton) return;
    const side = getSelectedSide();
    if (!side) {
        /* No side selected yet — check_total will show the "select a side" warning */
        submitButton.onclick = () => check_total();
        return;
    }
    const isOpen = (side === "MERON") ? meronBettingOpen : walaBettingOpen;
    submitButton.onclick = isOpen
        ? () => check_total()
        : () => openbettingdisabledModal();
}

function updateOnClick(ButtonStatus, side) {
    ButtonStatus = normalizeBettingStatus(ButtonStatus);
    const headertext = document.getElementById("modal-header-text");
    const modalmessage = document.getElementById("modal-message");

    if (ButtonStatus === 'CLOSED') {
        headertext.innerHTML = "Betting is currently disabled for <strong>" + side + "</strong>.";
        modalmessage.innerHTML = "DO NOT Accept bets for <strong>" + side + "</strong> until the betting is enabled again.";
        if (side === "MERON" || side === "BOTH") {
            setBettingStatusText(document.getElementById("meron-betting-status"), "CLOSED");
            meronBettingOpen = false;
        }
        if (side === "WALA" || side === "BOTH") {
            setBettingStatusText(document.getElementById("wala-betting-status"), "CLOSED");
            walaBettingOpen = false;
        }
    } else if (ButtonStatus === 'OPEN') {
        headertext.innerHTML = "Betting is enabled for <strong>" + side + "</strong>.";
        modalmessage.innerHTML = "You can now accept bets for <strong>" + side + "</strong>.";
        if (side === "MERON" || side === "BOTH") {
            setBettingStatusText(document.getElementById("meron-betting-status"), "OPEN");
            meronBettingOpen = true;
        }
        if (side === "WALA" || side === "BOTH") {
            setBettingStatusText(document.getElementById("wala-betting-status"), "OPEN");
            walaBettingOpen = true;
        }
    }
    updateUserSubmitButton();
    resetTotal();
};


function openbettingdisabledModal() {
    document.getElementById('bettingdisabled').style.display = 'flex';
    resetTotal();
};

function closebettingdisabledModal(event) {
    if (event) {
        event.preventDefault();
        event.stopPropagation();
    }

    const bettingDisabledModal = document.getElementById('bettingdisabled');
    if (bettingDisabledModal) {
        bettingDisabledModal.style.display = 'none';
        bettingDisabledModal.removeAttribute('style');
    }
    resetTotal();  // Reset totals when modal is closed
};

function openMeronUser() {
    console.log("openMeron user");
    meronBettingOpen = true;
    setBettingStatusText(document.getElementById("meron-betting-status"), "OPEN");
    setBetInputsDisabled(false);
    updateUserSubmitButton();
}

function openWalaUser() {
    walaBettingOpen = true;
    setBettingStatusText(document.getElementById("wala-betting-status"), "OPEN");
    setBetInputsDisabled(false);
    updateUserSubmitButton();
}

function closeMeronUser() {
    console.log("close meron");
    meronBettingOpen = false;
    setBettingStatusText(document.getElementById("meron-betting-status"), "CLOSED");
    const modalheader = document.getElementById("modal-header-text");
    const modalmessage = document.getElementById("modal-message");
    if (modalheader) modalheader.innerHTML = "Betting is currently disabled for <strong>MERON</strong>.";
    if (modalmessage) modalmessage.innerHTML = "DO NOT Accept bets for <strong>MERON</strong> until the betting is enabled again.";
    if (!meronBettingOpen && !walaBettingOpen) setBetInputsDisabled(true);
    updateUserSubmitButton();
}

function closeWalaUser() {
    walaBettingOpen = false;
    setBettingStatusText(document.getElementById("wala-betting-status"), "CLOSED");
    const modalheader = document.getElementById("modal-header-text");
    const modalmessage = document.getElementById("modal-message");
    if (modalheader) modalheader.innerHTML = "Betting is currently disabled for <strong>WALA</strong>.";
    if (modalmessage) modalmessage.innerHTML = "DO NOT Accept bets for <strong>WALA</strong> until the betting is enabled again.";
    if (!meronBettingOpen && !walaBettingOpen) setBetInputsDisabled(true);
    updateUserSubmitButton();
}

async function get_fightstatus(){
    const response = await fetch(`/get_fight_status_view/`);
    console.log('response: ' +response);
    const data = await response.json();
    console.log("Fight status data received: ", data);

    const event_active = data.event_active;
    applyEventState(event_active);

    if (!event_active) {
        update_disp_FightStatus('NO EVENT');
        return;
    }

    let fight_num = data.fightnum;
    let fight_status = data.overall_status;
    let m_status = data.meron_status;
    let w_status = data.wala_status;

    console.log("Fight status: ", fight_status);

    // Reset the reopen flag whenever the fight moves to any state other than CLOSED
    if (fight_status !== 'CLOSED') bettingReopenedUser = false;

    // Use the effective status for display — keep showing OPEN if admin re-opened
    const effectiveStatus = (fight_status === 'CLOSED' && bettingReopenedUser) ? 'OPEN' : fight_status;

    if (effectiveStatus === "OPEN") {
        if (bettingReopenedUser || normalizeBettingStatus(m_status) === "OPEN") {
            openMeronUser();
        } else {
            closeMeronUser();
        }
        if (bettingReopenedUser || normalizeBettingStatus(w_status) === "OPEN") {
            openWalaUser();
        } else {
            closeWalaUser();
        }
    } else {
        closeMeronUser();
        closeWalaUser();
        const submitButton = document.getElementById("Usersubmit");
        if (submitButton) submitButton.onclick = () => openmodal('matchclosedmodal', 'null');
    }
    update_disp_FightStatus(effectiveStatus);
    updateFightnum(fight_num);
};

function applyEventState(event_active) {
    const ids = ['Usersubmit'];
    if (!event_active) {
        ids.forEach(id => {
            const btn = document.getElementById(id);
            if (btn) { btn.onclick = null; btn.classList.add('btn-event-disabled'); }
        });
        closeMeronUser();
        closeWalaUser();
    } else {
        ids.forEach(id => {
            const btn = document.getElementById(id);
            if (btn) btn.classList.remove('btn-event-disabled');
        });
    }
}

async function fetchButtonState() {
    console.log("Fetching button state from server...");
    const headertext = document.getElementById("modal-header-text");
    const modalmessage = document.getElementById("modal-message");
    const mbettingstatus = document.getElementById("meron-betting-status");
    const wbettingstatus = document.getElementById("wala-betting-status");
    try {
        const response = await fetch(`/get_button_state_view/`);  // Fetch state from API
        const data = await response.json();
        console.log("Button state data received: ", data);

        if (data.mstate == 'Open') {
            setBettingStatusText(mbettingstatus, "OPEN");
            meronBettingOpen = true;
        } else if (data.mstate == 'Close') {
            setBettingStatusText(mbettingstatus, "CLOSED");
            meronBettingOpen = false;
            headertext.innerHTML = "Betting is currently disabled for <strong>MERON</strong>.";
            modalmessage.innerHTML = "DO NOT Accept bets for <strong>MERON</strong> until the betting is enabled again.";
            if (!sessionStorage.getItem("buttonStateChecked")) {
                openbettingdisabledModal();
                sessionStorage.setItem("buttonStateChecked", "true");
            }
        }

        if (data.wstate == 'Open') {
            setBettingStatusText(wbettingstatus, "OPEN");
            walaBettingOpen = true;
        } else if (data.wstate == 'Close') {
            setBettingStatusText(wbettingstatus, "CLOSED");
            walaBettingOpen = false;
            headertext.innerHTML = "Betting is currently disabled for <strong>WALA</strong>.";
            modalmessage.innerHTML = "DO NOT Accept bets for <strong>WALA</strong> until the betting is enabled again.";
            if (!sessionStorage.getItem("buttonStateChecked")) {
                openbettingdisabledModal();
                sessionStorage.setItem("buttonStateChecked", "true");
            }
        }

        if (data.wstate == 'Close' && data.mstate == 'Close') {
            headertext.innerText = "Betting is currently CLOSED!";
            modalmessage.innerText = "Please wait for the admin to open betting";
        }

        updateUserSubmitButton();
        console.log("Button states updated successfully.");

    } catch (error) {
        console.error("Error fetching button state:", error);
    }
};

// Call this function when the page loads
document.addEventListener("DOMContentLoaded", () => {
    console.log("Fetching button states on page load...");
    const bettingDisabledCloseButton = document.getElementById("bettingdisabled-close-button");
    if (bettingDisabledCloseButton) {
        bettingDisabledCloseButton.addEventListener("click", closebettingdisabledModal);
    }
    //fetchButtonState();
    get_fightstatus();  // Fetch fight status on page load
    fetchTellerBalance();
    fetchFightTotals();
    fetchPendingPayouts();
});
// window.onload = function() {
//     console.log("Fetching button states on page load...");
//     fetchButtonState();
// }

// ── Teller balance ────────────────────────────────────────

function formatBalance(value) {
    const num = Number(value);
    return '₱ ' + num.toLocaleString('en-PH', { minimumFractionDigits: 0, maximumFractionDigits: 2 });
}

function updateBalanceButton(balance) {
    const btn = document.getElementById('balance_button');
    if (btn) btn.innerText = formatBalance(balance);
}

function updateBalanceModal(balance, grandTotal) {
    const display = document.getElementById('balance_display');
    const gtDisplay = document.getElementById('grand_total_display');
    if (display) display.innerText = formatBalance(balance);
    if (gtDisplay) gtDisplay.innerText = formatBalance(grandTotal);
}

async function fetchTellerBalance() {
    try {
        const response = await fetch('/get_teller_balance/');
        const data = await response.json();
        if (data.ok) {
            updateBalanceButton(data.balance);
            return data;
        }
    } catch (error) {
        console.error('Error fetching teller balance:', error);
    }
    return null;
}

// ── Pending payout notification ───────────────────────────

async function fetchPendingPayouts() {
    try {
        const response = await fetch('/get_pending_payouts/');
        const data = await response.json();
        if (!data.ok) return;

        const badge  = document.getElementById('pending-payouts-badge');
        const countEl = document.getElementById('pending-payouts-count');
        const totalEl = document.getElementById('pending-payouts-total');
        if (!badge) return;

        if (data.count > 0) {
            countEl.innerText = data.count;
            totalEl.innerText = '₱ ' + Number(data.total).toLocaleString('en-PH', { minimumFractionDigits: 0, maximumFractionDigits: 2 });
            badge.style.display = 'flex';
        } else {
            badge.style.display = 'none';
        }
    } catch (error) {
        console.error('Error fetching pending payouts:', error);
    }
}

// ── Per-fight bet totals ───────────────────────────────────

function updateFightTotals(meronTotal, walaTotal) {
    const fmt = (v) => '₱ ' + Number(v).toLocaleString('en-PH', { minimumFractionDigits: 0, maximumFractionDigits: 2 });
    const mEl = document.getElementById('teller-meron-total');
    const wEl = document.getElementById('teller-wala-total');
    if (mEl) mEl.innerText = fmt(meronTotal);
    if (wEl) wEl.innerText = fmt(walaTotal);
}

async function fetchFightTotals() {
    try {
        const response = await fetch('/get_teller_fight_totals/');
        const data = await response.json();
        if (data.ok) {
            updateFightTotals(data.meron_total, data.wala_total);
        }
    } catch (error) {
        console.error('Error fetching fight totals:', error);
    }
}

async function openBalanceModal() {
    const data = await fetchTellerBalance();
    const balance = data?.balance ?? 0;
    const grandTotal = data?.grand_total ?? 0;
    updateBalanceModal(balance, grandTotal);

    const amountInput = document.getElementById('balance_amount');
    if (amountInput) {
        amountInput.value = '';
        // Attach comma-formatting once (guard against duplicate listeners)
        if (!amountInput._balanceFormatted) {
            amountInput._balanceFormatted = true;
            amountInput.addEventListener('input', () => {
                const digits = stripCommas(amountInput.value).replace(/\D/g, '');
                const num = digits === '' ? 0 : parseInt(digits, 10);
                amountInput.value = digits === '' ? '' : formatNumber(num);
            });
        }
    }
    const statusMsg = document.getElementById('balance_status_message');
    if (statusMsg) statusMsg.innerText = '';
    document.getElementById('balancemodal').style.display = 'flex';
    setTimeout(() => { if (amountInput) amountInput.focus(); }, 100);
}

async function printRemitReceipt(payload) {
    const localPrintAgentUrl = (localStorage.getItem("smartwagersPrintAgentUrl") || "http://127.0.0.1:8765").replace(/\/$/, "");
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 5000);
    try {
        const response = await fetch(`${localPrintAgentUrl}/print-remit`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
            signal: controller.signal,
        });
        let result = {};
        try { result = await response.json(); } catch (_) {}
        if (!response.ok || !result.ok) {
            return { ok: false, message: result.error || `Print agent returned HTTP ${response.status}.` };
        }
        return { ok: true, message: result.message || 'Receipt sent to printer.' };
    } catch (error) {
        return {
            ok: false,
            message: error.name === 'AbortError'
                ? 'Local print agent did not respond.'
                : 'Local print agent is not running or is blocked.',
        };
    } finally {
        clearTimeout(timeoutId);
    }
}

async function submitTellerTransaction(type) {
    const amountInput = document.getElementById('balance_amount');
    const statusMsg = document.getElementById('balance_status_message');
    const amount = parseFloat(stripCommas(amountInput.value));

    if (!amount || amount <= 0 || isNaN(amount)) {
        statusMsg.innerText = 'Please enter a valid amount.';
        return;
    }

    const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]')?.value || '';
    statusMsg.innerText = 'Processing...';

    const remitBtn = document.getElementById('balance_remit_btn');
    if (remitBtn) remitBtn.disabled = true;

    try {
        const response = await fetch('/teller_transaction/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded',
                'X-CSRFToken': csrfToken,
                'X-Requested-With': 'XMLHttpRequest',
            },
            body: `transaction_type=${encodeURIComponent(type)}&amount=${encodeURIComponent(amount)}`,
        });
        const data = await response.json();

        if (!data.ok) {
            statusMsg.innerText = data.error === 'invalid_amount'
                ? 'Please enter a valid amount greater than zero.'
                : 'Error: ' + (data.error || 'Unknown error');
            return;
        }

        updateBalanceButton(data.balance);
        closemodal('balancemodal');

        const now = new Date();
        const dateStr = now.toLocaleString('en-PH', {
            year: 'numeric', month: '2-digit', day: '2-digit',
            hour: '2-digit', minute: '2-digit', second: '2-digit',
            hour12: false,
        });
        const label = 'Remit';

        // Show the shared print-result modal while the job is in-flight
        document.getElementById('payout_success_header').innerText = `${label} Receipt`;
        document.getElementById('payout_message1').innerText = `Txn ID   : ${data.transaction_id}`;
        document.getElementById('payout_message2').innerText = `${label} Amount : ₱ ${Number(data.amount).toLocaleString('en-PH')}`;
        document.getElementById('payout_message3').innerText = 'Sending receipt to printer...';
        document.getElementById('payout_print_modal').style.display = 'flex';

        const printResult = await printRemitReceipt({
            transaction_type: data.transaction_type,
            transaction_id: data.transaction_id,
            amount: data.amount,
            balance: data.balance,
            grand_total: data.grand_total,
            cashier: data.cashier,
            date: dateStr,
        });

        document.getElementById('payout_message3').innerText = printResult.ok
            ? 'Receipt sent to printer.'
            : 'Print failed: ' + printResult.message;

    } catch (error) {
        console.error('Transaction error:', error);
        statusMsg.innerText = 'Network error. Please try again.';
    } finally {
        if (remitBtn) remitBtn.disabled = false;
    }
}