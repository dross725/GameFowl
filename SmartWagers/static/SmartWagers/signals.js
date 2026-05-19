const pageType = window.location.pathname.split("/").pop(); // Get page type from URL
const socket = new WebSocket(`ws://localhost:8000/ws/${pageType}/`); // Open correct WebSocket

socket.onmessage = (event) => {
    console.log("This is the signals.js file");
    const data = JSON.parse(event.data);
    

    console.log("Data received:", data);

    if ("fight_status" in data) {
        let status = data.fight_status;
        console.log("Fight status received:", fight_status);
        document.getElementById("currentmatchstatus").innerText = "Status: " + status;
        document.getElementById("currentmatchstatus").style.color = status === "OPEN" ? "green" : "red";
        document.getElementById("currentmatchstatus").style.fontWeight = "bold";
    } else if ("mtotal" in data && "wtotal" in data) {
        document.getElementById("M_total_bet").innerText = data.mtotal;
        document.getElementById("M_payout").innerText = data.mpayout;
        document.getElementById("W_total_bet").innerText = data.wtotal;
        document.getElementById("W_payout").innerText = data.wpayout;
    } else if ("side" in data && "side_status" in data){
        update_side_status (data.side, data.side_status)
    }
    updateStatus("Connected");
    updateFightnum(data.fightnum)
    console.log("This is the signals.js file");
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
    document.getElementById("payout_error_modal").style.display = "none"; // Hide the modal on page load
    document.getElementById("payout_print_modal").style.display = "none"; // Hide the modal on page load    
})