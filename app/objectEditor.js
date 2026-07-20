// Object / Create-Thing editor module

let objectEditorState = {
  mode: "closed",
  description: "",
  availableSprites: [],
  currentSprite: null,
  imagePath: null,
  imageUrl: null,
  generatingImage: false,
  creating: false,
};

let objectCreatorPage;
let objectCreatorDescription;
let objectCreatorSpriteList;
let objectCreatorImagePreview;
let objectCreatorError;
let btnObjectCreatorGenerateImage;
let btnObjectCreatorCreate;
let btnObjectCreatorClose;
let btnObjectCreatorDone;
let objectEditorInitialized = false;

let objectEditorSocket;
let objectEditorRestAuthToken;

function bindObjectEditorDomElements() {
  objectCreatorPage = document.getElementById("objectCreatorPage");
  objectCreatorDescription = document.getElementById("objectCreatorDescription");
  objectCreatorSpriteList = document.getElementById("objectCreatorSpriteList");
  objectCreatorImagePreview = document.getElementById("objectCreatorImagePreview");
  objectCreatorError = document.getElementById("objectCreatorError");
  btnObjectCreatorGenerateImage = document.getElementById("btnObjectCreatorGenerateImage");
  btnObjectCreatorCreate = document.getElementById("btnObjectCreatorCreate");
  btnObjectCreatorClose = document.getElementById("btnObjectCreatorClose");
  btnObjectCreatorDone = document.getElementById("btnObjectCreatorDone");
  return !!(
    objectCreatorPage &&
    objectCreatorDescription &&
    objectCreatorSpriteList &&
    objectCreatorImagePreview &&
    objectCreatorError &&
    btnObjectCreatorGenerateImage &&
    btnObjectCreatorCreate &&
    btnObjectCreatorClose &&
    btnObjectCreatorDone
  );
}

function initObjectEditor(clientSocket, clientRestAuthToken) {
  objectEditorSocket = clientSocket;
  objectEditorRestAuthToken = clientRestAuthToken;
  if (!bindObjectEditorDomElements() || objectEditorInitialized) {
    return;
  }
  btnObjectCreatorCreate.addEventListener("click", createThingFromEditor);
  btnObjectCreatorClose.addEventListener("click", closeObjectCreator);
  btnObjectCreatorDone.addEventListener("click", closeObjectCreator);
  btnObjectCreatorGenerateImage.addEventListener("click", generateObjectImage);
  objectCreatorDescription.addEventListener("input", () => {
    objectEditorState.description = objectCreatorDescription.value;
  });
  objectEditorInitialized = true;
}

function resetObjectEditorState() {
  objectEditorState = {
    mode: "closed",
    description: "",
    availableSprites: [],
    currentSprite: null,
    imagePath: null,
    imageUrl: null,
    generatingImage: false,
    creating: false,
  };
  if (!bindObjectEditorDomElements()) {
    return;
  }
  objectCreatorDescription.value = "";
  renderObjectCreator();
}

async function fetchObjectEditorJson(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (objectEditorRestAuthToken) {
    headers["X-TR-Auth"] = objectEditorRestAuthToken;
  }
  const response = await fetch(path, { ...options, headers });
  const payload = await response.json();
  if (!response.ok || payload.ok === false) {
    throw new Error(payload.error || `request failed: ${response.status}`);
  }
  return payload;
}

async function openObjectCreator() {
  objectEditorState.mode = "editing";
  objectEditorState.description = objectCreatorDescription ? objectCreatorDescription.value : "";
  objectCreatorError.textContent = "";
  objectCreatorPage.style.display = "flex";
  renderObjectCreator();
  try {
    const profile = await fetchObjectEditorJson("/api/object-editor/profile");
    objectEditorState.availableSprites = profile.available_sprites || [];
    renderObjectCreator();
  } catch (err) {
    objectCreatorError.textContent = err.message;
    renderObjectCreator();
  }
}

function closeObjectCreator() {
  objectCreatorPage.style.display = "none";
  objectEditorState.mode = "closed";
}

function createObjectSpritePreview(option) {
  const preview = document.createElement("div");
  preview.className = "character-sprite-preview";
  if (option.frame) {
    preview.classList.add("character-sprite-preview-frame");
    preview.style.width = `${option.frame.width || 32}px`;
    preview.style.height = `${option.frame.height || 32}px`;
    preview.style.backgroundImage = `url("${resolveAssetUrl(option.image_url || "")}")`;
    preview.style.backgroundPosition = `-${option.frame.x || 0}px -${option.frame.y || 0}px`;
    if (option.background_color) {
      preview.style.backgroundColor = option.background_color;
    }
    return preview;
  }
  const img = document.createElement("img");
  img.src = resolveAssetUrl(option.image_url || "");
  img.alt = option.label || option.sprite_id || "sprite";
  preview.appendChild(img);
  return preview;
}

