const userSocket = new WebSocket("ws://localhost:8000/ws/user/");

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

    // Enable/disable the button based on admin toggle
    if ("meron_status" in data && "wala_status" in data) {
        let side = data.side;
        let status = data.side_status;
        let over_all_status = data.overall_status;
        console.log("Changing status of ", side + " to " + status);
        updateOnClick(status, side);
        openbettingdisabledModal();  // Show modal when buttons are disabled
        update_disp_FightStatus(over_all_status);
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

function updateOnClick(ButtonStatus, side) {
    const headertext = document.getElementById("modal-header-text");
    const modalmessage = document.getElementById("modal-message");
    
    if (ButtonStatus === 'CLOSED'){
        headertext.innerHTML = "Betting is currently disabled for <strong>" + side + "</strong>.";
        modalmessage.innerHTML = "DO NOT Accept bets for <strong>" + side + "</strong> until the betting is enabled again.";
        if (side === "MERON") {
            const status_text = document.getElementById("meron-betting-status");
            const SubmitButton = document.getElementById("Musersubmit");

            status_text.innerHTML = "CLOSED";
            status_text.style.backgroundColor = "rgba(248, 7, 7, 0.573)"; // Change background color to red
            SubmitButton.onclick = () => openbettingdisabledModal();  // Show modal when disabled
        }else if (side === "WALA") {
            const status_text = document.getElementById("wala-betting-status");
            const SubmitButton = document.getElementById("Wusersubmit");

            status_text.innerHTML = "CLOSED";
            status_text.style.backgroundColor = "rgba(248, 7, 7, 0.573)"; // Change background color to red
            SubmitButton.onclick = () => openbettingdisabledModal();  // Show modal when disabled
        }
    }else if (ButtonStatus === 'OPEN') {
        headertext.innerHTML = "Betting is enabled for <strong>" + side + "</strong>.";
        modalmessage.innerHTML = "You can now accept bets for <strong>" + side + "</strong>.";  
        if (side === "MERON") {
            const status_text = document.getElementById("meron-betting-status");
            const SubmitButton = document.getElementById("Musersubmit");

            status_text.innerHTML = "OPEN";
            status_text.style.backgroundColor = "rgba(7, 248, 2, 0.573)"; // Change background color to green
            SubmitButton.onclick = () => check_total("MERON");  // Go back to normal behavior
        }else if (side === "WALA") {
            const status_text = document.getElementById("wala-betting-status");
            const SubmitButton = document.getElementById("Wusersubmit");
            
            status_text.innerHTML = "OPEN";
            status_text.style.backgroundColor = "rgba(7, 248, 2, 0.573)"; // Change background color to green
            SubmitButton.onclick = () => check_total("WALA");  // Go back to normal behavior
        }else {
            console.error("Invalid side specified:", side);
            return;
        }
    }   
    resetTotal();  // Reset totals whenever buttons are enabled or disabled
};


function openbettingdisabledModal() {
    document.getElementById('bettingdisabled').style.display = 'flex';
    resetTotal();
};

function closebettingdisabledModal() {
    document.getElementById('bettingdisabled').style.display = 'none';
    resetTotal();  // Reset totals when modal is closed
};

function openMeronUser(){
    console.log ("openMeron user)")
    let mbettingstatus = document.getElementById("meron-betting-status");
    let msubmitButton = document.getElementById("Musersubmit");
    
    mbettingstatus.innerHTML = "OPEN";
    mbettingstatus.style.backgroundColor = "rgba(7, 248, 2, 0.573)"; // Change background color to green
    mbettingstatus.style.textAlign = "center";
    msubmitButton.onclick = () => check_total("MERON");

};

function openWalaUser(){
    let wbettingstatus = document.getElementById("wala-betting-status");
    let wsubmitButton = document.getElementById("Wusersubmit");
    
    wbettingstatus.innerHTML = "OPEN";
    wbettingstatus.style.backgroundColor = "rgba(7, 248, 2, 0.573)"; // Change background color to green
    wbettingstatus.style.textAlign = "center";
    wsubmitButton.onclick = () => check_total("WALA");
};

function closeMeronUser(){
    console.log ("close meron");
    let mbettingstatus = document.getElementById("meron-betting-status");
    let msubmitButton = document.getElementById("Musersubmit");
    let modalheader = document.getElementById("modal-header-text")
    let modalmessage = document.getElementById("modal-message");
    mbettingstatus.innerHTML = "CLOSED";
    mbettingstatus.style.backgroundColor = "rgba(248, 7, 7, 0.573)";  // Change background color to red
    mbettingstatus.style.textAlign = "center";
    modalheader.innerHTML = "Betting is currently disabled for <strong>MERON</strong>.";
    modalmessage.innerHTML = "DO NOT Accept bets for <strong>MERON</strong> until the betting is enabled again.";
    msubmitButton.onclick = () => openbettingdisabledModal();
};

function closeWalaUser(){
    let wbettingstatus = document.getElementById("wala-betting-status");
    let wsubmitButton = document.getElementById("Wusersubmit");
    let modalheader = document.getElementById("modal-header-text")
    let modalmessage = document.getElementById("modal-message");
    wbettingstatus.innerHTML = "CLOSED";
    wbettingstatus.style.backgroundColor = "rgba(248, 7, 7, 0.573)";  // Change background color to red
    wbettingstatus.style.textAlign = "center";
    modalheader.innerHTML = "Betting is currently disabled for <strong>MERON</strong>.";
    modalmessage.innerHTML = "DO NOT Accept bets for <strong>MERON</strong> until the betting is enabled again.";
    wsubmitButton.onclick = () => openbettingdisabledModal();
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
        if (m_status == "OPEN"){
            //console.log ("Meron open");
            openMeronUser();
        }else if (m_status = "CLOSED"){
            console.log ("Meron close");
            closeMeronUser();
        }

        if(w_status == "OPEN"){
            //console.log ("wala open");
            openWalaUser();
        }else if (w_status == "CLOSED"){
            //console.log ("wala close");
            closeWalaUser();
        }
    }else {
        closeMeronUser();
        closeWalaUser();
        const msubmitButton = document.getElementById("Musersubmit");
        const wsubmitButton = document.getElementById("Wusersubmit");
        msubmitButton.onclick = () => openmodal('matchclosedmodal','null'); 
        wsubmitButton.onclick = () => openmodal('matchclosedmodal','null'); 
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

        const M_OpenButtonuserSubmitButton = document.getElementById("Musersubmit");
        const W_OpenButtonuserSubmitButton = document.getElementById("Wusersubmit");

        if (data.mstate == 'Open'){
            mbettingstatus.innerHTML = "OPEN";
            mbettingstatus.style.backgroundColor = "rgba(7, 248, 2, 0.573)";  // Change background color to green
            M_OpenButtonuserSubmitButton.onclick = () => check_total("MERON");  // Normal behavior for MERON
        }else if (data.mstate == 'Close') {
            mbettingstatus.innerHTML = "CLOSED";
            mbettingstatus.style.backgroundColor = "rgba(248, 7, 7, 0.573)";  // Change background color to red
            headertext.innerHTML = "Betting is currently disabled for <strong>MERON</strong>.";
            modalmessage.innerHTML = "DO NOT Accept bets for <strong>MERON</strong> until the betting is enabled again.";
            if (!sessionStorage.getItem("buttonStateChecked")) {
                openbettingdisabledModal();  // Opens modal if betting is disabled
                sessionStorage.setItem("buttonStateChecked", "true");
            }
            M_OpenButtonuserSubmitButton.onclick = openbettingdisabledModal;  // Opens modal if betting is disabled
        }
        
        if (data.wstate == 'Open'){
            wbettingstatus.innerHTML = "OPEN";
            wbettingstatus.style.backgroundColor = "rgba(7, 248, 2, 0.573)";  // Change background color to green
            W_OpenButtonuserSubmitButton.onclick = () => check_total("WALA");  // Normal behavior for WALA
        }
        else if (data.wstate == 'Close') {
            wbettingstatus.innerHTML = "CLOSED";
            wbettingstatus.style.backgroundColor = "rgba(248, 7, 7, 0.573)";  // Change background color to red
            headertext.innerHTML = "Betting is currently disabled for <strong>WALA</strong>.";
            modalmessage.innerHTML = "DO NOT Accept bets for <strong>WALA</strong> until the betting is enabled again.";
            //openbettingdisabledModal();  // Opens modal if betting is disabled
            if (!sessionStorage.getItem("buttonStateChecked")) {
                openbettingdisabledModal();  // Opens modal if betting is disabled
                sessionStorage.setItem("buttonStateChecked", "true");
            }
            W_OpenButtonuserSubmitButton.onclick = openbettingdisabledModal;  // Opens modal if betting is disabled
        }

        if (data.wstate == 'Close' && data.mstate == 'Close'){
            headertext.innerText = "Betting is currently CLOSED!"
            modalmessage.innerText = "Please wait for the admin to open betting"
        }
        console.log("Button states updated successfully.");

    } catch (error) {
        console.error("Error fetching button state:", error);
    }
};

// Call this function when the page loads
document.addEventListener("DOMContentLoaded", () => {
    console.log("Fetching button states on page load...");
    //fetchButtonState();
    get_fightstatus();  // Fetch fight status on page load
});
// window.onload = function() {
//     console.log("Fetching button states on page load...");
//     fetchButtonState();
// }