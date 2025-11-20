const socket = io();

const usernameInput = document.getElementById("username");
const passwordInput = document.getElementById("password");
const btnLogin = document.getElementById("btnLogin");
const btnRegister = document.getElementById("btnRegister");
const loginStatus = document.getElementById("loginStatus");
const chatBox = document.getElementById("chatBox");
const messagesDiv = document.getElementById("messages");
const msgInput = document.getElementById("msgInput");
const sendBtn = document.getElementById("sendBtn");
const btnLogout = document.getElementById("btnLogout");
const actionsChipsContainer = document.getElementById("actionsChips");

let myUsername = null;
let lastPassword = null; // Store password for auto-reconnect
let selectedActions = []; // Array of {key, label} for selected actions


// Cookie utilities
function setCookie(name, value, days) {
  const expires = new Date();
  expires.setTime(expires.getTime() + days * 24 * 60 * 60 * 1000);
  document.cookie = name + "=" + encodeURIComponent(value) + ";expires=" + expires.toUTCString() + ";path=/";
}


function getCookie(name) {
  const nameEQ = name + "=";
  const cookies = document.cookie.split(';');
  for (let i = 0; i < cookies.length; i++) {
    let c = cookies[i];
    while (c.charAt(0) === ' ') c = c.substring(1, c.length);
    if (c.indexOf(nameEQ) === 0) return decodeURIComponent(c.substring(nameEQ.length, c.length));
  }
  return null;
}


function deleteCookie(name) {
  document.cookie = name + "=;expires=Thu, 01 Jan 1970 00:00:00 UTC;path=/";
}


function saveCredentials(username, password) {
  setCookie("tr_username", username, 30);
  setCookie("tr_password", password, 30);
}


function loadCredentials() {
  return {
    username: getCookie("tr_username"),
    password: getCookie("tr_password")
  };
}


