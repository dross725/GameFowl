const userWebsocketProtocol = window.location.protocol === "https:" ? "wss" : "ws";
const userSocket = new WebSocket(`${userWebsocketProtocol}://${window.location.host}/ws/user/`);

userSocket.onmessage = (event) => {
    const data = JSON.parse(event.data);
    console.log("Data received from server: ", data);
    console.log("This is the user.js file");

    // Update left and right values
    if ("mtotal" in data && "wtotal" in data) {
        document.getElementById("M_total_bet").innerText = data.mtotal;
        document.getElementById("M_payout").innerText = data.mpayout;
        document.getElementById("W_total_bet").innerText = data.wtotal;
        document.getElementById("W_payout").innerText = data.wpayout;
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
            openbettingdisabledModal();
        }
    }

    if ("meron_status" in data && "wala_status" in data) {
        updateUserBettingStatus(data.meron_status, "MERON");
        updateUserBettingStatus(data.wala_status, "WALA");
        updateFightnum(data.fightnum);
    }

    if ("fight_status" in data) {
        get_fightstatus();
    }

    if ("overall_status" in data) {
        update_disp_FightStatus(data.overall_status);
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

function updateFightnum(fightnum){
    document.getElementById("currentmatchnum").innerText = "FIGHT # "+fightnum;
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
    updateUserSubmitButton();
}

function openWalaUser() {
    walaBettingOpen = true;
    setBettingStatusText(document.getElementById("wala-betting-status"), "OPEN");
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
    updateUserSubmitButton();
}

function closeWalaUser() {
    walaBettingOpen = false;
    setBettingStatusText(document.getElementById("wala-betting-status"), "CLOSED");
    const modalheader = document.getElementById("modal-header-text");
    const modalmessage = document.getElementById("modal-message");
    if (modalheader) modalheader.innerHTML = "Betting is currently disabled for <strong>WALA</strong>.";
    if (modalmessage) modalmessage.innerHTML = "DO NOT Accept bets for <strong>WALA</strong> until the betting is enabled again.";
    updateUserSubmitButton();
}

async function get_fightstatus(){
    const response = await fetch(`/get_fight_status_view/`);
    console.log('response: ' +response);
    const data = await response.json();
    console.log("Fight status data received: ", data);

    let fight_num = data.fightnum;
    let fight_status = data.overall_status;
    let m_status = data.meron_status;
    let w_status = data.wala_status;

    console.log("Fight status: ", fight_status);

    if (fight_status == "OPEN"){
        if (normalizeBettingStatus(m_status) == "OPEN"){
            //console.log ("Meron open");
            openMeronUser();
        }else if (normalizeBettingStatus(m_status) == "CLOSED"){
            console.log ("Meron close");
            closeMeronUser();
        }

        if(normalizeBettingStatus(w_status) == "OPEN"){
            //console.log ("wala open");
            openWalaUser();
        }else if (normalizeBettingStatus(w_status) == "CLOSED"){
            //console.log ("wala close");
            closeWalaUser();
        }
    } else {
        closeMeronUser();
        closeWalaUser();
        const submitButton = document.getElementById("Usersubmit");
        if (submitButton) submitButton.onclick = () => openmodal('matchclosedmodal', 'null');
    }
    update_disp_FightStatus(fight_status);
};

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
});
// window.onload = function() {
//     console.log("Fetching button states on page load...");
//     fetchButtonState();
// }