function renderObjectCreator() {
  if (!objectCreatorSpriteList || !objectCreatorImagePreview) {
    return;
  }
  const busy = objectEditorState.generatingImage || objectEditorState.creating;
  objectCreatorDescription.disabled = busy;
  btnObjectCreatorGenerateImage.disabled = busy;
  btnObjectCreatorCreate.disabled = busy;

  // Sprite list
  objectCreatorSpriteList.innerHTML = "";

  const noSpriteCard = document.createElement("button");
  noSpriteCard.type = "button";
  noSpriteCard.className = "character-sprite-card character-sprite-card-default";
  if (!objectEditorState.currentSprite) noSpriteCard.classList.add("selected");
  noSpriteCard.disabled = busy;
  noSpriteCard.addEventListener("click", () => {
    objectEditorState.currentSprite = null;
    renderObjectCreator();
  });
  const noSpriteLabel = document.createElement("div");
  noSpriteLabel.className = "character-sprite-label";
  noSpriteLabel.textContent = "Use image only";
  noSpriteCard.appendChild(noSpriteLabel);
  const noSpriteMeta = document.createElement("div");
  noSpriteMeta.className = "character-sprite-meta";
  noSpriteMeta.textContent = "Image required";
  noSpriteCard.appendChild(noSpriteMeta);
  objectCreatorSpriteList.appendChild(noSpriteCard);

  for (const option of objectEditorState.availableSprites) {
    const card = document.createElement("button");
    card.type = "button";
    card.className = "character-sprite-card";
    if (objectEditorState.currentSprite === option.sprite_ref) card.classList.add("selected");
    card.disabled = busy;
    card.addEventListener("click", () => {
      objectEditorState.currentSprite = option.sprite_ref;
      renderObjectCreator();
    });
    card.appendChild(createObjectSpritePreview(option));
    const label = document.createElement("div");
    label.className = "character-sprite-label";
    label.textContent = option.label || option.sprite_id || option.filename || "sprite";
    card.appendChild(label);
    const meta = document.createElement("div");
    meta.className = "character-sprite-meta";
    meta.textContent = `${option.scope}:${option.filename}/${option.sprite_id}`;
    card.appendChild(meta);
    objectCreatorSpriteList.appendChild(card);
  }

  // Image preview
  objectCreatorImagePreview.innerHTML = "";
  objectCreatorImagePreview.classList.toggle("is-busy", objectEditorState.generatingImage);
  if (objectEditorState.imageUrl) {
    const img = document.createElement("img");
    img.src = resolveAssetUrl(objectEditorState.imageUrl);
    img.alt = "Generated object image";
    objectCreatorImagePreview.appendChild(img);
  } else {
    const empty = document.createElement("div");
    empty.className = "character-main-image-empty";
    empty.textContent = "No image yet. Generate one or pick a sprite.";
    objectCreatorImagePreview.appendChild(empty);
  }
}

async function generateObjectImage() {
  const description = (objectCreatorDescription.value || "").trim();
  if (!description) {
    objectCreatorError.textContent = "Enter a description before generating an image.";
    return;
  }
  objectCreatorError.textContent = "";
  objectEditorState.description = description;
  objectEditorState.generatingImage = true;
  renderObjectCreator();
  try {
    const payload = await fetchObjectEditorJson("/api/object-editor/image", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        description,
        previous_image: objectEditorState.imagePath || null,
      }),
    });
    objectEditorState.imagePath = payload.image.image_path;
    objectEditorState.imageUrl = payload.image.image_url;
  } catch (err) {
    objectCreatorError.textContent = err.message;
  } finally {
    objectEditorState.generatingImage = false;
    renderObjectCreator();
  }
}

async function createThingFromEditor() {
  const description = (objectCreatorDescription.value || "").trim();
  if (!description) {
    objectCreatorError.textContent = "Enter a description for the thing.";
    return;
  }
  if (!objectEditorState.currentSprite && !objectEditorState.imagePath) {
    objectCreatorError.textContent = "Pick a sprite or generate an image first.";
    return;
  }
  objectCreatorError.textContent = "";
  objectEditorState.description = description;
  objectEditorState.creating = true;
  renderObjectCreator();
  try {
    await fetchObjectEditorJson("/api/object-editor/create", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        description,
        current_sprite: objectEditorState.currentSprite || null,
        image_path: objectEditorState.imagePath || null,
      }),
    });
    objectCreatorError.textContent = "";
    // Reset image state so it isn't reused next time
    objectEditorState.imagePath = null;
    objectEditorState.imageUrl = null;
    closeObjectCreator();
  } catch (err) {
    objectCreatorError.textContent = err.message;
  } finally {
    objectEditorState.creating = false;
    renderObjectCreator();
  }
}
