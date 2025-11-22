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


// localStorage for messages
function saveMessagesToStorage() {
  const messages = [];
  const msgDivs = messagesDiv.querySelectorAll('.msg');
  
  // Get only the last 50 messages
  const divsArray = Array.from(msgDivs);
  const lastMessages = divsArray.slice(-50);
  
  lastMessages.forEach(div => {
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
      attachRefEventHandlers(messagesDiv);
    } catch (err) {
      console.error('Error loading messages from storage:', err);
    }
  }
}


function clearMessagesFromStorage() {
  localStorage.removeItem('tr_messages');
}


// Save/restore input state for reload
function saveInputState() {
  localStorage.setItem('tr_input', msgInput.value);
  localStorage.setItem('tr_actions', JSON.stringify(selectedActions));
}

function loadInputState() {
  const savedInput = localStorage.getItem('tr_input');
  const savedActions = localStorage.getItem('tr_actions');
  
  if (savedInput) {
    msgInput.value = savedInput;
    localStorage.removeItem('tr_input');
  }
  
  if (savedActions) {
    try {
      selectedActions = JSON.parse(savedActions);
      renderActionChips();
      localStorage.removeItem('tr_actions');
    } catch (err) {
      console.error('Error loading actions:', err);
    }
  }
}