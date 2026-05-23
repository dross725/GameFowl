const adminWebsocketProtocol = window.location.protocol === "https:" ? "wss" : "ws";
const adminSocket = new WebSocket(`${adminWebsocketProtocol}://${window.location.host}/ws/administrator/`);

adminSocket.onmessage = (event) => {
    //console.log(`WebSocket message received for ${pageType}:`, event.data);
    const data = JSON.parse(event.data);
    console.log("Data received from server: ", data);
    console.log("This is the admin.js file");

    if ("mtotal" in data && "wtotal" in data) {
        document.getElementById("M_total_bet").innerText = data.mtotal;
        document.getElementById("M_payout").innerText = data.mpayout;
        document.getElementById("W_total_bet").innerText = data.wtotal;
        document.getElementById("W_payout").innerText = data.wpayout;
        document.getElementById("ws_status").innerText = "Status: Connected";
        updateStatus("Connected");
        console.log("Data received:", data);
        console.log("This is the admin.js file");
        updateFightnum(data.fightnum)
    }
};

adminSocket.onopen = () => {
    console.log("WebSocket connected!");
    adminSocket.send(JSON.stringify({ update: true }));
    console.log("Initial data request sent.");
    updateStatus("Connected");
    document.getElementById("ws_status").innerText = "Status: Connected";
    document.getElementById("ws_status").style.color = "blue";
    document.getElementById("ws_status").style.fontWeight = "bold";     
    get_fightstatus();
};

adminSocket.onerror = (error) => {
    console.error("WebSocket Error:", error);
};

adminSocket.onclose = () => {
    console.log("WebSocket disconnected!");
    updateStatus("Disconnected");
    document.getElementById("ws_status").innerText = "Status: Disconnected";

};

function openadminbetcontrolModal(side, action) {

    const modalmessage = document.getElementById("modal-message");
    const modalbutton = document.getElementById("confirmopen");
    const sidelabel = document.getElementById("")
    modalmessage.innerHTML = "Are you sure you want to " +action +" Betting for <strong>" + side + "</strong>?";
    if (action === 'Open') {
        modalbutton.onclick = () => OpenBetting(side);
    }else if (action === 'Close') {
        modalbutton.onclick = () => CloseBetting(side);
    } else {
        console.error("Invalid action specified:", action);
        return;
    }
    document.getElementById('adminbetcontrol').style.display = 'flex';
}

function closeadminbetcontrolModal() {
     document.getElementById('adminbetcontrol').style.display = 'none';
}

function updateStatus(status) {
    document.getElementById("ws_status").innerText = "Status: " + status;
}

function updateFightnum(fightnum){
    document.getElementById("currentmatchnum").innerText = "FIGHT # "+fightnum;
}

