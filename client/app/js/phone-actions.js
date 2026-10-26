import { buildPhoneMessagesCommand } from "./commands.js";

export async function refreshPhoneMessages(ctx) {
  try {
    await ctx.sendCommand(buildPhoneMessagesCommand("list"));
  } catch (error) {
    ctx.showError(error);
  }
}

export async function handlePhoneMessagesAction(action, ctx) {
  const { store, sendCommand, showError } = ctx;
  if (action.type === "phone-messages") {
    if (action.action === "open" || action.action === "pick") {
      store.dispatch({ type: "phone-messages-select", threadKey: action.threadKey });
      try {
        await sendCommand(buildPhoneMessagesCommand("open", action.threadKey));
      } catch (error) {
        showError(error);
      }
    } else if (action.action === "new") {
      store.dispatch({ type: "phone-messages-new" });
      try {
        await sendCommand(buildPhoneMessagesCommand("peers"));
      } catch (error) {
        showError(error);
      }
    } else if (action.action === "back") {
      store.dispatch({ type: "phone-messages-back" });
      try {
        await sendCommand(buildPhoneMessagesCommand("list"));
      } catch (error) {
        showError(error);
      }
    }
    return;
  }
  if (action.type === "phone-messages-send") {
    const body = String(action.body || "").trim();
    if (!body || !action.threadKey) return;
    try {
      await sendCommand(buildPhoneMessagesCommand("send", action.threadKey, body));
    } catch (error) {
      showError(error);
    }
  }
}