function clearCredentials() {
  deleteCookie("tr_username");
  deleteCookie("tr_password");
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

// localStorage for messages
function saveMessagesToStorage() {
  const messages = [];
  const msgDivs = messagesDiv.querySelectorAll('.msg');
  msgDivs.forEach(div => {
    messages.push({
      html: div.innerHTML,
      className: div.className
    });
  });
  localStorage.setItem('tr_messages', JSON.stringify(messages));
}

function loadMessagesFromStorage() {
  const saved = localStorage.getItem('tr_messages');
  if (saved) {
    try {
      const messages = JSON.parse(saved);
      messages.forEach(msg => {
        const div = document.createElement("div");
        div.className = msg.className;
        div.innerHTML = msg.html;
        messagesDiv.appendChild(div);
      });
      messagesDiv.scrollTop = messagesDiv.scrollHeight;
    } catch (err) {
      console.error('Error loading messages from storage:', err);
    }
  }
}

function clearMessagesFromStorage() {
  localStorage.removeItem('tr_messages');
}


function reloadStyle() {
  links = document.getElementsByTagName("link");
  for (i = 0; i < links.length;i++) { 
    link = links[i]; if (link.rel === "stylesheet") {link.href += "?"; }
  }
}


function formatText(text) {
  // Replace [[ and ]] with <span> tags
  // Support [[<@id>text]] or [[<color>text]] formats
  
  let result = text;
  
  // Pattern to match [[@id or [[color or [[ followed by content and closing ]]
  // This regex captures: [[(@id or color)? ... ]]
  result = result.replace(/\[\[(@\w+|#\w+)?\s*/g, (match, modifier) => {
    if (!modifier) {
      // Plain [[ - just opening span
      return '<span>';
    } else if (modifier.startsWith('@')) {
      // [[@id format - create span with id and class 'ref'
      const id = modifier.substring(1); // Remove @ prefix
      // Check if this ID matches the current user's username
      const isSelf = myUsername && id === myUsername;
      const classes = isSelf ? 'ref self' : 'ref';
      return `<span id="${id}" class="${classes}">`;
    } else if (modifier.startsWith('#')) {
      // Hex color format - set font color
      let color = modifier.substring(1); // Remove # prefix
      // If 3-digit hex, expand it to 6-digit
      if (color.length === 3) {
        color = color[0] + color[0] + color[1] + color[1] + color[2] + color[2];
      }
      return `<span style="color: #${color}">`;
    }
  });
  
  // Replace ]] with closing span
  result = result.replace(/\]\]/g, '</span>');  
  return result;
}


function addMessage(text, cls) {
  const div = document.createElement("div");
  div.className = "msg " + (cls || "");
  div.innerHTML = text;
  messagesDiv.appendChild(div);
  
  // Replace content of 'self' spans with 'YOU'
  const selfSpans = div.querySelectorAll('span.self');
  selfSpans.forEach(span => {
    span.textContent = 'you';
  });
  
  // Add click/touch event handlers to all spans with IDs
  const refSpans = div.querySelectorAll('span.ref[id]');
  refSpans.forEach(span => {
    const spanId = span.id;
    
    // Click handler
    span.addEventListener('click', (e) => {
      e.preventDefault();
      addActionChip('@' + spanId, '@' + spanId);
    });
    
    // Touch handler for mobile devices
    span.addEventListener('touchend', (e) => {
      e.preventDefault();
      addActionChip('@' + spanId, '@' + spanId);
    });
  });
  
  messagesDiv.scrollTop = messagesDiv.scrollHeight;
}


socket.on("connect", () => {
  addMessage("<span class='system'>Connected to server</span>");
  
  // Auto-login if we have stored credentials (from cookie or reconnect)
  const u = usernameInput.value.trim();
  const p = lastPassword || passwordInput.value;
  if (myUsername && u && p) {
    console.log("Reconnected - attempting auto-login");
    socket.emit("login", { username: u, password: p });
  }
  
  // Send heartbeat every second
  setInterval(() => {
    socket.emit("heartbeat", { timestamp: Date.now() });
  }, 1000);
  
  // Save messages to localStorage every second
  setInterval(() => {
    saveMessagesToStorage();
  }, 1000);
});


socket.on("connected", data => {
  // server greeting
  console.log("server:", data);
});


socket.on("actions_def", data => {
  // data: {actions: {...}}
  console.log("Received actions:", data.actions);
  const actionsContainer = document.getElementById("actionButtons");
  actionsContainer.innerHTML = ""; // Clear existing buttons
  
  // Group actions by their group property
  const groups = {};
  for (const [actionKey, actionDef] of Object.entries(data.actions || {})) {
    const groupName = actionDef.group || "other";
    if (!groups[groupName]) {
      groups[groupName] = [];
    }
    groups[groupName].push({ key: actionKey, def: actionDef });
  }
  
  // Create group buttons view
  function showGroups() {
    actionsContainer.innerHTML = "";
    
    for (const [groupName, actions] of Object.entries(groups)) {
      const groupBtn = document.createElement("button");
      groupBtn.className = "action-btn group-btn";
      groupBtn.textContent = groupName.charAt(0).toUpperCase() + groupName.slice(1);
      groupBtn.title = "Click to expand " + groupName + " actions";
      
      groupBtn.addEventListener("click", () => {
        showGroupActions(groupName, actions);
      });
      
      actionsContainer.appendChild(groupBtn);
    }
  }
  
  // Show individual actions for a group
  function showGroupActions(groupName, actions) {
    actionsContainer.innerHTML = "";
    
    // Back button
    const backBtn = document.createElement("button");
    backBtn.className = "action-btn back-btn";
    backBtn.textContent = "◀";
    backBtn.style.background = "#6c757d";
    backBtn.addEventListener("click", showGroups);
    actionsContainer.appendChild(backBtn);
    
    // Individual action buttons
    for (const { key: actionKey, def: actionDef } of actions) {
      const btn = document.createElement("button");
      btn.className = "action-btn";
      btn.textContent = actionDef.label;
      btn.title = actionDef.label + " - " + actionDef.description;
      btn.dataset.action = actionKey;
      
      btn.addEventListener("click", () => {
        addActionChip('.' + actionKey, actionDef.label);
      });
      
      actionsContainer.appendChild(btn);
    }
  }
  showGroups();
});


socket.on("login_success", data => {
  myUsername = data.username;
  loginStatus.style.color = "green";
  loginStatus.textContent = "Login successful — welcome " + myUsername;
  document.getElementById("loginBox").style.display = "none";
  chatBox.style.display = "block";
  
  // Save credentials to cookie
  saveCredentials(usernameInput.value.trim(), lastPassword || passwordInput.value);
  
  // Load saved messages from localStorage
  loadMessagesFromStorage();
});


socket.on("login_failed", data => {
  loginStatus.style.color = "red";
  loginStatus.textContent = "Login failed: " + (data.error || "unknown");
});


socket.on("user_joined", data => {
  addMessage("<span class='system'>" + data.username + " joined</span>");
});


socket.on("user_left", data => {
  addMessage("<span class='system'>" + data.username + " left</span>");
});


socket.on("message", data => {
  const safeText = escapeHtml(data.text || "");
  const formattedText = formatText(safeText);
  addMessage(formattedText);
});


socket.on("error", data => {
  addMessage("<span style='color:red'>Error: " + escapeHtml(data.error || "") + "</span>");
});


btnLogin.addEventListener("click", () => {
  const u = usernameInput.value.trim();
  const p = passwordInput.value;
  if (!u || !p) {
    loginStatus.style.color = "red";
    loginStatus.textContent = "username and password required";
    return;
  }
  // Store password for auto-reconnect
  lastPassword = p;
  socket.emit("login", { username: u, password: p });
});


btnLogout.addEventListener("click", () => {
  // Clear credentials and reset UI
  clearCredentials();
  clearMessagesFromStorage();
  myUsername = null;
  lastPassword = null;
  usernameInput.value = "";
  passwordInput.value = "";
  chatBox.style.display = "none";
  document.getElementById("loginBox").style.display = "block";
  messagesDiv.innerHTML = "";
  loginStatus.textContent = "";
  
  // Disconnect and reconnect to clear server state
  socket.disconnect();
  setTimeout(() => socket.connect(), 100);
});


// Simple local registration using /register HTTP endpoint
btnRegister.addEventListener("click", async () => {
  const u = usernameInput.value.trim();
  const p = passwordInput.value;
  if (!u || !p) {
    loginStatus.style.color = "red";
    loginStatus.textContent = "username and password required for register";
    return;
  }
  try {
    const resp = await fetch("/register", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: u, password: p })
    });
    const j = await resp.json();
    if (resp.ok) {
      loginStatus.style.color = "green";
      loginStatus.textContent = "Registered — now click Login";
    } else {
      loginStatus.style.color = "red";
      loginStatus.textContent = j.error || "register failed";
    }
  } catch (err) {
    loginStatus.style.color = "red";
    loginStatus.textContent = "register error: " + err.message;
  }
});


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
  
  socket.emit("message", { text: fullMessage });
  msgInput.value = "";
  clearActionChips();
});


msgInput.addEventListener("keydown", (ev) => {
  if (ev.key === "Enter") {
    sendBtn.click();
  }
});


function escapeHtml(s){
  return s.replace(/[&<>"'\/]/g, function (c) { return ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;','/':'&#x2F;'})[c]; });
}


// Auto-login on page load if credentials are saved
window.addEventListener("DOMContentLoaded", () => {
  const creds = loadCredentials();
  if (creds.username && creds.password) {
    usernameInput.value = creds.username;
    passwordInput.value = creds.password;
    lastPassword = creds.password;
    
    // Trigger login automatically
    setTimeout(() => {
      btnLogin.click();
    }, 500);
  }
});
