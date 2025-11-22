function reloadStyle() {
  links = document.getElementsByTagName("link");
  for (i = 0; i < links.length;i++) { 
    link = links[i]; if (link.rel === "stylesheet") {link.href += "?"; }
  }
}

// Action chips management
function addActionChip(actionKey, actionLabel) {
  // Check if already added
  if (selectedActions.some(a => a.key === actionKey)) {
    return;
  }
  
  selectedActions.push({ key: actionKey, label: actionLabel });
  renderActionChips();
}


function removeActionChip(actionKey) {
  selectedActions = selectedActions.filter(a => a.key !== actionKey);
  renderActionChips();
}


function renderActionChips() {
  actionsChipsContainer.innerHTML = "";
  
  selectedActions.forEach(action => {
    const chip = document.createElement("div");
    chip.className = "action-chip";
    chip.textContent = action.label;
    chip.title = "Click to remove";
    chip.addEventListener("click", () => {
      removeActionChip(action.key);
    });
    actionsChipsContainer.appendChild(chip);
  });
}


function clearActionChips() {
  selectedActions = [];
  renderActionChips();
}


// Connection state management
connectionIndicator.addEventListener("click", showConnectionInfo);


function setConnectionState(state) {
  connectionState = state;
  connectionIndicator.className = `connection-indicator ${state}`;
  
  if (state === "connected") {
    connectionTime = new Date();
  }
}


function showConnectionInfo() {
  let info = `<span class='system'>Connection Status: ${connectionState}</span>`;
  
  if (connectionState === "connected" && connectionTime) {
    const duration = Math.floor((new Date() - connectionTime) / 1000);
    info += `<br><span class='system'>Connected for ${duration} seconds</span>`;
  }
  
  if (socket.id) {
    info += `<br><span class='system'>Socket ID: ${socket.id}</span>`;
  }
  
  addMessage(info);
}


function attachRefEventHandlers(tgt) {
  // Add click/touch event handlers to all spans with IDs
  const spans = tgt.querySelectorAll('span.ref');
  touchHandler = (e) => {
    e.preventDefault();
    src = e.currentTarget;
    // If span has data-cmd attribute, use that as action command
    if (src.dataset.cmd) {
      actionCmd = `.${src.dataset.cmd}`;
      if (src.dataset.target) {
        actionCmd += ` @${src.dataset.target}`;
      }
      socket.emit("message", { text: actionCmd });
    } else {
      actionLabel = makeActionLabel(src.textContent);
      if (src.id.length === 0) {
        actionCmd = `[[@ ${src.textContent} ]]`;
      } else {
        actionCmd = `@${src.id}`;
      }
      addActionChip(actionCmd, actionLabel);
    }
  };

  spans.forEach(span => {
    span.addEventListener('click', touchHandler);
    span.addEventListener('touchend', touchHandler);
  });
}


function addMessage(text, cls) {
  const div = document.createElement("div");
  div.className = "msg " + (cls || "");
  div.innerHTML = text;
  messagesDiv.appendChild(div);
  
  // Remove old messages if count exceeds 50
  const allMessages = messagesDiv.querySelectorAll('.msg');
  if (allMessages.length > 50) {
    const removeCount = allMessages.length - 50;
    for (let i = 0; i < removeCount; i++) {
      allMessages[i].remove();
    }
  }
  
  // Replace content of 'self' spans with 'YOU'
  const selfSpans = div.querySelectorAll('span.self');
  selfSpans.forEach(span => {
    span.textContent = 'you';
  });
  

  attachRefEventHandlers(div);  
  messagesDiv.scrollTop = messagesDiv.scrollHeight;
}

sendBtn.addEventListener("click", () => {
  const t = msgInput.value.trim();
  
  // Build message with action prefixes
  let fullMessage = "";
  if (selectedActions.length > 0) {
    const actionTexts = selectedActions.map(a => a.key).join(" ");
    fullMessage = actionTexts + " " + t;
  } else {
    fullMessage = t;
  }
  
  if (!fullMessage.trim()) return;
  
  // Play bop sound
  playBopSound();
  
  socket.emit("message", { text: fullMessage });
  msgInput.value = "";
  clearActionChips();
});


msgInput.addEventListener("keydown", (ev) => {
  if (ev.key === "Enter") {
    sendBtn.click();
  }
});


// Talk button toggle
btnTalk.addEventListener("click", () => {
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
});


// Text-to-speech function
function stripFormattedText(html) {
  // Create a temporary element to parse HTML
  const temp = document.createElement('div');
  temp.innerHTML = html;
  text = temp.textContent || temp.innerText || '';
  // Remove emojis and repeated punctuation characters
  text = text.replace(/[\p{Emoji_Presentation}|\p{Emoji}\uFE0F]/gu, ''); // Remove emojis
  text = text.replace(/([!?.,])\1{2,}/g, '$1'); // Replace repeated punctuation with single
  return text;
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
  utterance.onstart = () => { isSpeaking = true; };  
  utterance.onend = () => { isSpeaking = false; };
  utterance.onerror = () => { isSpeaking = false; };  
  speechSynthesis.speak(utterance);
}
