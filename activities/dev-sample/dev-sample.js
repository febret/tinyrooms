const Tiny = window.TinyActivity;
const title = document.querySelector("#title");
const stateView = document.querySelector("#state");
const commandInput = document.querySelector("#command");
const connection = document.querySelector("#connection");

const template = new URLSearchParams(window.location.search).get("template") || "dev-sample";
const TITLES = {
  "dev-sample": "Development Activity",
  "lazor-rush": "Lazor Rush Preview",
  "crafting": "Crafting Preview",
  "shop": "Shop Preview",
};

title.textContent = TITLES[template] || "Development Activity";

function renderState(state) {
  connection.textContent = state?.room
    ? `Ready in ${state.room.label || "your room"}.`
    : state?.user ? "Ready. No room is active." : "Waiting for Tinyrooms…";
  stateView.textContent = JSON.stringify({
    user: state?.user?.username,
    room: state?.room?.label,
    activity: state?.activity?.kind,
    inventoryCount: state?.room?.inventory?.length || 0,
  }, null, 2);
}

document.querySelector("#notify").onclick = () => {
  Tiny.notify(`${title.textContent} needs attention`);
};

document.querySelector("#say").onclick = async () => {
  try {
    await Tiny.command(`.say "Hello from ${title.textContent}!"`);
    Tiny.toast("Sent a room message.");
  } catch (error) {
    Tiny.toast(error instanceof Error ? error.message : String(error), true);
  }
};

document.querySelector("#celebrate").onclick = () => {
  Tiny.celebrate();
};

document.querySelector("#countdown").onclick = () => {
  Tiny.toast("Timer started.");
  window.setTimeout(() => Tiny.notify(`${title.textContent} timer finished`), 8000);
};

document.querySelector("#run").onclick = async () => {
  try {
    const result = await Tiny.command(commandInput.value);
    Tiny.toast(result.message || "Command completed.");
  } catch (error) {
    Tiny.toast(error instanceof Error ? error.message : String(error), true);
  }
};

Tiny.subscribe(renderState);
