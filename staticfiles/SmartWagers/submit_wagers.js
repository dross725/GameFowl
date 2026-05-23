let meron_total = 0;
let wala_total = 0;
let wager_value = 0;
let wager_id = '';

function check_total(side){
    /* Get the value from what is in the textarea not the total*/
    if (side == 'WALA'){
        const val = document.getElementById('wala_textinput')

        if (val.value == 0 || val.value == '' || isNaN(val.value)){
            wala_reset();
            openInvalidTotalModal();
        }else if (val.value != wala_total){
            openConfirmationModal(val.value, side);
        }else if (val.value == wala_total){
            openConfirmationModal(val.value, side);
        }

    }else if (side == 'MERON'){
        const val = document.getElementById('meron_textinput')

        if (val.value == 0 || val.value == '' || isNaN(val.value)){
            wala_reset();
            openInvalidTotalModal();
        }else if (val.value != meron_total){
            openConfirmationModal(val.value, side);
        }else if (val.value == meron_total){
            openConfirmationModal(val.value, side);
        }
    } else {
        resetTotal();
        openInvalidTotalModal();
    }
}

function wala_addValue(value) {
    /*make sure to clear other side to avoid stacking*/
    meron_reset();
    wala_total += value;
    const walatextarea = document.getElementById('wala_textinput');
    walatextarea.value = '';
    walatextarea.value += wala_total; 
}

function wala_reset() {
    wala_total = 0;
    const walatextarea = document.getElementById('wala_textinput');
    walatextarea.value = '0';
}

function meron_addValue(value) {
    /*make sure to clear other side to avoid stacking*/
    wala_reset();
    meron_total += value;
    const textarea = document.getElementById('meron_textinput');
    textarea.value = ''; 
    textarea.value += meron_total; 
}

function meron_reset() {
    meron_total = 0;
    const textarea = document.getElementById('meron_textinput');
    textarea.value = '0';
}

function resetTotal() {
    meron_reset();
    wala_reset();
    document.getElementById('wager_value').value = '';
    document.getElementById('wager_id').value = '';
    // localStorage.clear();
    // sessionStorage.clear();
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

    document.getElementById('confirmationModal').style.display = 'none'; // Hide the modal
    resetTotal(); // Reset total when modal is closed
}

function openInvalidTotalModal() {
    document.getElementById('invalidtotalModal').style.display = 'flex'; // Show the modal
}

function closeInvalidTotalModal() {
    document.getElementById('invalidtotalModal').style.display = 'none'; // Hide the modal
    resetTotal(); // Reset total when modal is closed
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
    return Boolean(document.getElementById("Musersubmit") || document.getElementById("Wusersubmit"));
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

    const form = document.getElementById('submitwagerForm');
    const submitButton = document.getElementById('submitvalue');
    if (submitButton) {
        submitButton.disabled = true;
        submitButton.innerText = "Printing...";
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