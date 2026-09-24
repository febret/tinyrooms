import { createBoard } from "/app/js/board.js";

function cardEntry(catalog, cardId) {
  return (catalog?.cards || []).find(entry => entry.id === cardId) || null;
}

export function buildBoardRoom(draft, catalog, roomId, worldId) {
  const room = draft?.rooms?.[roomId];
  if (!room) return null;
  const propCatalog = new Map((catalog?.props || []).map(entry => [entry.id, entry]));
  const props = Object.entries(room.props || {}).map(([instanceId, instance]) => {
    const definition = propCatalog.get(instance.prop) || null;
    return {
      id: instanceId,
      propId: instance.prop,
      position: Array.isArray(instance.pos) ? instance.pos.map(Number) : [50, 50, 0],
      rotation: Array.isArray(instance.rot) ? instance.rot.map(Number) : [0, 0, 0],
      scale: Number(instance.scale ?? 1),
      modelUrl: definition?.model_url || "",
      label: definition?.label || instance.prop,
      description: definition?.description || "",
      animation: instance.animation || "",
      quickActions: [],
      ghost: false,
    };
  });
  const roomCards = (room.cards || []).map((card, index) => {
    const entry = cardEntry(catalog, card.card);
    return {
      stackId: `seed-${roomId}-${index}`,
      position: Array.isArray(card.pos) ? card.pos.map(Number) : [50, 50, 0],
      definition: {
        imageUrl: entry?.image_url || "",
        label: entry?.label || card.card,
      },
    };
  });
  return {
    id: roomId,
    label: room.label || roomId,
    board: {
      type: room.board_type || "basic",
      imageUrl: `/assets/world/${worldId}/rooms/${room.board_image}`,
      imageStyle: room.board_image_style || "stretch",
      palette: Array.isArray(room.palette) ? room.palette : [],
      dark: Boolean(room.dark),
    },
    props,
    roomCards,
  };
}

export function createBoardView({ canvas, overlay, onSelect, onBegin, onTransform, onRotate, onScale }) {
  const board = createBoard({
    canvas,
    overlay,
    onSelect: selection => onSelect(selection),
    onEditSelect: id => onSelect(id ? { kind: "prop", id } : { kind: "room", id: null }),
    onEditBegin: () => onBegin(),
    onEditTransform: payload => onTransform(payload),
    onEditRotate: delta => onRotate(delta),
    onEditScale: factor => onScale(factor),
  });

  return {
    render({ draft, catalog, worldId, roomId, selection, editing = true }) {
      const room = buildBoardRoom(draft, catalog, roomId, worldId);
      board.render({
        room,
        selection: null,
        ui: { reducedMotion: true },
        editing,
        editSelection: selection?.kind === "prop" ? selection.id : null,
        views: { main: true, details: false, auth: false, commandPalette: false },
        user: { initialStickerComplete: true },
      });
    },
    dispose() {
      board.dispose();
    },
  };
}
