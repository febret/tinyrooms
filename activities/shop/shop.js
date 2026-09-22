(() => {
  "use strict";

  const packsRoot = document.getElementById("packs");
  const balance = document.getElementById("balance");
  const connection = document.getElementById("connection");
  const reveal = document.getElementById("reveal");
  const revealCards = document.getElementById("reveal-cards");
  const revealTitle = document.getElementById("reveal-title");
  const confirm = document.getElementById("confirm");
  const confirmText = document.getElementById("confirm-text");

  let busy = false;
  let pendingPack = null;

  function operationId() {
    return `pack-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
  }

  function packCard(pack) {
    const node = document.createElement("article");
    node.className = "pack-card";
    node.innerHTML = `
      <div class="pack-art" style="background-image:url('${TinyActivity.escape(pack.backImageUrl || "")}')"></div>
      <h3>${TinyActivity.escape(pack.label)}</h3>
      <p>${TinyActivity.escape(pack.description || "")}</p>
      <p class="pack-meta">${pack.size} cards · ${pack.price} Bops</p>
      <button type="button" class="primary buy">Buy</button>
    `;
    node.querySelector(".buy").onclick = () => askConfirm(pack);
    return node;
  }

  function render() {
    const state = TinyActivity.state;
    if (!state) return;
    connection.textContent = "";
    balance.textContent = `${state.user?.bops ?? 0} Bops`;
    packsRoot.replaceChildren(...(state.user?.packs || []).map(packCard));
  }

  function askConfirm(pack) {
    const bops = TinyActivity.state?.user?.bops ?? 0;
    if (bops < pack.price) {
      TinyActivity.toast(`You need ${pack.price - bops} more Bops for that pack.`, true);
      return;
    }
    pendingPack = pack;
    confirmText.textContent = `Buy ${pack.label} for ${pack.price} Bops?`;
    confirm.hidden = false;
    document.getElementById("confirm-ok").focus();
  }

  async function buy(pack) {
    if (busy || !pack) return;
    busy = true;
    try {
      const response = await TinyActivity.command(`.buy_pack ${pack.id} ${operationId()}`);
      const purchase = response.payload?.purchase;
      if (purchase) showReveal(purchase.cards || []);
      render();
    } catch (error) {
      TinyActivity.toast(error.message || "The purchase was rejected.", true);
    } finally {
      busy = false;
    }
  }

  function showReveal(cards) {
    revealTitle.textContent = `Your ${cards.length} cards`;
    revealCards.replaceChildren(...cards.map(card => {
      const node = document.createElement("figure");
      node.className = "reveal-card";
      node.innerHTML = `<img src="${TinyActivity.image(card.image_url)}" alt="${TinyActivity.escape(card.label)}"><figcaption>${TinyActivity.escape(card.label)}</figcaption>`;
      return node;
    }));
    reveal.hidden = false;
    reveal.scrollTop = 0;
    const panel = reveal.querySelector(".reveal-panel");
    if (panel) panel.scrollTop = 0;
    TinyActivity.celebrate();
    document.getElementById("reveal-close").focus({ preventScroll: true });
  }

  document.getElementById("reveal-close").onclick = () => { reveal.hidden = true; };
  document.getElementById("confirm-cancel").onclick = () => { confirm.hidden = true; pendingPack = null; };
  document.getElementById("confirm-ok").onclick = () => {
    const pack = pendingPack;
    confirm.hidden = true;
    pendingPack = null;
    buy(pack);
  };
  document.addEventListener("keydown", event => {
    if (event.key !== "Escape") return;
    if (!confirm.hidden) { confirm.hidden = true; pendingPack = null; }
    else if (!reveal.hidden) reveal.hidden = true;
  });

  TinyActivity.subscribe(render);
})();
