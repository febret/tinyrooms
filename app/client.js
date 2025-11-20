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

let myUsername = null;
let lastPassword = null; // Store password for auto-reconnect

function addMessage(text, cls) {
  const div = document.createElement("div");
  div.className = "msg " + (cls || "");
  div.innerHTML = text;
  messagesDiv.appendChild(div);
  messagesDiv.scrollTop = messagesDiv.scrollHeight;
}

socket.on("connect", () => {
  addMessage("<span class='system'>Connected to server</span>");
  
  // Auto-login if we have stored credentials
  const u = usernameInput.value.trim();
  const p = lastPassword || passwordInput.value;
  if (myUsername && u && p) {
    console.log("Reconnected - attempting auto-login");
    socket.emit("login", { username: u, password: p });
  }
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
  
  // Create a button for each action
  for (const [actionKey, actionDef] of Object.entries(data.actions || {})) {
    const btn = document.createElement("button");
    btn.className = "action-btn";
    btn.textContent = actionDef.label + " " + actionDef.description;
    btn.title = actionDef.description;
    btn.dataset.action = actionKey;
    
    btn.addEventListener("click", () => {
      msgInput.value = "." + actionKey + " ";
    });
    
    actionsContainer.appendChild(btn);
  }
});

socket.on("login_success", data => {
  myUsername = data.username;
  loginStatus.style.color = "green";
  loginStatus.textContent = "Login successful — welcome " + myUsername;
  document.getElementById("loginBox").style.display = "none";
  chatBox.style.display = "block";
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
  addMessage(safeText);
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
  if (!t) return;
  socket.emit("message", { text: t });
  msgInput.value = "";
});

msgInput.addEventListener("keydown", (ev) => {
  if (ev.key === "Enter") {
    sendBtn.click();
  }
});

function escapeHtml(s){
  return s.replace(/[&<>"'\/]/g, function (c) { return ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;','/':'&#x2F;'})[c]; });
}
