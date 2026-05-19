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

function submitValue() {
    
    const wager_val = document.getElementById('wager_value');
    wager_val.value = wager_value; 

    const wager_side = document.getElementById('wager_id');
    wager_side.value = wager_id;

    document.getElementById('submitwagerForm').submit(); // Submit the form

    resetTotal();
}

window.onload = function() {
    document.getElementById('wager_value').value = '';
    document.getElementById('wager_id').value = '';
};