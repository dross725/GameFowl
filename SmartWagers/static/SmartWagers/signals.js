const pageType = window.location.pathname.split("/").filter(Boolean).pop() || "index";
const signalsWebsocketProtocol = window.location.protocol === "https:" ? "wss" : "ws";
const socket = new WebSocket(`${signalsWebsocketProtocol}://${window.location.host}/ws/${pageType}/`); // Open correct WebSocket

socket.onmessage = (event) => {
    const data = JSON.parse(event.data);
    console.log("signals.js received:", data);

    if (data.refresh_trends) {
        update_trends();
    }

    if ("fight_status" in data) {
        // Apply status from the broadcast immediately when present.
        if ("overall_status" in data || "meron_status" in data) {
            if (data.fightnum != null) updateFightnum(data.fightnum);
            if (data.overall_status) update_disp_FightStatus(data.overall_status);
            if (data.meron_status) update_side_status("MERON", normalizeDisplayStatus(data.meron_status));
            if (data.wala_status) update_side_status("WALA", normalizeDisplayStatus(data.wala_status));
        } else {
            get_fightstatus();
        }
        if (data.fight_status === "END" || data.fight_status === "CANCEL") {
            update_trends();
        } else if (data.fight_status === "event_changed") {
            get_fightstatus();
        }
    } else if ("mtotal" in data && "wtotal" in data) {
        document.getElementById("M_total_bet").innerText = data.mtotal;
        document.getElementById("M_payout").innerText = "PAYOUT: " + data.mpayout;
        document.getElementById("W_total_bet").innerText = data.wtotal;
        document.getElementById("W_payout").innerText = "PAYOUT: " + data.wpayout;
        if (data.fightnum != null) updateFightnum(data.fightnum);
    } else if ("side" in data && "side_status" in data) {
        const side   = data.side;
        const status = normalizeDisplayStatus(data.side_status);
        if (side === "BOTH") {
            update_side_status("MERON", status);
            update_side_status("WALA",  status);
        } else {
            update_side_status(side, status);
        }
        if (data.overall_status) update_disp_FightStatus(data.overall_status);
        if (data.fightnum != null) updateFightnum(data.fightnum);
    }

    updateStatus("Connected");
};

function normalizeDisplayStatus(status) {
    return status === "CLOSE" ? "CLOSED" : status;
}

socket.onopen = () => {
    console.log("WebSocket connected!");
    socket.send(JSON.stringify({ update: true }));
    console.log("Initial data request sent.");
    updateStatus("Connected");
    document.getElementById("ws_status").innerText = "Status: Connected";
    document.getElementById("ws_status").style.color = "blue";
    document.getElementById("ws_status").style.fontWeight = "bold";     
};

socket.onerror = (error) => {
    console.error("WebSocket Error:", error);
};

socket.onclose = () => {
    console.log("WebSocket disconnected!");
    updateStatus("Disconnected");
    document.getElementById("ws_status").innerText = "Status: Disconnected";

};

function updateStatus(status) {
    document.getElementById("ws_status").innerText = "Status: " + status;
};

function updateFightnum(fightnum){
    document.getElementById("currentmatchnum").innerText = fightnum;
}

function update_disp_FightStatus(status) {
    document.getElementById("currentmatchstatus").innerText = "Status: " + status;
    document.getElementById("currentmatchstatus").style.color = status === "OPEN" ? "green" : "red";
    document.getElementById("currentmatchstatus").style.fontWeight = "bold";
}

function update_side_status(side, side_status) {
    const elementId = side === "MERON" ? "meron-betting-status" : "wala-betting-status";
    const betting_status = document.getElementById(elementId);
    if (!betting_status) return;

    betting_status.textContent = side_status;
    betting_status.classList.remove("status-open", "status-closed");
    betting_status.classList.add(side_status === "OPEN" ? "status-open" : "status-closed");
}

async function update_trends() {
    const response = await fetch('/get_fight_results_view/');
    if (!response.ok) {
        throw new Error(`Fight results request failed with HTTP ${response.status}`);
    }
    const trendData = await response.json();
    const trendsList = document.getElementById('trends');
    if (!trendsList) return;
    trendsList.innerHTML = '';

    trendData.forEach((match) => {
        const row = document.createElement('li');
        row.className = 'sidebar-row';

        const fightDiv = document.createElement('div');
        fightDiv.className = 'fightnum';
        fightDiv.textContent = match.fightnum;

        const oddsDiv = document.createElement('div');
        oddsDiv.className = 'odds';
        oddsDiv.textContent = match.side === 'DRAW'
            ? 'DRAW'
            : match.odds === 'Llamado'
                ? 'L'
                : match.odds === 'Dehado'
                    ? 'D'
                    : '----';
        const colors = {
            MERON: 'linear-gradient(to bottom, red, black)',
            WALA: 'linear-gradient(to bottom, blue, black)',
            DRAW: 'linear-gradient(to bottom, #c8a800, black)',
        };
        oddsDiv.style.background = colors[match.side]
            || 'linear-gradient(to bottom, gray, black)';
        oddsDiv.style.color = 'white';

        row.appendChild(fightDiv);
        row.appendChild(oddsDiv);
        trendsList.appendChild(row);
    });
}

async function get_fightstatus(){
    const response = await fetch(`/get_fight_status_view/`);
    console.log('response: ' +response);
    const data = await response.json();
    console.log("Fight status data received: ", data);

    let fight_num = data.fightnum;
    let fight_status = data.overall_status;
    let m_status = normalizeDisplayStatus(data.meron_status);
    let w_status = normalizeDisplayStatus(data.wala_status);

    updateFightnum(fight_num);
    update_disp_FightStatus(fight_status);
    update_side_status("MERON", m_status);
    update_side_status("WALA", w_status);
}

document.addEventListener("DOMContentLoaded", () => {
    get_fightstatus();
    update_trends();
    const errModal = document.getElementById("payout_error_modal");
    const printModal = document.getElementById("payout_print_modal");
    if (errModal)   errModal.style.display   = "none";
    if (printModal) printModal.style.display = "none";
});