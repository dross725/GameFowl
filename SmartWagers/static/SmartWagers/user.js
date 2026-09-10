const userWebsocketProtocol = window.location.protocol === "https:" ? "wss" : "ws";
let userSocket = null;
let _userWsReconnectTimer = null;
let _userWsReconnectAttempt = 0;
let _userWsPageUnloading = false;

window.addEventListener('beforeunload', () => {
    _userWsPageUnloading = true;
});

function openWsDisconnectedModal() {
    const modal = document.getElementById('ws_disconnected_modal');
    if (modal) modal.style.display = 'flex';
    const statusEl = document.getElementById('ws_reconnect_status');
    if (statusEl) statusEl.innerText = 'Reconnecting…';
}

function closeWsDisconnectedModal() {
    const modal = document.getElementById('ws_disconnected_modal');
    if (modal) modal.style.display = 'none';
    const statusEl = document.getElementById('ws_reconnect_status');
    if (statusEl) statusEl.innerText = 'Reconnecting…';
}

function setWsReconnectStatus(message) {
    const statusEl = document.getElementById('ws_reconnect_status');
    if (statusEl) statusEl.innerText = message;
}

function scheduleUserSocketReconnect() {
    if (_userWsPageUnloading) return;
    if (_userWsReconnectTimer) return;

    const attempt = _userWsReconnectAttempt;
    const delayMs = Math.min(30000, 1000 * Math.pow(2, Math.min(attempt, 5)));
    _userWsReconnectAttempt += 1;
    setWsReconnectStatus(`Reconnecting in ${Math.round(delayMs / 1000)}s… (attempt ${_userWsReconnectAttempt})`);

    _userWsReconnectTimer = setTimeout(() => {
        _userWsReconnectTimer = null;
        setWsReconnectStatus('Reconnecting…');
        connectUserSocket();
    }, delayMs);
}

function connectUserSocket() {
    if (_userWsPageUnloading) return;

    // Avoid stacking sockets if a reconnect overlaps an open connection.
    if (userSocket &&
        (userSocket.readyState === WebSocket.OPEN || userSocket.readyState === WebSocket.CONNECTING)) {
        return;
    }

    const socket = new WebSocket(`${userWebsocketProtocol}://${window.location.host}/ws/user/`);
    userSocket = socket;

    socket.onmessage = handleUserSocketMessage;

    socket.onopen = () => {
        console.log("WebSocket connected!");
        _userWsReconnectAttempt = 0;
        if (_userWsReconnectTimer) {
            clearTimeout(_userWsReconnectTimer);
            _userWsReconnectTimer = null;
        }
        closeWsDisconnectedModal();
        try {
            socket.send(JSON.stringify({ update: true }));
        } catch (error) {
            console.error("Initial WebSocket send failed:", error);
        }
        console.log("Initial data request sent.");
        updateStatus("Connected");
        get_fightstatus();
        fetchTellerBalance();
        fetchFightTotals();
    };

    socket.onerror = (error) => {
        console.error("WebSocket Error:", error);
    };

    socket.onclose = () => {
        console.log("WebSocket disconnected!");
        updateStatus("Disconnected");
        if (_userWsPageUnloading) return;
        openWsDisconnectedModal();
        scheduleUserSocketReconnect();
    };
}

