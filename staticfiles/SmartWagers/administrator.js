const administratorSocket = new WebSocket("ws://localhost:8000/ws/administrator/");
//new WebSocket(`ws://${window.location.host}/ws/administrator`);

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

administratorSocket.onmessage = (event) => {
    const data = JSON.parse(event.data);
    console.log("Data received on message:", data);

    if ("mtotal" in data && "wtotal" in data) {
        document.getElementById("M_total_bet").innerText = data.mtotal;
        document.getElementById("M_payout").innerText = data.mpayout;
        document.getElementById("W_total_bet").innerText = data.wtotal;
        document.getElementById("W_payout").innerText = data.wpayout;
        document.getElementById("ws_status").innerText = "Status: Connected";

    }else if ("payout" in data) {
        console.log("Payout result received:", data.payout_result);
        if ("error" in data){
            console.log("Payout error:", data.error);
            document.getElementById('payout_error_header').innerText = "Payout Error";  
            openmodal('payout_error_modal', data.error);

        } else if ("transaction_id" in data && "Total_Payout" in data) {
            document.getElementById('payout_success_header').innerText = "Payout request valid!";
            document.getElementById('payout_message1').innerText = "Transaction ID: " + data.transaction_id;
            document.getElementById('payout_message2').innerText = "Total Payout Amount: " + data.Total_Payout;
            document.getElementById('payout_message3').innerText = "";
            document.getElementById('payout_print_modal').style.display = 'flex';
        } else if ("side" in data && data.side === "CANCELLED") {
            document.getElementById('payout_success_header').innerText = "Bet Cancelled!";
            document.getElementById('payout_message1').innerText = "Please refund the bettor.";
            document.getElementById('payout_message2').innerText = "Amount to Refund: " + data.wager;
            document.getElementById('payout_message3').innerText = "";
            document.getElementById('payout_print_modal').style.display = 'flex';
        }
    }else if ("cancel_bet" in data){
        console.log("Cancel bet result received:", data.cancel_bet);
        console.log("Cancel bet data:", data);
        if ("error" in data){
            console.log("Cancel bet error:", data.error);
            document.getElementById('payout_error_header').innerText = "Cancel Bet Error";  
            openmodal('payout_error_modal', data.error);
        } else if ("transaction_id" in data && "amount" in data) {
            console.log("Cancel bet success:", data);
            document.getElementById('payout_success_header').innerText = "Cancel bet request valid!";
            document.getElementById('payout_message1').innerText = "Transaction ID: " + data.transaction_id;
            document.getElementById('payout_message2').innerText = "Please refund: " + data.amount;
            document.getElementById('payout_message3').innerText = "";
            document.getElementById('payout_print_modal').style.display = 'flex';
        }
    }
    updateStatus("Connected");
    get_fightstatus();
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

document.addEventListener('keydown', function(event) {
    if (event.key === 'Enter') {
        const payoutModal = document.getElementById('payoutmodal');
        const errorModal = document.getElementById('payout_error_modal');
        const cancelBetModal = document.getElementById('cancelbetmodal');

        if (payoutModal && payoutModal.style.display === 'flex') {
            const okayButton = document.getElementById('payout_yes');
            if (okayButton) okayButton.click();
        } else if (errorModal && errorModal.style.display === 'flex') {
            const closeButton = document.getElementById('payout_error_button');
            if (closeButton) closeButton.click();
        }

        if (cancelBetModal && cancelBetModal.style.display === 'flex') {
            const cancelButton = document.getElementById('cancelbet_yes');
            if (cancelButton) cancelButton.click();
        } else if (errorModal && errorModal.style.display === 'flex') {
            const closeButton = document.getElementById('payout_error_button');
            if (closeButton) closeButton.click();
        }
    }
});


//start of betting functions 
function update_disp_Fightnum(fightnum) {
    document.getElementById("currentmatchnum").innerText = "FIGHT # " + fightnum;
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
    document.getElementById("M_payout").innerText = data.M_payout;
    document.getElementById("W_total_bet").innerText = data.W_total_bet;
    document.getElementById("W_payout").innerText = data.W_payout
}

function disableadminButtons() {
    console.log("Disable admin buttons")
    const admincontrol = document.getElementById("controls");
    const admincontrolbuttons = admincontrol.querySelectorAll(".button")
    admincontrolbuttons.forEach(button => {
        button.onclick = () => null;
    })
}

function disableAllButtons() {
    const buttons = document.querySelectorAll(".button");
    buttons.forEach(button => {
        button.onclick = () => null; // Disable all admin buttons
    });
}

function setStartMatchButton() {
    console.log("Setting start match button");
    const startmatchButton = document.getElementById("startmatchbutton");
    startmatchButton.onclick = () => openmodal('control_confirmationModal', 'StartMatch'); // Enable the start match button
}

function setEndMatchButton() {
    console.log("Setting end match button");
    const endmatchButton = document.getElementById("endmatchbutton");
    endmatchButton.onclick = () => openmodal('control_confirmationModal', 'EndMatch'); // Enable the end match button
}

function setCloseBettingButton() {
    console.log("Setting close betting button");
    const closebettingButton = document.getElementById("closebettingbutton");
    //closebettingButton.onclick = () => null; // Enable the close betting button
    closebettingButton.onclick = () => openmodal('control_confirmationModal', 'AdminCloseBetting'); // Enable the close betting button
}

function setCancelMatchButton() {
    console.log("Setting cancel match button");
    const cancelmatchButton = document.getElementById("cancelmatchbutton");
    cancelmatchButton.onclick = () => openmodal('control_confirmationModal', 'CancelMatch'); // Enable the cancel match button
}

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
    console.log("Super closing betting for both sides");
    //disable buttons in the admin page
    const mopenButton = document.getElementById("M_OpenButton");
    const wopenButton = document.getElementById("W_OpenButton");
    const msubmitButton = document.getElementById("M_SubmitButton");
    const wsubmitButton = document.getElementById("W_SubmitButton");
    
    mopenButton.disable = true;
    mopenButton.onclick = null; // Disable the open button
    wopenButton.disable = true;
    wopenButton.onclick = null; // Disable the open button
    msubmitButton.onclick = () => openmodal('matchclosedmodal','null'); 
    wsubmitButton.onclick = () => openmodal('matchclosedmodal','null'); 
    
}

