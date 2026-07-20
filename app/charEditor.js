// Character Editor Module

let characterEditorState = {
  mode: "closed",
  descriptorClasses: {},
  appearance: {},
  description: "",
  availableSprites: [],
  currentSprite: null,
  currentSpritePreview: null,
  mainImageUrl: null,
  saving: false,
  generatingMainImage: false,
};

let btnCharacterEditor;
let characterEditorPage;
let characterEditorDescriptors;
let characterEditorDescription;
let characterEditorSpriteList;
let characterEditorMainImagePreview;
let characterEditorError;
let btnCharacterGenerateMainImage;
let btnCharacterSave;
let btnCharacterEditorClose;
let btnCharacterEditorDone;
let characterEditorInitialized = false;

let characterEditorSocket;

function bindCharacterEditorDomElements() {
  btnCharacterEditor = document.getElementById("btnCharacterEditor");
  characterEditorPage = document.getElementById("characterEditorPage");
  characterEditorDescriptors = document.getElementById("characterEditorDescriptors");
  characterEditorDescription = document.getElementById("characterEditorDescription");
  characterEditorSpriteList = document.getElementById("characterEditorSpriteList");
  characterEditorMainImagePreview = document.getElementById("characterEditorMainImagePreview");
  characterEditorError = document.getElementById("characterEditorError");
  btnCharacterGenerateMainImage = document.getElementById("btnCharacterGenerateMainImage");
  btnCharacterSave = document.getElementById("btnCharacterSave");
  btnCharacterEditorClose = document.getElementById("btnCharacterEditorClose");
  btnCharacterEditorDone = document.getElementById("btnCharacterEditorDone");
  return !!(
    btnCharacterEditor &&
    characterEditorPage &&
    characterEditorDescriptors &&
    characterEditorDescription &&
    characterEditorSpriteList &&
    characterEditorMainImagePreview &&
    characterEditorError &&
    btnCharacterGenerateMainImage &&
    btnCharacterSave &&
    btnCharacterEditorClose &&
    btnCharacterEditorDone
  );
}

function initCharacterEditor(clientSocket, clientRestAuthToken) {
  characterEditorSocket = clientSocket;
  if (!bindCharacterEditorDomElements() || characterEditorInitialized) {
    return;
  }

  btnCharacterEditor.addEventListener("click", openCharacterEditor);
  btnCharacterEditorClose.addEventListener("click", closeCharacterEditor);
  btnCharacterEditorDone.addEventListener("click", closeCharacterEditor);
  btnCharacterGenerateMainImage.addEventListener("click", generateCharacterMainImage);
  btnCharacterSave.addEventListener("click", saveCharacterProfile);
  characterEditorDescription.addEventListener("input", event => {
    characterEditorState.description = event.target.value;
  });
  characterEditorInitialized = true;
}

function resetCharacterEditorState() {
  characterEditorState = {
    mode: "closed",
    descriptorClasses: {},
    appearance: {},
    description: "",
    availableSprites: [],
    currentSprite: null,
    currentSpritePreview: null,
    mainImageUrl: null,
    saving: false,
    generatingMainImage: false,
  };
  if (!bindCharacterEditorDomElements()) {
    return;
  }
  renderCharacterEditor();
}

function applyCharacterProfile(profile) {
  const char = profile.char || {};
  characterEditorState.descriptorClasses = profile.descriptor_classes || {};
  characterEditorState.availableSprites = profile.available_sprites || [];
  characterEditorState.appearance = { ...(char.appearance || {}) };
  characterEditorState.description = char.description || "";
  characterEditorState.currentSprite = char.current_sprite || null;
  characterEditorState.currentSpritePreview = char.current_sprite_preview || null;
  characterEditorState.mainImageUrl = char.main_image_url || null;
}

async function openCharacterEditor() {
  characterEditorState.mode = "editing";
  characterEditorError.textContent = "";
  characterEditorPage.style.display = "flex";
  renderCharacterEditor();
  try {
    const profile = await fetchJson("/api/char-editor/profile");
    applyCharacterProfile(profile);
    renderCharacterEditor();
  } catch (err) {
    characterEditorError.textContent = err.message;
    renderCharacterEditor();
  }
}

function closeCharacterEditor() {
  characterEditorPage.style.display = "none";
  characterEditorState.mode = "closed";
}

function getDescriptorOptionId(option) {
  if (typeof option === "string") return option;
  return option.id || "";
}

function getDescriptorOptionLabel(option) {
  if (typeof option === "string") return option;
  return option.label || option.id || "";
}