async function handleUserSocketMessage(event) {
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
        if ("overall_status" in data) {
            applyOverallStatusDisplay(data.overall_status);
        }
        if (data.fightnum != null) {
            updateFightnum(data.fightnum);
        }
        if (status === "CLOSED") {
            bettingReopenedUser = false;
            const sideLabel = side === "BOTH" ? "Both sides" : side;
            showAppToast(
                sideLabel + " betting has been closed by the administrator.",
                "error",
                6000
            );
        } else if (status === "OPEN") {
            bettingReopenedUser = true;
            update_disp_FightStatus("OPEN");
            closebettingdisabledModal(null, true);
            closemodalIfOpen('matchclosedmodal');
        }
    } else if ("meron_status" in data && "wala_status" in data && !("fight_status" in data)) {
        // Side-status broadcasts already include meron/wala; avoid double-applying
        // when fight_status payloads also carry those fields.
        applySideStatusesFromPayload(data.meron_status, data.wala_status, data.fightnum);
    }

    if ("fight_status" in data) {
        handleFightStatusBroadcast(data);
    } else if ("overall_status" in data && !("side" in data)) {
        applyOverallStatusDisplay(data.overall_status);
    }

    if ("payout" in data) {
        console.log("[user.js] payout message received:", data);
        await handlePayoutMessage(data);
        // Payout processed — refresh pending count and balance
        fetchPendingPayouts();
        fetchTellerBalance();
    }

    if ("cancel_bet" in data) {
        console.log("[user.js] cancel_bet message received:", data);
        if ("error" in data) {
            if (data.error === 'wrong_teller') {
                showWrongTellerModal(data);
            } else {
                document.getElementById('payout_error_header').innerText = "Cancel Bet Error";
                openmodal('payout_error_modal', data.error, null, false, data.transaction_id);
            }
        } else if ("transaction_id" in data && "amount" in data) {
            document.getElementById('payout_success_header').innerText = "Cancel Bet";
            document.getElementById('payout_message1').innerText = "Transaction ID: " + data.transaction_id;
            setModalMoneyMessage(
                document.getElementById('payout_message2'),
                'Please refund: ',
                '₱ ' + data.amount,
            );
            document.getElementById('payout_message3').innerText = "";
            document.getElementById('payout_print_modal').style.display = 'flex';
            if (data.receipt && data.print_required !== false) {
                document.getElementById('payout_message3').innerText = formatTransactionMessage(
                    "Sending cancel receipt to local printer...",
                    data.transaction_id,
                );
                const printResult = await printWagerReceipt(data.receipt);
                document.getElementById('payout_message3').innerText = printResult.ok
                    ? formatTransactionMessage("Cancel receipt sent to printer.", data.transaction_id)
                    : formatTransactionMessage("Cancel receipt print failed: " + printResult.message, data.transaction_id);
            }
        }
        // Refresh balance and per-fight totals — cancel reverses collected cash
        fetchTellerBalance();
        fetchFightTotals();
    }

    if ("teller_online" in data && "teller_id" in data) {
        if (Number(data.teller_id) === Number(window.TELLER_ID)) {
            setTellerOnlineStatus(Boolean(data.teller_online));
            // Opening float is issued server-side when marked online mid-event;
            // refresh so the balance button / open advance modal are not stuck at ₱0.
            if (data.teller_online) {
                fetchTellerBalance().then((balanceData) => {
                    if (!balanceData) return;
                    const modal = document.getElementById('balancemodal');
                    if (modal && modal.style.display === 'flex') {
                        updateBalanceModal(
                            balanceData.balance ?? 0,
                            balanceData.grand_total ?? 0,
                            balanceData.opening_fund ?? 0,
                        );
                    }
                });
            }
        }
    }
}

connectUserSocket();

function closemodalIfOpen(modalId) {
    const modal = document.getElementById(modalId);
    if (modal && modal.style.display === 'flex') {
        if (typeof closemodal === 'function') {
            closemodal(modalId);
        } else {
            modal.style.display = 'none';
        }
    }
}

function setBettingDisabledModalCopy(side) {
    const headertext = document.getElementById("modal-header-text");
    const modalmessage = document.getElementById("modal-message");
    const label = side === "BOTH" ? "both sides" : side;
    if (headertext) {
        headertext.innerHTML = side === "BOTH"
            ? "Betting has been closed by the administrator"
            : ("Betting is currently disabled for <strong>" + side + "</strong>.");
    }
    if (modalmessage) {
        modalmessage.innerHTML = side === "BOTH"
            ? "DO NOT accept any more bets until the administrator re-opens betting."
            : ("DO NOT Accept bets for <strong>" + label + "</strong> until the betting is enabled again.");
    }
}

function applySideStatusesFromPayload(meronStatus, walaStatus, fightnum) {
    updateUserBettingStatus(meronStatus, "MERON");
    updateUserBettingStatus(walaStatus, "WALA");
    if (fightnum != null) {
        updateFightnum(fightnum);
    }
}

function applyOverallStatusDisplay(overallStatus) {
    if (overallStatus !== 'CLOSED') {
        bettingReopenedUser = false;
    }
    const effectiveStatus = (overallStatus === 'CLOSED' && bettingReopenedUser) ? 'OPEN' : overallStatus;
    update_disp_FightStatus(effectiveStatus);
}

