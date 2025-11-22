const socket = io();

const usernameInput = document.getElementById("username");
const passwordInput = document.getElementById("password");
const btnLogin = document.getElementById("btnLogin");
const btnRegister = document.getElementById("btnRegister");
const loginStatus = document.getElementById("loginStatus");
const chatBox = document.getElementById("chatBox");
const statusDisplay = document.getElementById("statusDisplay");
const messagesDiv = document.getElementById("messages");
const msgInput = document.getElementById("msgInput");
const sendBtn = document.getElementById("sendBtn");
const btnLogout = document.getElementById("btnLogout");
const actionsChipsContainer = document.getElementById("actionsChips");
const connectionIndicator = document.getElementById("connectionIndicator");

let myUsername = null;
let lastPassword = null; // Store password for auto-reconnect
let selectedActions = []; // Array of {key, label} for selected actions
let connectionState = "connecting"; // connecting, connected, disconnected
let connectionTime = null;


socket.on("connect", () => {
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

socket.on("disconnect", () => {
  setConnectionState("disconnected");
});

socket.on("connect_error", () => {
  setConnectionState("disconnected");
});

socket.on("connected", data => {
  setConnectionState("connected");
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
  loadInputState();
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


socket.on("reload_styles", data => {
  reloadStyle();
});

socket.on("reload_client", data => {
  saveInputState();
  window.location.reload();
});

socket.on("set_skin", data => {
  // data: {skin: "skinname"}
  const skinName = data.skin || "base";
  
  // Find the main stylesheet link element
  const links = document.getElementsByTagName("link");
  for (let i = 0; i < links.length; i++) {
    const link = links[i];
    if (link.rel === "stylesheet" && link.id === "skin-style") {
      // Update the href to the new skin CSS file
      link.href = "/app/" + skinName + ".css?" + Date.now();
      console.log("Skin changed to:", skinName);
      break;
    }
  }
});

socket.on("update_status", data => {
  // data is a dict/object of items, each with at least a 'label' field
  statusDisplay.innerHTML = "";
  
  for (const [key, item] of Object.entries(data || {})) {
    const div = document.createElement("div");
    div.className = "status-item";
    div.textContent = item.label || "";
    statusDisplay.appendChild(div);
  }
});

socket.on("update_view", data => {
  // data: {view: "viewName", format: "text", label: "", description: "", image: ""}
  const viewName = data.view;
  const format = data.format || "text";
  const label = formatText(data.label || "");
  const description = formatText(data.description || "");
  const image = data.image || "";
  
  if (!viewName) {
    console.error("update_view: missing view name");
    return;
  }
  
  // Find or create the view div
  const viewId = "view_" + viewName;
  let viewDiv = document.getElementById(viewId);
  
  if (!viewDiv) {
    // Create the view div if it doesn't exist
    viewDiv = document.createElement("div");
    viewDiv.id = viewId;
    viewDiv.className = "view-container";
    
    // Insert it in the chatBox, after statusDisplay but before messages
    const chatBoxEl = document.getElementById("chatBox");
    const messagesEl = document.getElementById("messages");
    chatBoxEl.insertBefore(viewDiv, messagesEl);
  }
  
  // Clear existing content
  viewDiv.innerHTML = "";
  
  // Create sub-sections for image, label, and description
  if (image) {
    const img = document.createElement("img");
    img.src = "/world/images/" + image;
    img.alt = label || "Room image";
    img.className = "view-image";
    viewDiv.appendChild(img);
  }
  
  if (label) {
    const labelDiv = document.createElement("div");
    labelDiv.className = "view-label";
    
    // Format label with first character uppercase
    const labelText = label.trim();
    if (labelText.length > 0) {
      const firstChar = labelText.charAt(0).toUpperCase();
      const restOfText = labelText.substring(1);
      labelDiv.innerHTML = firstChar + restOfText;
    } else {
      labelDiv.innerHTML = label;
    }
    
    viewDiv.appendChild(labelDiv);
  }
  
  if (description) {
    const descDiv = document.createElement("div");
    descDiv.className = "view-description";
    
    // Format description with drop cap (first character larger)
    const descText = description.trim();
    if (descText.length > 0) {
      const firstChar = descText.charAt(0).toUpperCase();
      const restOfText = descText.substring(1);
      descDiv.innerHTML = '<span class="drop-cap">' + firstChar + '</span>' + restOfText;
    } else {
      descDiv.innerHTML = description;
    }
    
    viewDiv.appendChild(descDiv);
  }
  
  // viewDiv.appendChild(textContainer);
  attachRefEventHandlers(viewDiv); 
});

socket.on("error", data => {
  addMessage("<span style='color:red'>Error: " + escapeHtml(data.error || "") + "</span>");
});

