(() => {
  "use strict";

  const recipesRoot = document.getElementById("recipes");
  const detailRoot = document.getElementById("detail");
  const connection = document.getElementById("connection");
  const energy = document.getElementById("energy");
  const result = document.getElementById("result");
  const resultCards = document.getElementById("result-cards");

  let busy = false;
  let selectedRecipeId = null;
  let preview = null;
  let selections = {};

  function configuredRecipes() {
    const config = TinyActivity.state?.activity?.config || {};
    return Array.isArray(config.recipes) ? config.recipes : [];
  }

  function image(cardId) {
    const inventory = TinyActivity.state?.room?.inventory || TinyActivity.state?.user?.inventory || [];
    const stack = inventory.find(item => item.definition?.id === cardId);
    return stack?.definition?.image_url ? TinyActivity.image(stack.definition.image_url) : "";
  }

  function renderRecipeList() {
    const recipes = configuredRecipes();
    const nodes = recipes.map(recipe => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "recipe-button";
      button.dataset.recipe = recipe.id;
      button.setAttribute("role", "option");
      button.setAttribute("aria-selected", String(recipe.id === selectedRecipeId));
      button.innerHTML = `<strong>${TinyActivity.escape(recipe.label || recipe.id)}</strong><span>${TinyActivity.escape(recipe.description || "")}</span>`;
      button.onclick = () => selectRecipe(recipe.id);
      return button;
    });
    recipesRoot.replaceChildren(...nodes);
    if (!recipes.length) {
      const empty = document.createElement("p");
      empty.className = "empty";
      empty.textContent = "This station has no recipes.";
      recipesRoot.replaceChildren(empty);
    }
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
    try {
      const response = await TinyActivity.command(`.craft_preview ${recipeId}`);
      preview = response.payload?.preview || null;
      selectedRecipeId = recipeId;
      selections = {};
      for (const ingredient of preview?.ingredients || []) autoSelect(ingredient);
      renderRecipeList();
      renderDetail();
    } catch (error) {
      TinyActivity.toast(error.message || "That recipe could not be loaded.", true);
    } finally {
      busy = false;
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

  function renderDetail() {
    if (!preview) {
      detailRoot.innerHTML = `<p class="empty">Choose a recipe to begin.</p>`;
      return;
    }
    const output = (preview.output || []).map(item => {
      const art = image(item.card_id);
      const img = art ? `<img src="${art}" alt="">` : "";
      return `<figure class="output-card">${img}<figcaption>${TinyActivity.escape(item.label)} ×${item.quantity}</figcaption></figure>`;
    }).join("");
    const ingredients = (preview.ingredients || []).map(ingredient => {
      const stacks = (ingredient.stacks || []).map(stack => {
        const value = selections[stack.stack_id] || 0;
        const equipped = stack.equipped ? `<em class="equipped">equipped</em>` : "";
        return `<label class="stack-row">
          <span class="stack-copy">${equipped}<span>${TinyActivity.escape(stack.stack_id)}</span></span>
          <input type="number" min="0" max="${stack.quantity}" value="${value}" data-stack="${TinyActivity.escape(stack.stack_id)}" aria-label="Quantity from ${TinyActivity.escape(stack.stack_id)}">
          <span class="stack-have">of ${stack.quantity}</span>
        </label>`;
      }).join("") || `<p class="empty smallprint">None owned.</p>`;
      const total = selectedTotal(ingredient.card_id);
      const satisfied = total === ingredient.quantity;
      return `<section class="ingredient">
        <h3>${TinyActivity.escape(ingredient.label)} <span class="need ${satisfied ? "ok" : "missing"}" data-need="${TinyActivity.escape(ingredient.card_id)}" data-required="${ingredient.quantity}">${total}/${ingredient.quantity}</span></h3>
        <div class="stacks">${stacks}</div>
      </section>`;
    }).join("");
    detailRoot.innerHTML = `
      <h2>${TinyActivity.escape(preview.label)}</h2>
      <p class="muted">${TinyActivity.escape(preview.description || "")}</p>
      <div class="output">${output}</div>
      <div class="ingredients">${ingredients}</div>
      <div class="actions">
        <span class="cost">${preview.energy_cost ? `${preview.energy_cost} Energy` : "No Energy cost"}</span>
        <button type="button" class="primary" id="confirm" ${isReady() && !busy ? "" : "disabled"}>Craft</button>
      </div>`;
    detailRoot.querySelectorAll("input[data-stack]").forEach(input => {
      input.oninput = () => {
        const stackId = input.dataset.stack;
        const quantity = Math.max(0, Math.min(Number(input.max), Number(input.value || 0)));
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
    });
    const confirm = detailRoot.querySelector("#confirm");
    if (confirm) confirm.disabled = !isReady() || busy;
  }

  function selectedTokens() {
    return Object.entries(selections)
      .filter(([, quantity]) => quantity > 0)
      .map(([stackId, quantity]) => `${stackId}:${quantity}`);
  }

  async function craft() {
    if (busy || !preview || !isReady()) return;
    busy = true;
    renderDetail();
    try {
      const tokens = selectedTokens();
      const response = await TinyActivity.command(`.craft_make ${preview.recipe_id} ${tokens.join(" ")}`);
      showResult(response.payload?.craft?.outputs || []);
      await selectRecipe(preview.recipe_id);
    } catch (error) {
      TinyActivity.toast(error.message || "The craft was rejected.", true);
    } finally {
      busy = false;
      renderDetail();
    }
  }

  function showResult(outputs) {
    resultCards.replaceChildren(...outputs.map(item => {
      const art = image(item.card_id);
      const node = document.createElement("figure");
      node.className = "result-card";
      node.innerHTML = `${art ? `<img src="${art}" alt="">` : ""}<figcaption>${TinyActivity.escape(item.label)} ×${item.quantity}</figcaption>`;
      return node;
    }));
    result.hidden = false;
    TinyActivity.celebrate();
    document.getElementById("result-close").focus({ preventScroll: true });
  }

  function render() {
    const state = TinyActivity.state;
    if (!state) return;
    connection.textContent = "";
    const counters = state.user?.counters || {};
    energy.textContent = `${Math.round(counters.energy ?? 0)} Energy`;
    renderRecipeList();
    if (selectedRecipeId) renderDetail();
  }

  document.getElementById("result-close").onclick = () => { result.hidden = true; };
  document.addEventListener("keydown", event => {
    if (event.key === "Escape" && !result.hidden) result.hidden = true;
  });

  TinyActivity.subscribe(render);
})();