function openmodal(modalid, buttonid) {
    //const modal = document.getElementById(modalid);
    const cm_headermessage = document.getElementById('cm-modal-header')
    const cm_message = document.getElementById('cm-modal-message')
    const cm_yesbutton = document.getElementById('cm-yes-button')
    const cm_nobutton = document.getElementById('cm-no-button')
    
    if (buttonid === 'StartMatch') {
        console.log("Start Match button clicked");
        cm_headermessage.innerHTML = "Start Match";
        cm_message.innerHTML = "Are you sure you want to start the match?";
        cm_yesbutton.onclick = () => startmatch();
        cm_nobutton.onclick = () => closemodal('control_confirmationModal');
    } else if (buttonid === 'EndMatch') {
        console.log("End Match button clicked");
        cm_headermessage.innerHTML = "End Match";
        cm_message.innerHTML = "Are you sure you want to end the match?";
        cm_yesbutton.onclick = () => openmodal('whowonmodal', 'winner');
        cm_nobutton.onclick = () => closemodal('control_confirmationModal');
    } else if (buttonid === 'SuperCloseBetting'){
        console.log("Super Close Betting button clicked");
        cm_headermessage.innerHTML = "Close Betting";
        cm_message.innerHTML = "Are you sure you want to close betting for everyone including you?";
        cm_yesbutton.onclick = () => SuperCloseBetting();
        cm_nobutton.onclick = () => closemodal('control_confirmationModal');
    }

    if (modalid == 'whowonmodal') {
        document.getElementById(modalid).style.display = 'flex';
    }else if (modalid =='matchclosedmodal'){
        document.getElementById(modalid).style.display = 'flex';
    }
    else {
        document.getElementById('control_confirmationModal').style.display = 'flex';
    }
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

function declarewinner(side) {
    console.log("Declaring winner for side:", side);

    closemodal("control_confirmationModal");
    SuperCloseBetting();
    
    const currentmatchstatus = document.getElementById("currentmatchstatus");
    const startmatchButton = document.getElementById("startmatchbutton");
    currentmatchstatus.innerHTML = "COMPLETE";
    disableadminButtons();

    startmatchButton.onclick = () => openmodal('control_confirmationModal', 'StartMatch'); // Enable the start match button
    adminSocket.send(JSON.stringify({ winner: side}));
    closemodal("whowonmodal");
}


function startmatch() {
    console.log("Starting match...");
    closemodal("control_confirmationModal");
    const CloseBettingButton = document.getElementById("closebettingbutton");
    adminSocket.send(JSON.stringify({ fight_status: 'START' }));
    get_fightstatus();
    
    disableadminButtons();
    CloseBettingButton.onclick = () => openmodal('control_confirmationModal', 'SuperCloseBetting'); // Enable the close betting button    
    
    console.log("Match started successfully.");
}

function OpenBetting(side) {
    closeadminbetcontrolModal();
    console.log("Opening betting for side:", side);
    if (side === 'MERON') {
        try {
            const mcloseButton = document.getElementById("M_CloseButton");
            const mopenButton = document.getElementById("M_OpenButton");
            const status_text = document.getElementById("meron-betting-status");

            status_text.innerHTML = "OPEN";
            status_text.style.backgroundColor = "rgba(7, 248, 2, 0.573)"; // Change background color to green   
            //adminSocket.send(JSON.stringify({ ButtonStatus: 'Open', side : 'MERON' }));
            adminSocket.send(JSON.stringify({ fight_status: 'Open', side : 'MERON' }));
            mcloseButton.onclick = () => openadminbetcontrolModal("MERON", "Close");
            mopenButton.onclick = () => null // Disable the open button

            //console.log("Betting opened for MERON");
            //console.log("Data sent to server: ", { ButtonStatus: false, side : 'MERON' });
        }
        catch (error) {
            console.error("Error sending message to server:", error);
        }
        // adminSocket.send(JSON.stringify({ ButtonStatus: false, side : 'MERON' }));
    } else if (side === 'WALA') {
        try {
            const wcloseButton = document.getElementById("W_CloseButton");
            const wopenButton = document.getElementById("W_OpenButton");
            const status_text = document.getElementById("wala-betting-status");

            status_text.innerHTML = "OPEN";
            status_text.style.backgroundColor = "rgba(7, 248, 2, 0.573)"; // Change background color to green
            adminSocket.send(JSON.stringify({ fight_status: 'Open', side : 'WALA' }));

            wcloseButton.onclick = () => openadminbetcontrolModal("WALA", "Close");
            wopenButton.onclick = () => null // Disable the open button
        }
        catch (error) {
            console.error("Error sending message to server:", error);
        }
        //adminSocket.send(JSON.stringify({ ButtonStatus: false, side : 'WALA' }));
    } else if (side === 'BOTH'){
        //Open MERON
        const mcloseButton = document.getElementById("M_CloseButton");
        const mopenButton = document.getElementById("M_OpenButton");
        const mstatus_text = document.getElementById("meron-betting-status");

        mstatus_text.innerHTML = "OPEN";
        mstatus_text.style.backgroundColor = "rgba(7, 248, 2, 0.573)"; // Change background color to green   
        adminSocket.send(JSON.stringify({ ButtonStatus: 'Open', side : 'MERON' }));

        mcloseButton.onclick = () => openadminbetcontrolModal("MERON", "Close");
        mopenButton.onclick = () => null // Disable the open button

        //Open WALA
        const wcloseButton = document.getElementById("W_CloseButton");
        const wopenButton = document.getElementById("W_OpenButton");
        const wstatus_text = document.getElementById("wala-betting-status");

        wstatus_text.innerHTML = "OPEN";
        wstatus_text.style.backgroundColor = "rgba(7, 248, 2, 0.573)"; // Change background color to green
        adminSocket.send(JSON.stringify({ ButtonStatus: 'Open', side : 'WALA' }));

        wcloseButton.onclick = () => openadminbetcontrolModal("WALA", "Close");
        wopenButton.onclick = () => null // Disable the open button
}
    else {
        console.error("Invalid side specified:", side);
    }
}

function disableadminButtons() {
    const startmatchButton = document.getElementById("startmatchbutton");
    const closebettingButton = document.getElementById("closebettingbutton");
    const endmatchButton = document.getElementById("endmatchbutton");
    const cancelmatchButton = document.getElementById("cancelmatchbutton");
    
    startmatchButton.onclick = () => null; // Disable the start match button
    closebettingButton.onclick = () => null; // Disable the close betting button
    endmatchButton.onclick = () => null; // Disable the end match button
    cancelmatchButton.onclick = () => null; // Disable the cancel match button
}

function SuperCloseBetting() {
    closemodal("control_confirmationModal");
    console.log("Super closing betting for both sides");
    CloseBetting("BOTH");
    //disable buttons in the admin page
    const mopenButton = document.getElementById("M_OpenButton");
    const wopenButton = document.getElementById("W_OpenButton");
    const msubmitButton = document.getElementById("M_SubmitButton");
    const wsubmitButton = document.getElementById("W_SubmitButton");
    const currentmatchstatus = document.getElementById("currentmatchstatus");
    const startmatchButton = document.getElementById("startmatchbutton");
    const closebettingButton = document.getElementById("closebettingbutton");

    mopenButton.onclick = () => null; // Disable the open button
    wopenButton.onclick = () => null; // Disable the open button
    startmatchButton.onclick = () => null; // Disable the start match button
    closebettingButton.onclick = () => null; // Disable the close betting button
    msubmitButton.onclick = () => openmodal('matchclosedmodal','null'); 
    wsubmitButton.onclick = () => openmodal('matchclosedmodal','null'); 
    currentmatchstatus.innerHTML = "CLOSED";
    currentmatchstatus.style.backgroundColor = "rgba(248, 7, 7, 0.573)"; // Change background color to red    
}

function CloseBetting(side) {
    closeadminbetcontrolModal();
    console.log("Closing betting for side:", side);
    if (side === 'MERON') {
        const mcloseButton = document.getElementById("M_CloseButton");
        const mopenButton = document.getElementById("M_OpenButton");
        const status_text = document.getElementById("meron-betting-status");
        
        status_text.innerHTML = "CLOSED";
        status_text.style.backgroundColor = "rgba(248, 7, 7, 0.573)"; // Change background color to red
        adminSocket.send(JSON.stringify({ ButtonStatus: 'Close', side : 'MERON' }));

        mcloseButton.onclick = () => null;
        mopenButton.onclick = () => openadminbetcontrolModal("MERON", "Open");

    } else if (side === 'WALA') {
        const wcloseButton = document.getElementById("W_CloseButton");
        const wopenButton = document.getElementById("W_OpenButton");
        const status_text = document.getElementById("wala-betting-status");

        status_text.innerHTML = "CLOSED";
        status_text.style.backgroundColor = "rgba(248, 7, 7, 0.573)"; // Change background color to red
        adminSocket.send(JSON.stringify({ ButtonStatus: 'Close', side : 'WALA' }));
        wcloseButton.onclick = () => null;
        wopenButton.onclick = () => openadminbetcontrolModal("MERON", "Open");

    }else if (side === 'BOTH'){
        //close MERON
        const mcloseButton = document.getElementById("M_CloseButton");
        const mopenButton = document.getElementById("M_OpenButton");
        const mstatus_text = document.getElementById("meron-betting-status");
        
        mstatus_text.innerHTML = "CLOSED";
        mstatus_text.style.backgroundColor = "rgba(248, 7, 7, 0.573)"; // Change background color to red
        adminSocket.send(JSON.stringify({ fight_status: 'CLOSE' }));
        
        mcloseButton.onclick = () => null;
        mopenButton.onclick = () => null;

        //close WALA
        const wcloseButton = document.getElementById("W_CloseButton");
        const wopenButton = document.getElementById("W_OpenButton");
        const wstatus_text = document.getElementById("wala-betting-status");

        wstatus_text.innerHTML = "CLOSED";
        wstatus_text.style.backgroundColor = "rgba(248, 7, 7, 0.573)"; // Change background color to red
        adminSocket.send(JSON.stringify({ ButtonStatus: 'Close', side : 'WALA' }));
        wcloseButton.onclick = () => null;
        wopenButton.onclick = () => null;
    } 
    else {
        console.error("Invalid side specified:", side);
    }
}

async function get_fightstatus() {
    try {
        const response = await fetch(`/get_fight_status_view/`);
        console.log('response: ' +response);
        const data = await response.json();
        console.log("Fight status data received: ", data);
        const currentmatchstatus = document.getElementById("currentmatchstatus");   
        const startmatchButton = document.getElementById("startmatchbutton");
        const endmatchButton = document.getElementById("endmatchbutton");
        const closebettingButton = document.getElementById("closebettingbutton");
        const cancelmatchButton = document.getElementById("cancelmatchbutton");
        const msubmitButton = document.getElementById("M_SubmitButton");
        const wsubmitButton = document.getElementById("W_SubmitButton");
        const mopenButton = document.getElementById("M_OpenButton");
        const wopenButton = document.getElementById("W_OpenButton");
        const mcloseButton = document.getElementById("M_CloseButton");
        const wcloseButton = document.getElementById("W_CloseButton");
        const currentmatchnum = document.getElementById("currentmatchnum");
        const mbettingstatus = document.getElementById("meron-betting-status"); 
        const wbettingstatus = document.getElementById("wala-betting-status");

        currentmatchnum.innerText = "FIGHT # " + data.fightnum;
        currentmatchstatus.innerHTML = data.overall_status;

        if (data.fight_status === 'START') {
            currentmatchstatus.style.backgroundColor = "rgba(7, 248, 2, 0.573)"; // Change background color to green    
            OpenBetting('BOTH'); // Open betting for both sides

        } else if (data.overall_status === 'OPEN') {
            currentmatchstatus.style.backgroundColor = "rgba(7, 248, 2, 0.573)"; // Change background color to green    
            if (data.meron_status == 'OPEN'){
                OpenBetting('MERON'); // Open MERON betting
                // mopenButton.onclick = () => null; // Disable the open button for MERON
                // mcloseButton.onclick = () => openadminbetcontrolModal("MERON", "Close");
            } else if (data.meron_status == 'CLOSED'){
                CloseBetting('MERON'); // Close MERON betting
                // mopenButton.onclick = () => openadminbetcontrolModal("MERON", "Open");
                // mcloseButton.onclick = () => null; // Disable the close button for MERON
            }else if (data.wala_status == 'OPEN'){
                OpenBetting('WALA'); // Open WALA betting
                // wopenButton.onclick = () => null; // Disable the open button for WALA
                // wcloseButton.onclick = () => openadminbetcontrolModal("WALA", "Close");
            }
            else if (data.wala_status == 'CLOSED'){
                CloseBetting('WALA'); // Close WALA betting
                // wopenButton.onclick = () => openadminbetcontrolModal("WALA", "Open");
                // wcloseButton.onclick = () => null; // Disable the close button for WALA
            }
            // startmatchButton.onclick = () => null; // Disable the start match button
            // endmatchButton.onclick = () => openmodal('control_confirmationModal', 'EndMatch'); // Enable the end match button
            // closebettingButton.onclick = () => openmodal('control_confirmationModal', 'SuperCloseBetting'); // Enable the close betting button
            // cancelmatchButton.onclick = () => openmodal('control_confirmationModal', 'CancelMatch'); // Enable the cancel match button
            // msubmitButton.onclick = () => check_total('MERON'); // Enable the submit button for MERON
            // wsubmitButton.onclick = () => check_total('WALA'); // Enable the submit button for WALA
        } else if (data.overall_status === 'CLOSED') {
            console.log("Fight status is CLOSED");
            SuperCloseBetting(); // Close betting for both sides
        //     currentmatchstatus.style.backgroundColor = "rgba(248, 7, 7, 0.573)"; // Change background color to red    
        //     mopenButton.onclick = () => null; // Disable the open button for MERON
        //     wopenButton.onclick = () => null; // Disable the open button for WALA
        //     mcloseButton.onclick = () => null; // Disable the close button for MERON
        //     wcloseButton.onclick = () => null; // Disable the close button for WALA
        //     startmatchButton.onclick = () => null; // Disable the start match button
        //     closebettingButton.onclick = () => null; // Disable the cancel match button
        //     endmatchButton.onclick = () => openmodal('endmatchModal', 'EndMatch'); // Enable the end match button
        //     cancelmatchButton.onclick = () => openmodal('cancelmatchModal', 'CancelMatch'); // Enable the cancel match button
        } else if (data.overall_status === 'CANCELED') {
            currentmatchstatus.style.backgroundColor = "rgba(248, 7, 7, 0.573)"; // Change background color to red    
            mopenButton.onclick = () => null; // Disable the open button for MERON
            wopenButton.onclick = () => null; // Disable the open button for WALA
            mcloseButton.onclick = () => null; // Disable the close button for MERON
            wcloseButton.onclick = () => null; // Disable the close button for WALA
            startmatchButton.onclick = () => openmodal('control_confirmationModal', 'StartMatch'); // Enable the start match button
            closebettingButton.onclick = () => null; // Disable the close betting button
            endmatchButton.onclick = () => null; // Disable the end match button
            cancelmatchButton.onclick = () => null; // Disable the cancel match button
        } else if (data.overall_status === 'COMPLETE') {
            currentmatchstatus.style.backgroundColor = "rgba(248, 7, 7, 0.573)"; // Change background color to red    
            startmatchButton.onclick = () => openmodal('control_confirmationModal', 'StartMatch'); // Enable the start match button
            mopenButton.onclick = () => null; // Disable the open button for MERON
            wopenButton.onclick = () => null; // Disable the open button for WALA
            mcloseButton.onclick = () => null; // Disable the close button for MERON
            wcloseButton.onclick = () => null; // Disable the close button for WALA
            msubmitButton.onclick = () => null; // Disable the submit button for MERON
            wsubmitButton.onclick = () => null; // Disable the submit button for WALA
            closebettingButton.onclick = () => null; // Disable the close betting button
            endmatchButton.onclick = () => null; // Disable the end match button
            cancelmatchButton.onclick = () => null; // Disable the cancel match button
        }
    }
    catch (error) {
        console.error("Error fetching fight status:", error);  
    }
    console.log("Fight status fetched successfully.");
}
        
async function fetchButtonState() {
    const mbettingstatus = document.getElementById("meron-betting-status");
    const wbettingstatus = document.getElementById("wala-betting-status");
    try {
        const response = await fetch(`/get_button_state_view/`);  
        const data = await response.json();
        console.log("Button state data received: ", data);
        if (data.mstate === 'Open') {
            const mcloseButton = document.getElementById("M_CloseButton");
            const mopenButton = document.getElementById("M_OpenButton");
            
            mbettingstatus.innerHTML = "OPEN";
            mbettingstatus.style.backgroundColor = "rgba(7, 248, 2, 0.573)";
            mcloseButton.onclick = () => openadminbetcontrolModal("MERON", "Close");
            mopenButton.onclick = () => null; // Disable the open button

        } else if (data.mstate === 'Close') {
            const mcloseButton = document.getElementById("M_CloseButton");
            const mopenButton = document.getElementById("M_OpenButton");
            
            mbettingstatus.innerHTML = "CLOSED";
            mbettingstatus.style.backgroundColor = "rgba(248, 7, 7, 0.573)";  
            mcloseButton.onclick = () => null; // Disable the close button
            mopenButton.onclick = () => openadminbetcontrolModal("MERON", "Open");
        }
        if (data.wstate === 'Open') {
            const wcloseButton = document.getElementById("W_CloseButton");
            const wopenButton = document.getElementById("W_OpenButton");

            wbettingstatus.innerHTML = "OPEN";
            wbettingstatus.style.backgroundColor = "rgba(7, 248, 2, 0.573)";  
            wcloseButton.onclick = () => openadminbetcontrolModal("WALA", "Close");
            wopenButton.onclick = () => null; // Disable the open button

        } else if (data.wstate === 'Close') {
            const wcloseButton = document.getElementById("W_CloseButton");
            const wopenButton = document.getElementById("W_OpenButton");

            wbettingstatus.innerHTML = "CLOSED";
            wbettingstatus.style.backgroundColor = "rgba(248, 7, 7, 0.573)";  
            wcloseButton.onclick = () => null; // Disable the close button
            wopenButton.onclick = () => openadminbetcontrolModal("WALA", "Open");
        }
    } catch (error) {
        console.error("Error fetching button state:", error);
    }
    console.log("Button state fetched successfully.");
}

document.addEventListener("DOMContentLoaded", () => {
    console.log("Fetching button states on page load...");
    fetchButtonState();
});