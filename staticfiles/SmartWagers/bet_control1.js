function disableSelectedButtons() {
    /*const buttons1 = document.querySelectorAll('#buttons_section1 .button'); // Select only buttons within this section
    buttons1.forEach(button => {
        button.classList.add('disabled'); // Add a class to visually indicate a disabled state
        //button.onclick = null; // Disable the click event
    });
    const buttons2 = document.querySelectorAll('#buttons_section2 .button'); // Select only buttons within this section
    buttons2.forEach(button => {
        button.classList.add('disabled'); // Add a class to visually indicate a disabled state
        //button.onclick = null; // Disable the click event
    });*/
    const Msubmitbutton = document.querySelectorAll('#meron-submitreset-button .button'); // Select only buttons within this section
    Msubmitbutton.forEach(mbutton => {
        //button.classList.add('disabled'); // Add a class to visually indicate a disabled state
        mbutton.onclick = 'opensubmitdisableModal()'; // Disable the click event
    });
    const Wsubmitbutton = document.querySelectorAll('#wala-submitreset-button .button'); // Select only buttons within this section
    Wsubmitbutton.forEach(wbutton => {
        //button.classList.add('disabled'); // Add a class to visually indicate a disabled state
        wbutton.onclick = 'opensubmitdisableModal()'; // Disable the click event
    });
    console.log('Buttons in the section have been disabled.');
}


function enableSelectedButtons() {
    /*const buttons1 = document.querySelectorAll('#buttons_section1 .button'); // Select only buttons within this section
    buttons1.forEach(button => {
        button.classList.remove('disabled'); // Add a class to visually indicate a disabled state
        //button.onclick = null; // Disable the click event
    });
    const buttons2 = document.querySelectorAll('#buttons_section2 .button'); // Select only buttons within this section
    buttons2.forEach(button => {
        button.classList.remove('disabled'); // Add a class to visually indicate a disabled state
        //button.onclick = null; // Disable the click event
    });*/
    const Msubmitbutton = document.querySelectorAll('#meron-submitreset-button .button'); // Select only buttons within this section
    Msubmitbutton.forEach(button => {
        //button.classList.add('disabled'); // Add a class to visually indicate a disabled state
        button.onclick = 'check_total("MERON")'; // Disable the click event
    });

    const Wsubmitbutton = document.querySelectorAll('#wala-submitreset-button .button'); // Select only buttons within this section
    Wsubmitbutton.forEach(button => {
        //button.classList.add('disabled'); // Add a class to visually indicate a disabled state
        button.onclick = 'check_total("WALA")'; // Disable the click event
    });

    console.log('Buttons in the section have been disabled.');
}

// Check localStorage for the disable flag
function checkDisableStatus() {
    const isDisabled = localStorage.getItem('disableButtons') === 'true';
    if (isDisabled) {
        disableSelectedButtons();
    }else {
        enableSelectedButtons();
    }
}

function disableAllButtons() {
    localStorage.setItem('disableButtons', 'true'); // Set the value to disable buttons
    alert('Betting is disabled in all tellers');
}

function enableAllButtons() {
    localStorage.setItem('disableButtons', 'false');
    alert('Betting open to all tellers')
}

// Listen for storage changes
window.addEventListener('storage', (event) => {
    if (event.key === 'disableButtons') {
        disableSelectedButtons();
    } else {
        enableSelectedButtons();
    }
});


// Initial check on page load
window.onload = checkDisableStatus;