function applyFightStatusFromPayload(data) {
    const fightStatus = data.overall_status;
    const meronStatus = data.meron_status;
    const walaStatus = data.wala_status;
    const fightNum = data.fightnum;

    if (fightStatus != null && fightStatus !== 'CLOSED') {
        bettingReopenedUser = false;
    }

    const effectiveStatus = (fightStatus === 'CLOSED' && bettingReopenedUser) ? 'OPEN' : fightStatus;

    if (effectiveStatus === "OPEN") {
        if (bettingReopenedUser || normalizeBettingStatus(meronStatus) === "OPEN") {
            openMeronUser();
        } else {
            closeMeronUser();
        }
        if (bettingReopenedUser || normalizeBettingStatus(walaStatus) === "OPEN") {
            openWalaUser();
        } else {
            closeWalaUser();
        }
    } else if (fightStatus != null) {
        closeMeronUser();
        closeWalaUser();
        const submitButton = document.getElementById("Usersubmit");
        if (submitButton) submitButton.onclick = () => openmodal('matchclosedmodal', 'null');
    }

    if (effectiveStatus != null) {
        update_disp_FightStatus(effectiveStatus);
    }
    if (fightNum != null) {
        updateFightnum(fightNum);
    }
}

function handleFightStatusBroadcast(data) {
    const fightAction = data.fight_status;

    // Apply server state immediately when the broadcast includes it.
    if ("overall_status" in data || "meron_status" in data) {
        applyFightStatusFromPayload(data);
    } else {
        get_fightstatus();
    }

    if (fightAction === "CLOSED") {
        bettingReopenedUser = false;
        setBettingDisabledModalCopy("BOTH");
        const matchClosed = document.getElementById('matchclosedmodal');
        if (matchClosed) {
            matchClosed.style.display = 'flex';
        } else {
            openbettingdisabledModal();
        }
    } else if (fightAction === "START") {
        bettingReopenedUser = false;
        closebettingdisabledModal();
        closemodalIfOpen('matchclosedmodal');
    } else if (fightAction === "END" || fightAction === "CANCEL") {
        bettingReopenedUser = false;
        closebettingdisabledModal();
        closemodalIfOpen('matchclosedmodal');
        update_trends();
        fetchPendingPayouts();
    } else if (fightAction === "event_changed") {
        fetchTellerBalance();
        fetchFightTotals();
        if (!("overall_status" in data)) {
            get_fightstatus();
        }
    }
}

function openTellerOfflineModal() {
    if (isTellerStationClosed()) return;
    const modal = document.getElementById('teller_offline_modal');
    if (modal) modal.style.display = 'flex';
}

function closeTellerOfflineModal() {
    const modal = document.getElementById('teller_offline_modal');
    if (modal) modal.style.display = 'none';
}

function openTellerStationClosedModal() {
    const modal = document.getElementById('teller_station_closed_modal');
    if (modal) modal.style.display = 'flex';
    closeTellerOfflineModal();
}

function closeTellerStationClosedModal() {
    const modal = document.getElementById('teller_station_closed_modal');
    if (modal) modal.style.display = 'none';
}

function setTellerStationClosed(closed) {
    window.TELLER_STATION_CLOSED = closed;
    if (closed) {
        openTellerStationClosedModal();
    } else {
        closeTellerStationClosedModal();
    }
}

function isTellerStationClosed() {
    return window.TELLER_STATION_CLOSED === true;
}

function setTellerOnlineStatus(isOnline) {
    window.TELLER_IS_ONLINE = isOnline;
    if (isTellerStationClosed()) {
        openTellerStationClosedModal();
        return;
    }
    if (isOnline) {
        closeTellerOfflineModal();
    } else {
        openTellerOfflineModal();
    }
}

