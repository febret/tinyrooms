function reloadStyle() {
  links = document.getElementsByTagName("link");
  for (i = 0; i < links.length;i++) { 
    link = links[i]; if (link.rel === "stylesheet") {link.href += "?"; }
  }
}


// Description panel management
function showDescriptionPanel(label, description) {
  descriptionPanel.innerHTML = "";
  
  if (label || description) {
    if (label) {
      const labelEl = document.createElement("span");
      labelEl.className = "desc-panel-label";
      labelEl.textContent = label;
      descriptionPanel.appendChild(labelEl);
    }
    if (description) {
      if (label) {
        descriptionPanel.appendChild(document.createTextNode(" — "));
      }
      const descEl = document.createElement("span");
      descEl.className = "desc-panel-text";
      descEl.textContent = description;
      descriptionPanel.appendChild(descEl);
    }
    descriptionPanel.style.display = "block";
  } else {
    descriptionPanel.style.display = "none";
  }
}


function clearDescriptionPanel() {
  descriptionPanel.innerHTML = "";
  descriptionPanel.style.display = "none";
  // Remove selected state from all icons
  document.querySelectorAll('.room-icon.selected').forEach(i => i.classList.remove('selected'));
}


// Icon event handlers for the room icon strip
function attachIconEventHandlers(container) {
  const icons = container.querySelectorAll('.room-icon');
  
  icons.forEach(icon => {
    const handler = (e) => {
      e.preventDefault();
      
      const refId = icon.dataset.refId || "";
      const label = icon.dataset.label || "";
      const description = icon.dataset.description || "";
      
      // Show entity description in the panel
      showDescriptionPanel(label, description);
      
      // Add as an action target chip (same behaviour as clicking a ref span)
      if (refId) {
        const actionLabel = makeActionLabel(label) || "…";
        addActionChip('@' + refId, actionLabel);
      }
      
      // Highlight selected icon, deselect others in the same strip
      container.querySelectorAll('.room-icon').forEach(i => i.classList.remove('selected'));
      icon.classList.add('selected');
    };
    
    icon.addEventListener('click', handler);
    icon.addEventListener('touchend', handler);
  });
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
