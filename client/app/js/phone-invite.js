/** Fetch a fresh guest invite for the Phone's Guest Invite app. */
export async function loadGuestInvite({ api, store, onError }) {
  store.dispatch({ type: "guest-invite-loading" });
  try {
    const invite = await api.createGuestInvite();
    store.dispatch({ type: "guest-invite-loaded", invite });
    return invite;
  } catch (error) {
    store.dispatch({ type: "guest-invite-error", error: error?.message || String(error) });
    if (onError) onError(error);
    return null;
  }
}