function isTellerOffline() {
    return window.TELLER_IS_ONLINE === false || isTellerStationClosed();
} 

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
        return;
    }

    if (status === "OPEN") {
        if (side === "MERON" || side === "BOTH") {
            openMeronUser();
        }
        if (side === "WALA" || side === "BOTH") {
            openWalaUser();
        }
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

function closebettingdisabledModal(event, preserveBet) {
    if (event) {
        event.preventDefault();
        event.stopPropagation();
    }

    const bettingDisabledModal = document.getElementById('bettingdisabled');
    if (bettingDisabledModal) {
        bettingDisabledModal.style.display = 'none';
        bettingDisabledModal.removeAttribute('style');
    }
    if (!preserveBet) {
        resetTotal();
    }
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

    applyFightStatusFromPayload({
        overall_status: data.overall_status,
        meron_status: data.meron_status,
        wala_status: data.wala_status,
        fightnum: data.fightnum,
    });
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
    if (isTellerOffline()) {
        if (isTellerStationClosed()) {
            openTellerStationClosedModal();
        } else {
            openTellerOfflineModal();
        }
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

function updateBalanceModal(balance, grandTotal, openingFund) {
    const display = document.getElementById('balance_display');
    const gtDisplay = document.getElementById('grand_total_display');
    const openingDisplay = document.getElementById('opening_fund_display');
    if (display) {
        display.innerText = formatBalance(balance);
        display.dataset.balance = String(Number(balance) || 0);
    }
    if (gtDisplay) gtDisplay.innerText = formatBalance(grandTotal);
    if (openingDisplay) openingDisplay.innerText = formatBalance(openingFund ?? 0);
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
    // Unclaimed-bets indicator disabled on the teller view.
    const badge = document.getElementById('pending-payouts-badge');
    if (badge) badge.style.display = 'none';
    return;
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
    const openingFund = data?.opening_fund ?? 0;
    updateBalanceModal(balance, grandTotal, openingFund);

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

async function submitTellerTransaction(type) {
    const amountInput = document.getElementById('balance_amount');
    const statusMsg = document.getElementById('balance_status_message');
    const amount = parseFloat(stripCommas(amountInput.value));

    if (!amount || amount <= 0 || isNaN(amount)) {
        statusMsg.innerText = 'Please enter a valid amount.';
        return;
    }

    const balanceDisplay = document.getElementById('balance_display');
    const cashOnHand = parseFloat(balanceDisplay?.dataset?.balance ?? '0');
    if (!isNaN(cashOnHand) && amount > cashOnHand + 0.001) {
        statusMsg.innerText = 'Advance amount cannot exceed cash on hand.';
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
            if (data.error === 'exceeds_cash_on_hand') {
                statusMsg.innerText = 'Advance amount cannot exceed cash on hand.';
                if (data.balance !== undefined) {
                    updateBalanceModal(
                        data.balance,
                        data.grand_total ?? 0,
                        data.opening_fund ?? 0,
                    );
                }
            } else if (data.error === 'invalid_amount') {
                statusMsg.innerText = 'Please enter a valid amount greater than zero.';
            } else {
                statusMsg.innerText = 'Error: ' + (data.error || 'Unknown error');
            }
            return;
        }

        updateBalanceButton(data.balance);
        closemodal('balancemodal');

        const label = 'Advance';

        // Show the shared print-result modal while the job is in-flight
        document.getElementById('payout_success_header').innerText = `${label} Receipt`;
        document.getElementById('payout_message1').innerText = `Txn ID   : ${data.transaction_id}`;
        setModalMoneyMessage(
            document.getElementById('payout_message2'),
            `${label} Amount : `,
            `₱ ${Number(data.amount).toLocaleString('en-PH')}`,
        );
        document.getElementById('payout_print_modal').style.display = 'flex';

        if (data.print_required !== false) {
            document.getElementById('payout_message3').innerText = 'Sending receipt to printer...';
            const printResult = await printRemitReceipt({
                transaction_type: data.transaction_type,
                transaction_id: data.transaction_id,
                amount: data.amount,
                balance: data.balance,
                grand_total: data.grand_total,
                cashier: data.cashier,
                date: data.created_at,
            });
            document.getElementById('payout_message3').innerText = printResult.ok
                ? 'Receipt sent to printer.'
                : 'Print failed: ' + printResult.message;
        } else {
            document.getElementById('payout_message3').innerText = '';
        }

    } catch (error) {
        console.error('Transaction error:', error);
        statusMsg.innerText = 'Network error. Please try again.';
    } finally {
        if (remitBtn) remitBtn.disabled = false;
    }
}