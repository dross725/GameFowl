const administratorWebsocketProtocol = window.location.protocol === "https:" ? "wss" : "ws";
const localPrintAgentUrl = (localStorage.getItem("smartwagersPrintAgentUrl") || "http://127.0.0.1:8765").replace(/\/$/, "");

/** Normalize a wager transaction id typed or scanned by a teller.
 *  Stored IDs are zero-padded to 6 digits; accept both "123" and "000123".
 */
function normalizeWagerTransactionId(raw) {
    const tid = String(raw ?? "").trim();
    if (!tid) return "";
    if (/^\d+$/.test(tid)) return tid.padStart(6, "0");
    return tid;
}

// Only open the admin WebSocket when on the admin page.  On the teller page
// (/user) this script is also loaded for shared helpers, but creating the
// socket there immediately fails the auth check and flashes a "Disconnected"
// status.  window.location.pathname is available immediately (no DOM needed).
const _isAdminPage = !/\/user\/?$/.test(window.location.pathname);
const administratorSocket = _isAdminPage
    ? new WebSocket(`${administratorWebsocketProtocol}://${window.location.host}/ws/administrator/`)
    : { readyState: WebSocket.CLOSED, send() {}, set onopen(_) {}, set onerror(_) {}, set onclose(_) {}, set onmessage(_) {} };

// Initialize the WebSocket connection
administratorSocket.onopen = () => {
    console.log("WebSocket connected! onopen");
    administratorSocket.send(JSON.stringify({ update: true }));
    updateStatus("Connected");
    // Fetch initial fight status for display
    get_fightstatus();
};

administratorSocket.onerror = (error) => {
    console.error("WebSocket Error:", error);
};

administratorSocket.onclose = () => {
    console.log("WebSocket disconnected!");
    updateStatus("Disconnected");
}

administratorSocket.onmessage = async (event) => {
    const data = JSON.parse(event.data);
    console.log("Data received on message:", data);

    if ("fight_status" in data &&
        (data.fight_status === "END" || data.fight_status === "CANCEL")) {
        update_trends();
    }

    if (data.refresh_trends) {
        update_trends();
    }

    if ("mtotal" in data && "wtotal" in data) {
        document.getElementById("M_total_bet").innerText = data.mtotal;
        document.getElementById("M_payout").innerText = "PAYOUT: " + data.mpayout;
        document.getElementById("W_total_bet").innerText = data.wtotal;
        document.getElementById("W_payout").innerText = "PAYOUT: " + data.wpayout;
        document.getElementById("ws_status").innerText = "Status: Connected";

    }else if ("payout" in data) {
        await handlePayoutMessage(data);
    }else if ("cancel_bet" in data){
        console.log("Cancel bet result received:", data.cancel_bet);
        console.log("Cancel bet data:", data);
        if ("error" in data){
            console.log("Cancel bet error:", data.error);
            if (data.error === 'wrong_teller') {
                document.getElementById('wrong_teller_name').innerText = data.original_cashier || 'Unknown';
                document.getElementById('wrong_teller_modal').style.display = 'flex';
            } else {
                document.getElementById('payout_error_header').innerText = "Cancel Bet Error";
                openmodal('payout_error_modal', data.error);
            }
        } else if ("transaction_id" in data && "amount" in data) {
            console.log("Cancel bet success:", data);
            document.getElementById('payout_success_header').innerText = "Cancel bet request valid!";
            document.getElementById('payout_message1').innerText = "Transaction ID: " + data.transaction_id;
            document.getElementById('payout_message2').innerText = "Please refund: " + data.amount;
            document.getElementById('payout_message3').innerText = "";
            document.getElementById('payout_print_modal').style.display = 'flex';
            if (data.receipt && data.print_required !== false) {
                document.getElementById('payout_message3').innerText = "Sending cancel receipt to local printer...";
                const printResult = await printWagerReceipt(data.receipt);
                document.getElementById('payout_message3').innerText = printResult.ok
                    ? "Cancel receipt sent to printer."
                    : "Cancel receipt print failed: " + printResult.message;
            }
        }
    }
    updateStatus("Connected");
    get_fightstatus();
}