function renderCharacterEditor() {
  if (
    !characterEditorDescriptors ||
    !characterEditorDescription ||
    !characterEditorSpriteList ||
    !characterEditorMainImagePreview
  ) {
    return;
  }

  const busy = characterEditorState.saving || characterEditorState.generatingMainImage;
  characterEditorDescription.value = characterEditorState.description;
  characterEditorDescription.disabled = busy;
  btnCharacterSave.disabled = busy;
  btnCharacterGenerateMainImage.disabled = busy;

  characterEditorDescriptors.innerHTML = "";
  for (const [descriptorKey, descriptorMeta] of Object.entries(characterEditorState.descriptorClasses)) {
    const section = document.createElement("div");
    section.className = "character-descriptor";
    const label = document.createElement("div");
    label.className = "character-descriptor-label";
    label.textContent = descriptorMeta.label || descriptorKey;
    section.appendChild(label);

    const optionsWrap = document.createElement("div");
    optionsWrap.className = "character-options";
    for (const option of (descriptorMeta.options || [])) {
      const optionId = getDescriptorOptionId(option);
      const optionLabel = getDescriptorOptionLabel(option);
      const button = document.createElement("button");
      button.type = "button";
      button.className = "character-option";
      button.disabled = busy;
      if (descriptorMeta.type === "color") {
        button.classList.add("color-option");
        const swatch = document.createElement("span");
        swatch.className = "swatch";
        swatch.style.backgroundColor = option.swatch || optionId;
        button.appendChild(swatch);
        const txt = document.createElement("span");
        txt.textContent = optionLabel;
        button.appendChild(txt);
      } else {
        button.textContent = optionLabel;
      }
      if (characterEditorState.appearance[descriptorKey] === optionId) {
        button.classList.add("selected");
      }
      button.addEventListener("click", () => {
        characterEditorState.appearance[descriptorKey] = optionId;
        renderCharacterEditor();
      });
      optionsWrap.appendChild(button);
    }
    section.appendChild(optionsWrap);
    characterEditorDescriptors.appendChild(section);
  }

  characterEditorSpriteList.innerHTML = "";

  const defaultCard = document.createElement("button");
  defaultCard.type = "button";
  defaultCard.className = "character-sprite-card character-sprite-card-default";
  if (!characterEditorState.currentSprite) defaultCard.classList.add("selected");
  defaultCard.disabled = busy;
  defaultCard.addEventListener("click", () => {
    characterEditorState.currentSprite = null;
    characterEditorState.currentSpritePreview = null;
    renderCharacterEditor();
  });
  const defaultLabel = document.createElement("div");
  defaultLabel.className = "character-sprite-label";
  defaultLabel.textContent = "Use main image";
  defaultCard.appendChild(defaultLabel);
  const defaultMeta = document.createElement("div");
  defaultMeta.className = "character-sprite-meta";
  defaultMeta.textContent = "No sprite sheet";
  defaultCard.appendChild(defaultMeta);
  characterEditorSpriteList.appendChild(defaultCard);

  for (const option of characterEditorState.availableSprites) {
    characterEditorSpriteList.appendChild(createSpriteCard(
      option,
      characterEditorState.currentSprite === option.sprite_ref,
      opt => {
        characterEditorState.currentSprite = opt.sprite_ref;
        characterEditorState.currentSpritePreview = opt;
        renderCharacterEditor();
      },
      busy,
    ));
  }

  characterEditorMainImagePreview.innerHTML = "";
  characterEditorMainImagePreview.classList.toggle("is-busy", characterEditorState.generatingMainImage);
  if (characterEditorState.mainImageUrl) {
    const img = document.createElement("img");
    img.src = resolveAssetUrl(characterEditorState.mainImageUrl);
    img.alt = "Character main image";
    characterEditorMainImagePreview.appendChild(img);
  } else {
    const empty = document.createElement("div");
    empty.className = "character-main-image-empty";
    empty.textContent = "No main image yet.";
    characterEditorMainImagePreview.appendChild(empty);
  }
}

function characterEditorPayload() {
  return {
    appearance: characterEditorState.appearance,
    description: characterEditorState.description,
    current_sprite: characterEditorState.currentSprite,
  };
}

async function saveCharacterProfile() {
  await withEditorBusy(characterEditorState, "saving", characterEditorError, renderCharacterEditor, async () => {
    const payload = await fetchJson("/api/char-editor/profile", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(characterEditorPayload()),
    });
    applyCharacterProfile({ descriptor_classes: characterEditorState.descriptorClasses, available_sprites: characterEditorState.availableSprites, char: payload.char });
  });
}

async function generateCharacterMainImage() {
  await withEditorBusy(characterEditorState, "generatingMainImage", characterEditorError, renderCharacterEditor, async () => {
    const payload = await fetchJson("/api/char-editor/main-image", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(characterEditorPayload()),
    });
    applyCharacterProfile({ descriptor_classes: characterEditorState.descriptorClasses, available_sprites: characterEditorState.availableSprites, char: payload.char });
  });
}
