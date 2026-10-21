(() => {
  "use strict";

  const recipesRoot = document.getElementById("recipes");
  const detailRoot = document.getElementById("detail");
  const connection = document.getElementById("connection");
  const energyValue = document.getElementById("energy-value");
  const recipeCount = document.getElementById("recipe-count");
  const result = document.getElementById("result");
  const resultCards = document.getElementById("result-cards");
  const resultClose = document.getElementById("result-close");
  const overlay = document.getElementById("craft-overlay");
  const overlayVessel = document.getElementById("craft-vessel");
  const overlayFlight = document.getElementById("craft-flight");
  const overlayTitle = document.getElementById("craft-overlay-title");
  const overlaySubtitle = document.getElementById("craft-overlay-subtitle");
  const reducedMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

  let busy = false;
  let selectedRecipeId = null;
  let preview = null;
  let selections = {};

  function icon(id, className = "icon") {
    return `<svg class="${className}" aria-hidden="true"><use href="#${id}"></use></svg>`;
  }

  function configuredRecipes() {
    const config = TinyActivity.state?.activity?.config || {};
    return Array.isArray(config.recipes) ? config.recipes : [];
  }

  function inventoryImage(cardId) {
    const inventory = TinyActivity.state?.room?.inventory || TinyActivity.state?.user?.inventory || [];
    const stack = inventory.find(item => item.definition?.id === cardId);
    const url = stack?.definition?.image_url;
    return url ? TinyActivity.image(url) : "";
  }

  function imageUrl(item) {
    if (item?.image_url) return TinyActivity.image(item.image_url);
    return item?.card_id ? inventoryImage(item.card_id) : "";
  }

  function outputArt(item) {
    const url = item ? imageUrl(item) : "";
    if (url) return `<img src="${TinyActivity.escape(url)}" alt="">`;
    return icon("icon-pot");
  }

  function recipeAvailability(recipe) {
    const ingredients = Array.isArray(recipe.ingredients) ? recipe.ingredients : [];
    if (!ingredients.length) return { available: true, missing: 0 };
    const missing = ingredients.filter(
      ingredient => Number(ingredient.owned || 0) < Number(ingredient.quantity || 0)
    ).length;
    return { available: missing === 0, missing };
  }

  function renderRecipeList() {
    const recipes = configuredRecipes();
    const unavailable = recipes.filter(recipe => !recipeAvailability(recipe).available).length;
    recipeCount.textContent = `${recipes.length} recipe${recipes.length === 1 ? "" : "s"}${unavailable ? ` · ${unavailable} unavailable` : ""}`;
    if (!recipes.length) {
      const empty = document.createElement("p");
      empty.className = "empty";
      empty.innerHTML = `${icon("icon-pot")} No recipes learned here yet.`;
      recipesRoot.replaceChildren(empty);
      return;
    }
    const nodes = recipes.map(recipe => {
      const output = Array.isArray(recipe.outputs) ? recipe.outputs[0] : null;
      const art = output ? imageUrl(output) : "";
      const cost = Number(recipe.energy_cost || 0);
      const availability = recipeAvailability(recipe);
      const button = document.createElement("button");
      button.type = "button";
      button.className = `recipe-tile${availability.available ? "" : " is-unavailable"}`;
      button.dataset.recipe = recipe.id;
      button.setAttribute("role", "option");
      button.setAttribute("aria-selected", String(recipe.id === selectedRecipeId));
      button.setAttribute(
        "aria-label",
        `${recipe.label || recipe.id}${availability.available ? "" : " (missing ingredients)"}`
      );
      if (!availability.available) {
        button.title = "Missing ingredients — select to see what is needed.";
      }
      button.innerHTML = `
        <span class="tile-art">${art ? `<img src="${TinyActivity.escape(art)}" alt="">` : icon("icon-pot")}</span>
        <span class="tile-label">${TinyActivity.escape(recipe.label || recipe.id)}</span>
        <span class="tile-meta">
          <span class="tile-energy">${icon("icon-bolt")}${cost || 0}</span>
          <span class="tile-status">${availability.available ? `${icon("icon-check")}Ready` : `${icon("icon-warning")}Missing`}</span>
        </span>`;
      button.onclick = () => selectRecipe(recipe.id);
      return button;
    });
    recipesRoot.replaceChildren(...nodes);
  }

  function autoSelect(ingredient) {
    let remaining = ingredient.quantity;
    for (const stack of ingredient.stacks || []) {
      if (remaining <= 0) break;
      const take = Math.min(remaining, stack.quantity);
      selections[stack.stack_id] = take;
      remaining -= take;
    }
  }

  async function selectRecipe(recipeId) {
    if (busy) return;
    busy = true;
    selectedRecipeId = recipeId;
    renderRecipeList();
    detailRoot.innerHTML = `<div class="detail-loading"><span class="spinner"></span><span>Opening the recipe…</span></div>`;
    try {
      const response = await TinyActivity.command(`.craft_preview ${recipeId}`);
      preview = response.payload?.preview || null;
      selections = {};
      for (const ingredient of preview?.ingredients || []) autoSelect(ingredient);
      renderDetail();
    } catch (error) {
      preview = null;
      renderDetail();
      TinyActivity.toast(error.message || "That recipe could not be loaded.", true);
    } finally {
      busy = false;
      renderDetail();
    }
  }

  function selectedTotal(cardId) {
    const ingredient = (preview?.ingredients || []).find(item => item.card_id === cardId);
    if (!ingredient) return 0;
    return (ingredient.stacks || []).reduce((total, stack) => total + (selections[stack.stack_id] || 0), 0);
  }

  function isReady() {
    if (!preview) return false;
    return (preview.ingredients || []).every(ingredient => selectedTotal(ingredient.card_id) === ingredient.quantity);
  }

  function stacksMarkup(ingredient) {
    const rows = (ingredient.stacks || []).map((stack, index) => {
      const value = selections[stack.stack_id] || 0;
      const equipped = stack.equipped ? `<em class="equipped">Equipped</em>` : "";
      return `<label class="stack-row">
        <span class="stack-copy">${equipped}<span class="stack-id" title="${TinyActivity.escape(stack.stack_id)}">Stack ${index + 1}</span></span>
        <input type="number" inputmode="numeric" min="0" max="${stack.quantity}" value="${value}" data-stack="${TinyActivity.escape(stack.stack_id)}" aria-label="Quantity from stack ${index + 1}">
        <span class="stack-have">of ${stack.quantity}</span>
      </label>`;
    }).join("");
    return rows || `<p class="empty smallprint">None owned yet.</p>`;
  }

  function renderDetail() {
    if (!preview) {
      detailRoot.innerHTML = `
        <div class="detail-empty">
          ${icon("icon-pot", "icon detail-empty-icon")}
          <p>Pick a recipe to see what it needs.</p>
        </div>`;
      return;
    }
    const output = (preview.output || [])[0];
    const outputQuantity = output?.quantity || 1;
    const ingredients = (preview.ingredients || []).map(ingredient => {
      const total = selectedTotal(ingredient.card_id);
      const satisfied = total === ingredient.quantity;
      const art = imageUrl(ingredient);
      const artMarkup = art
        ? `<img src="${TinyActivity.escape(art)}" alt="">`
        : `<span class="ingredient-art-empty">${icon("icon-pot")}</span>`;
      return `<section class="ingredient-card ${satisfied ? "is-ready" : ""}" data-ingredient="${TinyActivity.escape(ingredient.card_id)}">
        <div class="ingredient-art">${artMarkup}</div>
        <div class="ingredient-main">
          <div class="ingredient-head">
            <h3>${TinyActivity.escape(ingredient.label)}</h3>
            <span class="need ${satisfied ? "ok" : "missing"}" data-need="${TinyActivity.escape(ingredient.card_id)}" data-required="${ingredient.quantity}">${total}/${ingredient.quantity}</span>
          </div>
          <div class="stacks">${stacksMarkup(ingredient)}</div>
        </div>
      </section>`;
    }).join("");
    const cost = Number(preview.energy_cost || 0);
    detailRoot.innerHTML = `
      <div class="detail-hero">
        <div class="detail-art">${outputArt(output)}</div>
        <div class="detail-copy">
          <h2>${TinyActivity.escape(preview.label)}</h2>
          <p class="muted">${TinyActivity.escape(preview.description || "")}</p>
          <div class="detail-stats">
            <span class="detail-stat">${icon("icon-bolt")}${cost ? `${cost} Energy` : "No Energy cost"}</span>
            <span class="detail-stat output-stat">${icon("icon-pot")}${TinyActivity.escape(output?.label || "Output")} ×${outputQuantity}</span>
          </div>
        </div>
      </div>
      <div class="ingredient-grid">${ingredients}</div>
      <div class="detail-actions">
        <button type="button" class="primary craft-button" id="confirm" ${isReady() && !busy ? "" : "disabled"}>
          ${icon("icon-pot")} Craft ${TinyActivity.escape(output?.label || "recipe")}
        </button>
      </div>`;
    detailRoot.querySelectorAll("input[data-stack]").forEach(input => {
      input.oninput = () => {
        const stackId = input.dataset.stack;
        const quantity = Math.max(0, Math.min(Number(input.max), Number(input.value || 0)));
        input.value = String(quantity);
        selections[stackId] = quantity;
        refreshReadiness();
      };
    });
    const confirm = detailRoot.querySelector("#confirm");
    if (confirm) confirm.onclick = () => craft();
  }

  function refreshReadiness() {
    detailRoot.querySelectorAll("[data-need]").forEach(node => {
      const cardId = node.dataset.need;
      const required = Number(node.dataset.required || 0);
      const total = selectedTotal(cardId);
      node.textContent = `${total}/${required}`;
      node.classList.toggle("ok", total === required);
      node.classList.toggle("missing", total !== required);
      const card = node.closest(".ingredient-card");
      if (card) card.classList.toggle("is-ready", total === required);
    });
    const confirm = detailRoot.querySelector("#confirm");
    if (confirm) confirm.disabled = !isReady() || busy;
  }

  function selectedTokens() {
    return Object.entries(selections)
      .filter(([, quantity]) => quantity > 0)
      .map(([stackId, quantity]) => `${stackId}:${quantity}`);
  }

  function delay(milliseconds) {
    return new Promise(resolve => window.setTimeout(resolve, milliseconds));
  }

  function startCraftAnimation(snapshot) {
    if (reducedMotion) return;
    overlayTitle.textContent = "Cooking…";
    overlaySubtitle.textContent = snapshot.label;
    const output = (snapshot.output || [])[0];
    const outputPicture = output ? imageUrl(output) : "";
    overlayVessel.innerHTML = outputPicture
      ? `<img src="${TinyActivity.escape(outputPicture)}" alt="">`
      : icon("icon-pot");
    overlayFlight.replaceChildren();
    const ingredients = snapshot.ingredients || [];
    const radius = Math.min(150, Math.max(94, Math.min(window.innerWidth, window.innerHeight) * 0.22));
    ingredients.forEach((ingredient, index) => {
      const art = imageUrl(ingredient);
      if (!art) return;
      const angle = (index / Math.max(1, ingredients.length)) * Math.PI * 2 - Math.PI / 2;
      const flyer = document.createElement("span");
      flyer.className = "craft-flyer";
      flyer.style.setProperty("--x", `${Math.cos(angle) * radius}px`);
      flyer.style.setProperty("--y", `${Math.sin(angle) * radius * 0.82}px`);
      flyer.style.setProperty("--rot", `${Math.round(Math.cos(angle) * 22)}deg`);
      flyer.style.setProperty("--delay", `${index * 0.07}s`);
      const img = document.createElement("img");
      img.src = art;
      img.alt = "";
      flyer.append(img);
      overlayFlight.append(flyer);
    });
    overlay.hidden = false;
  }

  function endCraftAnimation() {
    overlay.hidden = true;
    overlayFlight.replaceChildren();
    overlayVessel.replaceChildren();
  }

  async function craft() {
    if (busy || !preview || !isReady()) return;
    const snapshot = {
      recipe_id: preview.recipe_id,
      label: preview.label,
      ingredients: preview.ingredients.map(ingredient => ({ ...ingredient })),
      output: preview.output.map(item => ({ ...item })),
    };
    busy = true;
    renderDetail();
    startCraftAnimation(snapshot);
    try {
      const [response] = await Promise.all([
        TinyActivity.command(`.craft_make ${snapshot.recipe_id} ${selectedTokens().join(" ")}`),
        delay(reducedMotion ? 0 : 860),
      ]);
      endCraftAnimation();
      showResult(response.payload?.craft?.outputs || snapshot.output);
      busy = false;
      await selectRecipe(snapshot.recipe_id);
    } catch (error) {
      endCraftAnimation();
      TinyActivity.toast(error.message || "The craft was rejected.", true);
    } finally {
      busy = false;
      if (preview) renderDetail();
    }
  }

  function showResult(outputs) {
    resultCards.replaceChildren(...outputs.map(item => {
      const art = imageUrl(item);
      const node = document.createElement("figure");
      node.className = "result-card";
      node.innerHTML = `${art ? `<img src="${TinyActivity.escape(art)}" alt="">` : ""}<figcaption>${TinyActivity.escape(item.label)} ×${item.quantity}</figcaption>`;
      return node;
    }));
    result.hidden = false;
    TinyActivity.celebrate();
    resultClose.focus({ preventScroll: true });
  }

  function closeResult() {
    result.hidden = true;
    detailRoot.querySelector("#confirm")?.focus({ preventScroll: true });
  }

  function render() {
    const state = TinyActivity.state;
    if (!state) return;
    connection.textContent = "";
    const counters = state.user?.counters || {};
    energyValue.textContent = `${Math.round(counters.energy ?? 0)} Energy`;
    const recipes = configuredRecipes();
    if (selectedRecipeId && !recipes.some(recipe => recipe.id === selectedRecipeId)) {
      selectedRecipeId = null;
      preview = null;
    }
    renderRecipeList();
    if (selectedRecipeId && preview) renderDetail();
  }

  resultClose.onclick = closeResult;
  document.addEventListener("keydown", event => {
    if (event.key === "Escape" && !result.hidden) closeResult();
  });

  TinyActivity.subscribe(render);
})();
