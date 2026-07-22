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

function initObjectEditor() {
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

async function openObjectCreator() {
  objectEditorState.mode = "editing";
  objectEditorState.description = objectCreatorDescription ? objectCreatorDescription.value : "";
  objectCreatorError.textContent = "";
  objectCreatorPage.style.display = "flex";
  renderObjectCreator();
  try {
    const profile = await fetchJson("/api/object-editor/profile");
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
    objectCreatorSpriteList.appendChild(createSpriteCard(
      option,
      objectEditorState.currentSprite === option.sprite_ref,
      opt => {
        objectEditorState.currentSprite = opt.sprite_ref;
        renderObjectCreator();
      },
      busy,
    ));
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
  objectEditorState.description = description;
  await withEditorBusy(objectEditorState, "generatingImage", objectCreatorError, renderObjectCreator, async () => {
    const payload = await fetchJson("/api/object-editor/image", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        description,
        previous_image: objectEditorState.imagePath || null,
      }),
    });
    objectEditorState.imagePath = payload.image.image_path;
    objectEditorState.imageUrl = payload.image.image_url;
  });
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
  objectEditorState.description = description;
  await withEditorBusy(objectEditorState, "creating", objectCreatorError, renderObjectCreator, async () => {
    await fetchJson("/api/object-editor/create", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        description,
        current_sprite: objectEditorState.currentSprite || null,
        image_path: objectEditorState.imagePath || null,
      }),
    });
    objectEditorState.imagePath = null;
    objectEditorState.imageUrl = null;
    closeObjectCreator();
  });
}
