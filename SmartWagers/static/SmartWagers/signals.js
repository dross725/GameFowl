const pageType = window.location.pathname.split("/").pop(); // Get page type from URL
const signalsWebsocketProtocol = window.location.protocol === "https:" ? "wss" : "ws";
const socket = new WebSocket(`${signalsWebsocketProtocol}://${window.location.host}/ws/${pageType}/`); // Open correct WebSocket

socket.onmessage = (event) => {
    const data = JSON.parse(event.data);
    console.log("signals.js received:", data);

    if ("fight_status" in data) {
        // Fetch real status from server so display shows proper values
        get_fightstatus();
        // Refresh trends sidebar whenever a fight completes or is cancelled
        if (data.fight_status === "END" || data.fight_status === "CANCEL") {
            update_trends();
        }
    } else if ("mtotal" in data && "wtotal" in data) {
        document.getElementById("M_total_bet").innerText = data.mtotal;
        document.getElementById("M_payout").innerText = data.mpayout;
        document.getElementById("W_total_bet").innerText = data.wtotal;
        document.getElementById("W_payout").innerText = data.wpayout;
        if (data.fightnum != null) updateFightnum(data.fightnum);
    } else if ("side" in data && "side_status" in data) {
        const side   = data.side;
        const status = data.side_status;
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
    document.getElementById("currentmatchnum").innerText = "FIGHT # "+fightnum;
}

function update_disp_FightStatus(status) {
    document.getElementById("currentmatchstatus").innerText = "Status: " + status;
    document.getElementById("currentmatchstatus").style.color = status === "OPEN" ? "green" : "red";
    document.getElementById("currentmatchstatus").style.fontWeight = "bold";
}

function update_side_status(side, side_status) {
    console.log ("Updating side status! ")

    if (side == "MERON"){
        const meron_betting_status = document.getElementById("meron-betting-status");
        meron_betting_status.innerText = side_status; 
        meron_betting_status.style.backgroundColor = side_status === "OPEN" ? "rgba(7, 248, 2, 0.573)" : "rgba(248, 7, 7, 0.573)";
        meron_betting_status.style.textAlign = "center";
        meron_betting_status.style.fontSize = "30px";
        meron_betting_status.style.fontWeight = "bold";
    } else if (side == "WALA"){
        const wala_betting_status = document.getElementById("wala-betting-status");
        wala_betting_status.innerText = side_status;
        wala_betting_status.style.backgroundColor = side_status === "OPEN" ? "rgba(7, 248, 2, 0.573)" : "rgba(248, 7, 7, 0.573)";
        wala_betting_status.style.textAlign = "center";
        wala_betting_status.style.fontSize = "30px";
        wala_betting_status.style.fontWeight = "bold";
    }
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