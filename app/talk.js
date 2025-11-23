// Talk button toggle with long-press for voice selection
let voicePopupShown = false;


btnTalk.addEventListener("mousedown", (e) => {
  voicePopupShown = false;
  longPressTimer = setTimeout(() => {
    // Long press - show voice selection
    showVoiceSelection(e);
    voicePopupShown = true;
    longPressTimer = null;
  }, 500); // 500ms for long press
});


btnTalk.addEventListener("mouseup", () => {
  if (longPressTimer) {
    // Short press - toggle talk mode
    clearTimeout(longPressTimer);
    longPressTimer = null;
    toggleTalkMode();
  } else if (!voicePopupShown) {
    // Released after timeout but popup wasn't shown (shouldn't happen, but safety check)
    toggleTalkMode();
  }
  // If voicePopupShown is true, do nothing - let the popup stay open
});


btnTalk.addEventListener("mouseleave", () => {
  if (longPressTimer) {
    clearTimeout(longPressTimer);
    longPressTimer = null;
  }
});


// Also support touch events for mobile
btnTalk.addEventListener("touchstart", (e) => {
  e.preventDefault();
  voicePopupShown = false;
  longPressTimer = setTimeout(() => {
    showVoiceSelection(e);
    voicePopupShown = true;
    longPressTimer = null;
  }, 500);
});


btnTalk.addEventListener("touchend", (e) => {
  if (longPressTimer) {
    e.preventDefault();
    clearTimeout(longPressTimer);
    longPressTimer = null;
    toggleTalkMode();
  } else if (!voicePopupShown) {
    e.preventDefault();
    toggleTalkMode();
  }
  // If voicePopupShown is true, do nothing - let the popup stay open
});


btnTalk.addEventListener("touchcancel", () => {
  if (longPressTimer) {
    clearTimeout(longPressTimer);
    longPressTimer = null;
  }
});


function toggleTalkMode() {
  talkEnabled = !talkEnabled;
  
  if (talkEnabled) {
    btnTalk.style.background = "#28a745";
    btnTalk.textContent = "🔊 Talk";
  } else {
    btnTalk.style.background = "#6c757d";
    btnTalk.textContent = "🔇 Talk";
    
    // Stop any ongoing speech
    if (speechSynthesis.speaking) {
      speechSynthesis.cancel();
      isSpeaking = false;
    }
  }
}


function speakText(text) {
  // Skip if already speaking
  if (isSpeaking) {
    return;
  }
  const plainText = stripFormattedText(text);
  if (!plainText.trim()) {
    return;
  }
  
  // Create speech synthesis utterance
  const utterance = new SpeechSynthesisUtterance(plainText);
  
  // Use selected voice if available
  if (selectedVoice) {
    utterance.voice = selectedVoice;
  }
  
  utterance.onstart = () => { isSpeaking = true; };  
  utterance.onend = () => { isSpeaking = false; };
  utterance.onerror = () => { isSpeaking = false; };  
  speechSynthesis.speak(utterance);
}


function showVoiceSelection(event) {
  // Get available voices
  let voices = speechSynthesis.getVoices();
  
  // If voices not loaded yet, wait for them
  if (voices.length === 0) {
    speechSynthesis.onvoiceschanged = () => {
      voices = speechSynthesis.getVoices();
      createVoicePopup(voices, event);
    };
  } else {
    createVoicePopup(voices, event);
  }
}


function createVoicePopup(voices, event) {
  // Remove any existing popup
  const existingPopup = document.querySelector('.voice-popup');
  if (existingPopup) {
    existingPopup.remove();
  }
  
  // Create popup
  const popup = document.createElement('div');
  popup.className = 'voice-popup';
  
  // Add header
  const header = document.createElement('h4');
  header.textContent = 'Select Voice';
  popup.appendChild(header);
  
  // Add voice options
  voices.forEach(voice => {
    const option = document.createElement('div');
    option.className = 'voice-option';
    if (selectedVoice && selectedVoice.name === voice.name) {
      option.classList.add('selected');
    }
    
    const nameSpan = document.createElement('span');
    nameSpan.className = 'voice-option-name';
    nameSpan.textContent = voice.name;
    
    const langSpan = document.createElement('span');
    langSpan.className = 'voice-option-lang';
    langSpan.textContent = `(${voice.lang})`;
    
    option.appendChild(nameSpan);
    option.appendChild(langSpan);
    
    option.addEventListener('click', () => {
      selectedVoice = voice;
      popup.remove();
      voicePopupShown = false;
      
      // Save selection to localStorage
      localStorage.setItem('tinyrooms_voice', voice.name);
      
      // Show confirmation
      addMessage(`<span class='system'>Voice set to: ${voice.name}</span>`);
    });
    
    popup.appendChild(option);
  });
  
  // Position popup near the button
  document.body.appendChild(popup);
  
  const btnRect = btnTalk.getBoundingClientRect();
  popup.style.left = btnRect.left + 'px';
  popup.style.top = (btnRect.bottom + 5) + 'px';
  
  // Adjust if popup goes off-screen
  const popupRect = popup.getBoundingClientRect();
  if (popupRect.right > window.innerWidth) {
    popup.style.left = (window.innerWidth - popupRect.width - 10) + 'px';
  }
  if (popupRect.bottom > window.innerHeight) {
    popup.style.top = (btnRect.top - popupRect.height - 5) + 'px';
  }
  
  // Close popup when clicking outside
  setTimeout(() => {
    const closeHandler = (e) => {
      if (!popup.contains(e.target) && e.target !== btnTalk) {
        popup.remove();
        voicePopupShown = false;
        document.removeEventListener('click', closeHandler);
      }
    };
    document.addEventListener('click', closeHandler);
  }, 100);
}


// Load saved voice preference on startup
window.addEventListener('load', () => {
  const savedVoiceName = localStorage.getItem('tinyrooms_voice');
  if (savedVoiceName) {
    const loadVoice = () => {
      const voices = speechSynthesis.getVoices();
      const voice = voices.find(v => v.name === savedVoiceName);
      if (voice) {
        selectedVoice = voice;
      }
    };
    
    // Try loading immediately
    loadVoice();
    
    // Also listen for voices changed event
    speechSynthesis.onvoiceschanged = loadVoice;
  }
});