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