function SuperOpenBetting() {
    closemodal("control_confirmationModal");
    openMeron();
    openWala();
    console.log("Super Open betting for both sides");
    //disable buttons in the admin page
    const msubmitButton = document.getElementById("M_SubmitButton");
    const wsubmitButton = document.getElementById("W_SubmitButton");
    const mopenButton = document.getElementById("M_OpenButton");
    const wopenButton = document.getElementById("W_OpenButton");

    mopenButton.onclick = () => null; // Disable the open button
    wopenButton.onclick = () => null; // Disable the open button
    msubmitButton.onclick = () => check_total("MERON"); 
    wsubmitButton.onclick = () => check_total("WALA"); 
    
}

function openBetting(side){
    console.log("Opening betting for " +side)
    if (side === "BOTH"){
        SuperOpenBetting();
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

function openmodal(modalid, buttonid, side=null) {
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

    } else {
        console.log("Opening modal with ID: " + modalid);
        document.getElementById(modalid).style.display = 'flex';
    }
}



async function payout() {
   const barcode = document.getElementById('payout_barcode').value;
   closemodal('payoutmodal');
   if (barcode === 0 || barcode === '' || isNaN(barcode)) {
        openmodal('payout_error_modal', 'invalid_barcode');
   } else {
        try {
            administratorSocket.send(JSON.stringify({barcode: barcode}));
        }catch (error){
            console.error("websocket send failed: ", error);
            openmodal('payout_error_modal', 'web_socket_error');
        }
   }

}


function closeadminbetting() {
    console.log('Close admin betting')
    const msubmitButton = document.getElementById('M_SubmitButton');
    const wsubmitButton = document.getElementById('W_SubmitButton');
    msubmitButton.onclick = () => null;
    wsubmitButton.onclick = () => null;
}

function openadminbetting() {
    const msubmitButton = document.getElementById('M_SubmitButton');
    const wsubmitButton = document.getElementById('W_SubmitButton');
    msubmitButton.onclick = () => check_total("MERON");
    wsubmitButton.onclick = () => check_total("WALA");
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
    get_fightstatus();
    SuperCloseBetting();
    closemodal("control_confirmationModal");
}

function cancelMatch(){
    administratorSocket.send(JSON.stringify({fight_status: "CANCEL"}));
    get_fightstatus();
    closemodal("control_confirmationModal");
}

function endMatch(winner){
    console.log("Ending Match");
    administratorSocket.send(JSON.stringify({fight_status: "END", Winner: winner}));
    get_fightstatus();
    closemodal("control_confirmationModal");
    closemodal("whowonmodal")
}

async function get_status_for_display(fight_num=null, fight_status=null, m_status=null, w_status=null) {
    update_disp_FightStatus(fight_status);
    update_disp_Fightnum(fight_num);
    if (fight_status === "OPEN"){
        if (m_status === "OPEN") {
            openMeron();
        } else {
            closeMeron();
        }
        if (w_status === "OPEN") {
            openWala();
        } else {
            closeWala();
        }
    }else {
        closeMeron();
        closeWala();
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

    get_status_for_display(fight_num, fight_status, m_status, w_status);
}


function fightupdateStatus(fight_status){
    if (fight_status === "OPEN"){
        disableadminButtons();
        setCloseBettingButton();
    } else if (fight_status === "CLOSED") {
        console.log("Fight status is CLOSED");
        disableadminButtons();
        setCancelMatchButton();
        setEndMatchButton();
        closeBetting("BOTH")
        console.log("closed!")
    } else if (fight_status === "CANCELLED"){
        console.log("Fight Cancelled")
        disableadminButtons();
        setStartMatchButton();
        closeBetting("BOTH");
    } else if (fight_status === "COMPLETE"){
        console.log("Fight Complete")
        disableadminButtons();
        setStartMatchButton();
        closeBetting("BOTH");
    }
}

function openadminbetcontrolModal(side, action) {
    const modalmessage = document.getElementById("modal-message");
    const modalbutton = document.getElementById("confirmopen");
    const sidelabel = document.getElementById("")

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
    const barcode = document.getElementById('cancelbet_barcode').value;
    if (barcode === 0 || barcode === '' || isNaN(barcode)) {
        openmodal('payout_error_modal', 'invalid_barcode');
    }else {
        console.log("Cancelling bet for barcode: " + barcode);
        administratorSocket.send(JSON.stringify({cancel_barcode: barcode}));
        closemodal('cancelbetmodal');
   }

}
async function update_trends() {
    //console.log("Updating trends");
    const trends_response = await fetch(`/get_fight_results_view/`);
    const trend_data = await trends_response.json();
    //console.log("Trends data received: ", trend_data);

    const trendsList = document.getElementById("trends");
    trendsList.innerHTML = ''; // Clear existing rows
    const headerRow = document.createElement("li");
    headerRow.className = "sidebar-header";
    headerRow.innerHTML = `
        <div class="fightnum">FN</div>
        <div class="winner">SIDE</div>
        <div class="odds">Odds</div>
    `;
    trendsList.appendChild(headerRow);

    trend_data.forEach(match => {
    const row = document.createElement("li");
    let formattedOdds = '';
    
    if (match.odds === 'Llamado') { 
      formattedOdds = 'L';
    } else if (match.odds === 'Dehado') {
      formattedOdds = 'D';
    } else {
      formattedOdds = "----";
    }

    row.className = "sidebar-row";

    const fightDiv = document.createElement("div");
    fightDiv.className = "fightnum";
    fightDiv.textContent = match.fightnum;

    const winnerDiv = document.createElement("div");
    winnerDiv.className = "winner";
    winnerDiv.textContent = match.side;

    const oddsDiv = document.createElement("div");
    oddsDiv.className = "odds";
    oddsDiv.textContent = formattedOdds;

    // 🎨 Apply background based on winner
    if (match.side === "MERON") {
        winnerDiv.style.background = "linear-gradient(to bottom, red, black)";
        winnerDiv.style.color = "white";
        oddsDiv.style.background = "linear-gradient(to bottom, red, black)";
        oddsDiv.style.color = "white";
    } else if (match.side === "WALA") {
        winnerDiv.style.background = "linear-gradient(to bottom, blue, black)";
        winnerDiv.style.color = "white";
        oddsDiv.style.background = "linear-gradient(to bottom, blue, black)";
        oddsDiv.style.color = "white";
    } else {
        winnerDiv.style.background = "linear-gradient(to bottom, gray, black)";
        winnerDiv.style.color = "white";
        oddsDiv.style.background = "linear-gradient(to bottom, gray, black)";
        oddsDiv.style.color = "white";
    }

    // 🧱 Append columns to row
    row.appendChild(fightDiv);
    row.appendChild(winnerDiv);
    row.appendChild(oddsDiv);

    // 📥 Add row to sidebar
    trendsList.appendChild(row);

  });


}