async function printPayoutReceipt(data) {
    const receipt = data.receipt || {
        receipt_type: "payout",
        transaction_id: data.transaction_id,
        fightnum: data.fightnum,
        side: data.side,
        amount: data.wager,
        odds: data.odds,
        multiplier: data.multiplier,
        Total_Payout: data.Total_Payout,
        cashier: data.cashier,
        date: data.receipt_date,
    };
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 5000);

    try {
        const response = await fetch(`${localPrintAgentUrl}/print-payout`, {
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
            message: result.message || "Receipt sent to local printer.",
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

let payoutReprintReceipt = null;

function setPayoutReprintOption(data) {
    const button = document.getElementById('payout_reprint_button');
    const status = document.getElementById('payout_reprint_status');
    payoutReprintReceipt = data.error === 'alreadypaid' && data.receipt
        ? data.receipt
        : null;

    if (button) {
        button.style.display = payoutReprintReceipt ? '' : 'none';
        button.disabled = false;
    }
    if (status) status.innerText = '';
}

async function reprintPaidPayoutReceipt() {
    if (!payoutReprintReceipt) return;

    const button = document.getElementById('payout_reprint_button');
    const status = document.getElementById('payout_reprint_status');
    if (button) button.disabled = true;
    if (status) status.innerText = 'Sending payout receipt to local printer...';

    const printResult = await printPayoutReceipt({ receipt: payoutReprintReceipt });
    if (status) {
        status.innerText = printResult.ok
            ? 'Payout receipt sent to printer.'
            : 'Payout receipt print failed: ' + printResult.message;
    }
    if (button) button.disabled = false;
}

function updateStatus(status) {
    document.getElementById("ws_status").innerText = "Status: " + status;
    document.getElementById("ws_status").style.color = status === "Connected" ? "green" : "red";
    document.getElementById("ws_status").style.fontWeight = "bold";
}

document.addEventListener("DOMContentLoaded", () => {
    console.log("Document fully loaded and parsed");
    updateStatus("Connected");
    get_fightstatus();
    update_trends();
});

/* Modal keyboard shortcuts are handled centrally in submit_wagers.js */


//start of betting functions 
function update_disp_Fightnum(fightnum) {
    document.getElementById("currentmatchnum").innerText = fightnum;
}

function update_disp_FightStatus(status) {
    document.getElementById("currentmatchstatus").innerText = "Status: " + status;
    document.getElementById("currentmatchstatus").style.color = status === "OPEN" ? "green" : "red";
    document.getElementById("currentmatchstatus").style.fontWeight = "bold";
}

async function update_disp_Pot(){
    const response = await fetch(`/get_pot_values`);
    const data = await response.json();

    document.getElementById("M_total_bet").innerText = data.M_total_bet;
    document.getElementById("M_payout").innerText = "PAYOUT: " + data.M_payout;
    document.getElementById("W_total_bet").innerText = data.W_total_bet;
    document.getElementById("W_payout").innerText = "PAYOUT: " + data.W_payout
}

// ── Bet input enable/disable ──────────────────────────────
// Disables/enables all amount buttons, Submit, Reset, and the textarea
// inside #unified-wagers when overall betting is closed.
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

// ── Match button state machine ────────────────────────────
// Tracks whether admin has manually re-opened betting after a CLOSED state.
// Resets whenever the fight moves to a non-CLOSED server state.
let bettingReopened = false;

// Enable/disable a single control button and re-attach its action.
function _setMatchBtn(id, enabled, action) {
    const btn = document.getElementById(id);
    if (!btn) return;
    if (enabled) {
        btn.onclick = action;
        btn.classList.remove('btn-ctrl-disabled');
    } else {
        btn.onclick = null;
        btn.classList.add('btn-ctrl-disabled');
    }
}

/*  State rules
 *  ─────────────────────────────────────────────────────────
 *  IDLE / COMPLETE / CANCELLED  →  only Start Match active
 *  OPEN                         →  Close Betting + Cancel active
 *  CLOSED                       →  Re-Open + Cancel + End Match active
 *  REOPENED (local flag)        →  Close Betting + Cancel + End Match active
 */
function applyMatchState(serverStatus) {
    if (serverStatus !== 'CLOSED') bettingReopened = false;
    const state = (serverStatus === 'CLOSED' && bettingReopened) ? 'REOPENED' : serverStatus;

    const start  = () => openmodal('control_confirmationModal', 'StartMatch');
    const close  = () => openmodal('control_confirmationModal', 'CloseBetting');
    const reopen = () => openmodal('control_confirmationModal', 'ReopenBetting');
    const cancel = () => openmodal('control_confirmationModal', 'CancelMatch');
    const end    = () => openmodal('control_confirmationModal', 'EndMatch');

    switch (state) {
        case 'OPEN':
            _setMatchBtn('startmatchbutton',    false, null);
            _setMatchBtn('closebettingbutton',  true,  close);
            _setMatchBtn('reopenbettingbutton', false, null);
            _setMatchBtn('cancelmatchbutton',   true,  cancel);
            _setMatchBtn('endmatchbutton',      false, null);
            setBetInputsDisabled(false);
            break;
        case 'CLOSED':
            _setMatchBtn('startmatchbutton',    false, null);
            _setMatchBtn('closebettingbutton',  false, null);
            _setMatchBtn('reopenbettingbutton', true,  reopen);
            _setMatchBtn('cancelmatchbutton',   true,  cancel);
            _setMatchBtn('endmatchbutton',      true,  end);
            setBetInputsDisabled(true);
            break;
        case 'REOPENED':
            _setMatchBtn('startmatchbutton',    false, null);
            _setMatchBtn('closebettingbutton',  true,  close);
            _setMatchBtn('reopenbettingbutton', false, null);
            _setMatchBtn('cancelmatchbutton',   true,  cancel);
            _setMatchBtn('endmatchbutton',      true,  end);
            setBetInputsDisabled(false);
            break;
        default: // IDLE / COMPLETE / CANCELLED
            _setMatchBtn('startmatchbutton',    true,  start);
            _setMatchBtn('closebettingbutton',  false, null);
            _setMatchBtn('reopenbettingbutton', false, null);
            _setMatchBtn('cancelmatchbutton',   false, null);
            _setMatchBtn('endmatchbutton',      false, null);
            setBetInputsDisabled(true);
    }
}

function reopenBetting() {
    bettingReopened = true;
    openBetting("BOTH");
    closemodal("control_confirmationModal");
    applyMatchState('CLOSED');
    update_disp_FightStatus("OPEN");
}

// Legacy stubs kept so any remaining call-sites don't throw.
function disableadminButtons() {}
function disableAllButtons() {}
function setStartMatchButton() { applyMatchState('COMPLETE'); }
function setEndMatchButton() {}
function setCloseBettingButton() {}
function setCancelMatchButton() {}

function closeBetting(side){
    console.log("CLOSE BETTING: Closing betting for " +side)
    if (side === "MERON") {
        closeMeron();
    }else if (side === "WALA"){
        closeWala();
    // }else if (side === "BOTH"){
    //     //closed by admin
    //     SuperCloseBetting();
    }
    administratorSocket.send(JSON.stringify({side_status: "CLOSED", side: side}));
}

function SuperCloseBetting() {
    closemodal("control_confirmationModal");
    closeMeron();
    closeWala();
    setBetInputsDisabled(true);
    console.log("Super closing betting for both sides");
    const mopenButton = document.getElementById("M_OpenButton");
    const wopenButton = document.getElementById("W_OpenButton");
    const submitButton = document.getElementById("SubmitButton");

    if (mopenButton) { mopenButton.disabled = true; mopenButton.onclick = null; }
    if (wopenButton) { wopenButton.disabled = true; wopenButton.onclick = null; }
    if (submitButton) submitButton.onclick = () => openmodal('matchclosedmodal', 'null');
}

function SuperOpenBetting() {
    closemodal("control_confirmationModal");
    openMeron();
    openWala();
    setBetInputsDisabled(false);
    console.log("Super Open betting for both sides");
    const submitButton = document.getElementById("SubmitButton");
    const mopenButton = document.getElementById("M_OpenButton");
    const wopenButton = document.getElementById("W_OpenButton");

    if (mopenButton) mopenButton.onclick = () => null;
    if (wopenButton) wopenButton.onclick = () => null;
    if (submitButton) submitButton.onclick = () => check_total();
}

function openBetting(side){
    console.log("Opening betting for " +side)
    if (side === "BOTH"){
        SuperOpenBetting();
        administratorSocket.send(JSON.stringify({side_status: "OPEN", side: side}));
        return
    }

    if (side === "MERON") {
        openMeron();
    }else if (side === "WALA"){
        openWala();
    }
    document.getElementById('adminbetcontrol').style.display = 'none';
    administratorSocket.send(JSON.stringify({side_status: "OPEN", side: side}));
}

function openMeron() {
    const meron_betting_status = document.getElementById("meron-betting-status");
    document.getElementById('M_OpenButton').onclick = () => null; // Disable the Meron open button
    document.getElementById("M_CloseButton").onclick = () => closeBetting("MERON"); // Enable the Meron close button
    meron_betting_status.innerText = "OPEN";
    meron_betting_status.style.backgroundColor = "rgba(7, 248, 2, 0.573)";
    meron_betting_status.style.textAlign = "center";
    console.log("Meron betting opened");
}

function closeMeron() {
    const meron_betting_status = document.getElementById("meron-betting-status");
    document.getElementById('M_OpenButton').onclick = () => openBetting("MERON"); // Enable the Meron open button
    document.getElementById("M_CloseButton").onclick = () => null; // Disable the Meron close button
    meron_betting_status.innerText = "CLOSED"
    meron_betting_status.style.backgroundColor = "rgba(248, 7, 7, 0.573)";
    meron_betting_status.style.textAlign = "center";
    console.log("Meron betting closed");
}

function openWala() {
    const wala_betting_status = document.getElementById("wala-betting-status");
    document.getElementById('W_OpenButton').onclick = () => null; // Disable the Wala open button
    document.getElementById("W_CloseButton").onclick = () => closeBetting("WALA"); // Enable the Wala close button
    wala_betting_status.innerText = "OPEN";
    wala_betting_status.style.backgroundColor = "rgba(7, 248, 2, 0.573)";
    wala_betting_status.style.textAlign = "center";
    console.log("Wala betting opened");
}

function closeWala() {
    const wala_betting_status = document.getElementById("wala-betting-status");
    document.getElementById('W_OpenButton').onclick = () => openBetting("WALA"); // Enable the Wala open button
    document.getElementById("W_CloseButton").onclick = () => null; // Disable the Wala close button
    wala_betting_status.innerText = "CLOSED";
    wala_betting_status.style.backgroundColor = "rgba(248, 7, 7, 0.573)"
    wala_betting_status.style.textAlign = "center"
    console.log("Wala betting closed");
}

function openmodal(modalid, buttonid, side=null, preservePayoutReprint=false) {
    console.log ("open modal");
    console.log ("modal id : " +modalid);
    console.log ("button id : " + buttonid);
    //const modal = document.getElementById(modalid);
    const cm_headermessage = document.getElementById('cm-modal-header');
    const cm_message = document.getElementById('cm-modal-message');
    const cm_yesbutton = document.getElementById('cm-yes-button');
    const cm_nobutton = document.getElementById('cm-no-button');
    
    if (buttonid === 'StartMatch') {
        console.log("Start Match button clicked");
        cm_headermessage.innerHTML = "Start Match";
        cm_message.innerHTML = "Are you sure you want to start a new match?";
        cm_yesbutton.onclick = () => startMatch();
        cm_nobutton.onclick = () => closemodal('control_confirmationModal');
    } else if (buttonid === 'EndMatch') {
        console.log("End Match button clicked");
        cm_headermessage.innerHTML = "End Match";
        cm_message.innerHTML = "Are you sure you want to end the match?";
        cm_yesbutton.onclick = () => openmodal('whowonmodal', 'winner');
        cm_nobutton.onclick = () => closemodal('control_confirmationModal');
    } else if (buttonid === 'CloseBetting'){
        console.log("Close Betting button clicked");
        cm_headermessage.innerHTML = "Close Betting";
        cm_message.innerHTML = "Are you sure you want to close betting for everyone including you?";
        cm_yesbutton.onclick = () => closeMatch();
        cm_nobutton.onclick = () => closemodal('control_confirmationModal');
    } else if (buttonid === 'CancelMatch'){
        console.log("Cancel Betting button clicked");
        cm_headermessage.innerHTML = "Cancel Match";
        cm_message.innerHTML = "Are you sure you want to <strong>CANCEL</strong> the match?";
        cm_yesbutton.onclick = () => cancelMatch();
        cm_nobutton.onclick = () => closemodal('control_confirmationModal');
    } else if (buttonid === 'ReopenBetting') {
        cm_headermessage.innerHTML = "Re-Open Betting";
        cm_message.innerHTML = "Are you sure you want to re-open betting?";
        cm_yesbutton.onclick = () => reopenBetting();
        cm_nobutton.onclick = () => closemodal('control_confirmationModal');
    }

    if (modalid == 'control_confirmationModal') {
        document.getElementById('control_confirmationModal').style.display = 'flex';
    }else if (modalid == 'payoutmodal') {
        document.getElementById(modalid).style.display = 'flex';
        //document.getElementById('payout_barcode').focus();
        document.getElementById('payout_barcode').value='';
        const timeout = 100;
        setTimeout(() => {
            document.getElementById('payout_barcode').focus();
        }, timeout); // Slight delay to ensure the modal is rendered

    } else if (modalid == 'payout_error_modal') {
        if (!preservePayoutReprint) {
            setPayoutReprintOption({ error: buttonid });
        }
        if (buttonid === 'invalid_barcode') {
            document.getElementById('payout_error_message').innerText = "Invalid barcode. Please try again.";
        } else if (buttonid === 'notfound_barcode') {
            document.getElementById('payout_error_message').innerText = "Barcode not found. Please try again.";
        } else if (buttonid === 'alreadypaid_barcode') {
            document.getElementById('payout_error_message').innerText = "This bet has already been paid out.";
        } else if (buttonid === 'web_socket_error'){
            document.getElementById('payout_error_message').innerText = "Network error, try hitting F5";
        } else if (buttonid === 'notfound'){
            document.getElementById('payout_error_message').innerText = "Transaction ID not found.";
        } else if (buttonid === 'alreadypaid'){
            document.getElementById('payout_error_message').innerText = "This transaction has already been paid out.";
        } else if (buttonid === 'wrongside') {
            document.getElementById('payout_error_message').innerText = "The selected side did not win. No payout available.";
        } else if (buttonid === 'exceeds_cash_on_hand') {
            document.getElementById('payout_error_message').innerText = "Insufficient cash on hand to issue this payout.";
        } else if (buttonid === 'cashier_not_found') {
            document.getElementById('payout_error_message').innerText = "The ticket's cashier account could not be found. Payout was blocked.";
        } else if (buttonid === 'teller_offline') {
            document.getElementById('payout_error_message').innerText = "You are tagged as offline. Please report to the admin office.";
        } else if (buttonid === 'matchcomplete') {
            document.getElementById('payout_error_message').innerText = "The match is already complete. Bet cancellation is not allowed.";
        } else if (buttonid === 'matchnotopen') {
            document.getElementById('payout_error_message').innerText = "The Betting is no longer open. Bet cancellation is not allowed.";
        } else if (buttonid === 'notfound') {
            document.getElementById('payout_error_message').innerText = "Transaction ID not found.";
        }
        else {
            document.getElementById('payout_error_message').innerText = "An unknown error occurred.";
        }
        document.getElementById(modalid).style.display = 'flex';
    } else if (modalid == 'cancelbetmodal') {
        document.getElementById(modalid).style.display = 'flex';
        document.getElementById('cancelbet_barcode').value='';
        setTimeout(() => document.getElementById('cancelbet_barcode').focus(), 100);

    } else if (modalid == 'reprintmodal') {
        document.getElementById(modalid).style.display = 'flex';
        document.getElementById('reprint_transaction_id').value = '';
        document.getElementById('reprint_status_message').innerText = '';
        const btn = document.getElementById('reprint_search_button');
        if (btn) { btn.disabled = false; }
        setTimeout(() => {
            document.getElementById('reprint_transaction_id').focus();
        }, 100);

    } else {
        console.log("Opening modal with ID: " + modalid);
        document.getElementById(modalid).style.display = 'flex';
    }
}



// Shared payout response handler — called by both administratorSocket and userSocket.
async function handlePayoutMessage(data) {
    console.log("Payout result received:", data);
    if ("error" in data) {
        console.log("Payout error:", data.error);
        setPayoutReprintOption(data);
        if (data.error === 'wrong_teller') {
            document.getElementById('wrong_teller_name').innerText = data.original_cashier || 'Unknown';
            document.getElementById('wrong_teller_modal').style.display = 'flex';
        } else {
            document.getElementById('payout_error_header').innerText = "Payout Error";
            openmodal('payout_error_modal', data.error, null, true);
        }
    } else if ("transaction_id" in data && "Total_Payout" in data) {
        document.getElementById('payout_success_header').innerText = "Payout request valid!";
        document.getElementById('payout_message1').innerText = "Transaction ID: " + data.transaction_id;
        document.getElementById('payout_message2').innerText = "Total Payout Amount: " + data.Total_Payout;
        document.getElementById('payout_print_modal').style.display = 'flex';

        if (data.print_required !== false) {
            document.getElementById('payout_message3').innerText = "Sending receipt to local printer...";
            const printResult = await printPayoutReceipt(data);
            document.getElementById('payout_message3').innerText = printResult.ok
                ? printResult.message
                : "Receipt print failed: " + printResult.message;
        } else {
            document.getElementById('payout_message3').innerText = "";
        }
    } else if ("side" in data && data.side === "CANCELLED") {
        document.getElementById('payout_success_header').innerText = "Bet Cancelled!";
        document.getElementById('payout_message1').innerText = "Please refund the bettor.";
        document.getElementById('payout_message2').innerText = "Amount to Refund: " + data.wager;
        document.getElementById('payout_print_modal').style.display = 'flex';

        if (data.receipt && data.print_required !== false) {
            document.getElementById('payout_message3').innerText = "Sending cancelled fight refund receipt to local printer...";
            const printResult = await printPayoutReceipt(data);
            document.getElementById('payout_message3').innerText = printResult.ok
                ? "Cancelled fight refund receipt sent to printer."
                : "Cancelled fight refund receipt print failed: " + printResult.message;
        } else {
            document.getElementById('payout_message3').innerText = "";
        }
    } else if ("side" in data && data.side === "DRAW") {
        document.getElementById('payout_success_header').innerText = "Draw - Bet Refund!";
        document.getElementById('payout_message1').innerText = "Fight result is a draw.";
        document.getElementById('payout_message2').innerText = "Amount to Refund: " + data.wager;
        document.getElementById('payout_print_modal').style.display = 'flex';

        if (data.receipt && data.print_required !== false) {
            document.getElementById('payout_message3').innerText = "Sending draw refund receipt to local printer...";
            const printResult = await printPayoutReceipt(data);
            document.getElementById('payout_message3').innerText = printResult.ok
                ? "Draw refund receipt sent to printer."
                : "Draw refund receipt print failed: " + printResult.message;
        } else {
            document.getElementById('payout_message3').innerText = "";
        }
    }
}

async function payout() {
   const barcode = normalizeWagerTransactionId(
       document.getElementById('payout_barcode').value
   );
   closemodal('payoutmodal');
   if (barcode === '' || isNaN(barcode)) {
        openmodal('payout_error_modal', 'invalid_barcode');
   } else {
        // Teller pages use userSocket; admin pages use administratorSocket.
        const socket = (typeof userSocket !== 'undefined' && userSocket.readyState === WebSocket.OPEN)
            ? userSocket
            : administratorSocket;
        console.log("[payout] socket selected:", socket === (typeof userSocket !== 'undefined' ? userSocket : null) ? "userSocket" : "administratorSocket", "readyState:", socket.readyState);
        try {
            socket.send(JSON.stringify({barcode: barcode}));
        }catch (error){
            console.error("websocket send failed: ", error);
            openmodal('payout_error_modal', 'web_socket_error');
        }
   }
}


function closeadminbetting() {
    console.log('Close admin betting');
    const submitButton = document.getElementById('SubmitButton');
    if (submitButton) submitButton.onclick = () => null;
}

function openadminbetting() {
    const submitButton = document.getElementById('SubmitButton');
    if (submitButton) submitButton.onclick = () => check_total();
}

function closemodal(modalid) {
    //const modal = document.getElementById(modalid);
    if (modalid) {
        document.getElementById(modalid).style.display = 'none';
        console.log("Modal with ID " + modalid + " closed.");
    } else {
        console.error("Modal with ID " + modalid + " not found.");
    }
}

function startMatch(){
    console.log("Starting match...");
    try {
        administratorSocket.send(JSON.stringify({fight_status: "START"}));
    }catch (error){
        console.error("websocket send failed: ", error)
        return
    }
    applyMatchState('OPEN');
    get_fightstatus();
    openBetting("BOTH");
    openadminbetting();
    resetTotal();
    update_disp_Pot();
    closemodal("control_confirmationModal");
    update_trends();
}



function closeMatch(){
    console.log("Closing match");
    try {
        administratorSocket.send(JSON.stringify({ fight_status: "CLOSED" }));
    }catch (error){
        console.error("websocket send failed: ", error)
        return
    }
    bettingReopened = false;
    applyMatchState('CLOSED');
    get_fightstatus();
    SuperCloseBetting();
    closemodal("control_confirmationModal");
}

function cancelMatch(){
    administratorSocket.send(JSON.stringify({fight_status: "CANCEL"}));
    applyMatchState('CANCELLED');
    get_fightstatus();
    closemodal("control_confirmationModal");
}

function endMatch(winner){
    console.log("Ending Match");
    administratorSocket.send(JSON.stringify({fight_status: "END", Winner: winner}));
    applyMatchState('COMPLETE');
    get_fightstatus();
    update_trends();
    closemodal("control_confirmationModal");
    closemodal("whowonmodal")
}

async function get_status_for_display(fight_num=null, fight_status=null, m_status=null, w_status=null) {
    // When admin has re-opened betting, treat the display as OPEN even though
    // the server still records the fight as CLOSED.
    const effectiveStatus = (fight_status === 'CLOSED' && bettingReopened) ? 'OPEN' : fight_status;

    update_disp_FightStatus(effectiveStatus);
    update_disp_Fightnum(fight_num);
    applyMatchState(fight_status);

    if (effectiveStatus === "OPEN") {
        if (m_status === "OPEN" || bettingReopened) {
            openMeron();
        } else {
            closeMeron();
        }
        if (w_status === "OPEN" || bettingReopened) {
            openWala();
        } else {
            closeWala();
        }
    } else {
        closeMeron();
        closeWala();
    }
}

async function get_fightstatus(){
    const response = await fetch(`/get_fight_status_view/`);
    const data = await response.json();
    console.log("Fight status data received: ", data);

    const fight_num    = data.fightnum;
    const fight_status = data.overall_status;
    const m_status     = data.meron_status;
    const w_status     = data.wala_status;
    const event_active = data.event_active;

    applyEventState(event_active);

    if (event_active) {
        get_status_for_display(fight_num, fight_status, m_status, w_status);
    } else {
        applyMatchState('IDLE');
    }
}

function applyEventState(event_active) {
    const startLink = document.querySelector('.start-event-action');
    const endLink   = document.querySelector('.end-event-action');

    if (event_active) {
        // Event running: disable Start Event, enable End Event
        if (startLink) {
            startLink.classList.add('nav-event-disabled');
            startLink.onclick = e => e.preventDefault();
        }
        if (endLink) {
            endLink.classList.remove('nav-event-disabled');
            endLink.onclick = e => { e.preventDefault(); openEndEventModal(); };
        }
    } else {
        // No active event: enable Start Event, disable End Event,
        // and freeze every other operational button.
        if (startLink) {
            startLink.classList.remove('nav-event-disabled');
            startLink.onclick = e => { e.preventDefault(); openStartEventModal(); };
        }
        if (endLink) {
            endLink.classList.add('nav-event-disabled');
            endLink.onclick = e => e.preventDefault();
        }

        document.querySelectorAll('.button:not(#tellers_button)').forEach(btn => {
            btn.onclick = null;
            btn.classList.add('btn-event-disabled');
        });
        const tellersButton = document.getElementById('tellers_button');
        if (tellersButton) {
            tellersButton.classList.remove('btn-event-disabled');
        }
    }
}



function openadminbetcontrolModal(side, action) {
    const modalmessage = document.getElementById("modal-message");
    const modalbutton = document.getElementById("confirmopen");

    modalmessage.innerHTML = "Are you sure you want to " +action +" Betting for <strong>" + side + "</strong>?";
    if (action === 'Open') {
        modalbutton.onclick = () => openBetting(side);
    }else if (action === 'Close') {
        modalbutton.onclick = () => closeBetting(side);
    } else {
        console.error("Invalid action specified:", action);
        return;
    }
    document.getElementById('adminbetcontrol').style.display = 'flex';
}

function cancelbet(){
    console.log("Cancelling bet...");
    const barcode = normalizeWagerTransactionId(
        document.getElementById('cancelbet_barcode').value
    );
    if (barcode === '' || isNaN(barcode)) {
        openmodal('payout_error_modal', 'invalid_barcode');
    } else {
        // Teller pages use userSocket; admin pages use administratorSocket.
        const socket = (typeof userSocket !== 'undefined' && userSocket.readyState === WebSocket.OPEN)
            ? userSocket
            : administratorSocket;
        console.log("[cancelbet] socket selected:", socket === (typeof userSocket !== 'undefined' ? userSocket : null) ? "userSocket" : "administratorSocket", "readyState:", socket.readyState);
        try {
            socket.send(JSON.stringify({cancel_barcode: barcode}));
        } catch (error) {
            console.error("websocket send failed: ", error);
            openmodal('payout_error_modal', 'web_socket_error');
        }
        closemodal('cancelbetmodal');
    }
}

async function reprintReceipt() {
    const transactionId = normalizeWagerTransactionId(
        document.getElementById('reprint_transaction_id').value
    );
    const statusMsg = document.getElementById('reprint_status_message');
    const searchBtn = document.getElementById('reprint_search_button');

    if (!transactionId) {
        statusMsg.innerText = 'Please enter a Transaction ID.';
        return;
    }

    statusMsg.innerText = 'Searching...';
    searchBtn.disabled = true;

    const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]')?.value || '';

    try {
        const response = await fetch('/reprint_wager/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded',
                'X-CSRFToken': csrfToken,
                'X-Requested-With': 'XMLHttpRequest',
            },
            body: `transaction_id=${encodeURIComponent(transactionId)}`,
        });

        const data = await response.json();

        if (!data.ok) {
            closemodal('reprintmodal');
            document.getElementById('payout_error_header').innerText = 'Reprint Error';
            if (data.error === 'notfound') {
                document.getElementById('payout_error_message').innerText = 'Transaction ID not found. Please check and try again.';
            } else {
                document.getElementById('payout_error_message').innerText = 'An error occurred. Please try again.';
            }
            document.getElementById('payout_error_modal').style.display = 'flex';
            return;
        }

        statusMsg.innerText = 'Transaction found. Sending to printer...';

        let printResult;
        if (data.print_required !== false) {
            printResult = await printWagerReceipt(data.receipt);
        } else {
            printResult = { ok: true, message: 'Printing is disabled.' };
        }

        closemodal('reprintmodal');
        document.getElementById('payout_success_header').innerText = 'Reprint Receipt';
        document.getElementById('payout_message1').innerText = 'Transaction ID: ' + transactionId;
        document.getElementById('payout_message2').innerText = printResult.ok
            ? 'Receipt sent to printer successfully.'
            : 'Print failed: ' + printResult.message;
        document.getElementById('payout_message3').innerText = '';
        document.getElementById('payout_print_modal').style.display = 'flex';

    } catch (error) {
        console.error('Reprint error:', error);
        closemodal('reprintmodal');
        document.getElementById('payout_error_header').innerText = 'Reprint Error';
        document.getElementById('payout_error_message').innerText = 'Network error. Please try again.';
        document.getElementById('payout_error_modal').style.display = 'flex';
    } finally {
        searchBtn.disabled = false;
        statusMsg.innerText = '';
    }
}
async function update_trends() {
    const trends_response = await fetch(`/get_fight_results_view/`);
    const trend_data = await trends_response.json();

    const trendsList = document.getElementById("trends");
    trendsList.innerHTML = '';


    trend_data.forEach(match => {
        const row = document.createElement("li");
        row.className = "sidebar-row";

        let formattedOdds = '';
        if (match.side === 'DRAW') {
            formattedOdds = 'DRAW';
        } else if (match.odds === 'Llamado') {
            formattedOdds = 'L';
        } else if (match.odds === 'Dehado') {
            formattedOdds = 'D';
        } else {
            formattedOdds = "----";
        }

        const fightDiv = document.createElement("div");
        fightDiv.className = "fightnum";
        fightDiv.textContent = match.fightnum;

        const oddsDiv = document.createElement("div");
        oddsDiv.className = "odds";
        oddsDiv.textContent = formattedOdds;

        // Color coding based on winner
        const colors = {
            MERON: "linear-gradient(to bottom, red, black)",
            WALA:  "linear-gradient(to bottom, blue, black)",
            DRAW:  "linear-gradient(to bottom, #c8a800, black)",
        };
        oddsDiv.style.background = colors[match.side] || "linear-gradient(to bottom, gray, black)";
        oddsDiv.style.color = "white";

        row.appendChild(fightDiv);
        row.appendChild(oddsDiv);
        trendsList.appendChild(row);
    });
}
