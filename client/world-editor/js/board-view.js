import { createBoard } from "../../app/js/board.js";
import { withBase } from "../../app/js/base-path.js";

function cardEntry(catalog, cardId) {
  return (catalog?.cards || []).find(entry => entry.id === cardId) || null;
}

export function buildBoardRoom(draft, catalog, roomId, worldId) {
  const room = draft?.rooms?.[roomId];
  if (!room) return null;
  const propCatalog = new Map((catalog?.props || []).map(entry => [entry.id, entry]));
  const props = Object.entries(room.props || {})
    .map(([instanceId, instance]) => {
      const definition = propCatalog.get(instance.prop) || null;
      // Props absent from the catalog (e.g. hidden props) are never rendered.
      if (!definition) return null;
      return {
        id: instanceId,
        propId: instance.prop,
        position: Array.isArray(instance.pos) ? instance.pos.map(Number) : [50, 50, 0],
        rotation: Array.isArray(instance.rot) ? instance.rot : [0, 0, 0],
        scale: (definition.resizable ? Number(instance.scale ?? 1) : 1) * Number(definition.scale ?? 1),
        resizable: Boolean(definition.resizable),
        modelUrl: withBase(definition.model_url || ""),
        renderKind: definition.render_kind || "model",
        ...(instance.text ? { text: { ...instance.text } } : {}),
        ...(instance.exit_style ? { exit_style: { ...instance.exit_style } } : {}),
        label: instance.label || definition.label || instance.prop,
        description: instance.description || definition.description || "",
        animation: instance.animation || "",
        quickActions: [],
        ghost: false,
      };
    })
    .filter(Boolean);
  const roomCards = (room.cards || []).map((card, index) => {
    const entry = cardEntry(catalog, card.card);
    return {
      stackId: `seed-${roomId}-${index}`,
      position: Array.isArray(card.pos) ? card.pos.map(Number) : [50, 50, 0],
      definition: {
        imageUrl: withBase(entry?.image_url || ""),
        label: entry?.label || card.card,
      },
    };
  });
  return {
    id: roomId,
    label: room.label || roomId,
    board: {
      type: room.board_type || "basic",
      imageUrl: withBase(`/assets/world/${worldId}/rooms/${room.board_image}`),
      imageStyle: room.board_image_style || "stretch",
      palette: Array.isArray(room.palette) ? room.palette : [],
      dark: Boolean(room.dark),
    },
    props,
    roomCards,
  };
}

export function createBoardView({ canvas, overlay, onSelect, onBegin, onTransform, onRotate, onScale, onElevate }) {
  let activeRoomId = null;
  const selectProp = instanceId => {
    if (instanceId) onSelect({ kind: "prop", id: activeRoomId, sub: instanceId });
    else onSelect({ kind: "room", id: activeRoomId });
  };
  const board = createBoard({
    canvas,
    overlay,
    onSelect: selection => {
      if (selection.kind === "prop" && !selection.sub) {
        selectProp(selection.id);
        return;
      }
      onSelect(selection);
    },
    onEditSelect: selectProp,
    onEditBegin: () => onBegin(),
    onEditTransform: payload => onTransform(payload),
    onEditRotate: (delta, gesture) => onRotate(delta, gesture),
    onEditScale: (factor, gesture) => onScale(factor, gesture),
    onEditElevate: (delta, gesture) => onElevate(delta, gesture),
    stackProps: true,
    dragHandles: true,
  });

  return {
    render({ draft, catalog, worldId, roomId, selection, editing = true, editor }) {
      activeRoomId = roomId;
      const room = buildBoardRoom(draft, catalog, roomId, worldId);
      if (room && editor) {
        const locks = new Map(editor.props.map(prop => [prop.id, prop.locked]));
        room.props = room.props.map(prop => ({ ...prop, locked: Boolean(locks.get(prop.id)) }));
      }
      board.render({
        room,
        selection: null,
        ui: { reducedMotion: Boolean(window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches) },
        editing,
        editor,
        editSelection: selection?.kind === "prop" ? selection.sub : null,
        views: { main: editing ? "edit-room" : null, details: false, auth: false, commandPalette: false },
        user: { initialStickerComplete: true },
      });
    },
    dispose() {
      board.dispose();
    },
  };
}
