/** Room rules are evaluated only at the store boundary. */
function roomIsDark(room, now) {
  if (!room) return false;
  const environment = room.environment || {};
  const expires = Date.parse(environment.lighting_expires_at);
  const baseDark = room.board?.baseDark ?? room.board?.dark ?? false;
  if (Number.isFinite(expires) && expires <= now) return Boolean(baseDark);
  if (environment.lighting === "dark") return true;
  if (environment.lighting === "normal") return false;
  return Boolean(baseDark);
}

function propIsVisible(room, prop, now) {
  if (!prop || prop.hidden) return false;
  const hidden = room?.environment?.hidden_props;
  if (!hidden || !Object.prototype.hasOwnProperty.call(hidden, prop.id)) return true;
  const expires = Date.parse(hidden[prop.id]?.expires_at);
  return Number.isFinite(expires) && expires <= now;
}

function mapShared(items, annotate) {
  let result = items;
  items.forEach((item, index) => {
    const next = annotate(item);
    if (next === item) return;
    if (result === items) result = items.slice();
    result[index] = next;
  });
  return result;
}

export function annotateRoom(room, now = Date.now()) {
  if (!room) return room;
  const dark = roomIsDark(room, now);
  const board = room.board.dark === dark ? room.board : { ...room.board, dark };
  const props = mapShared(room.props, prop => {
    const visible = propIsVisible(room, prop, now);
    const selectable = !dark && visible;
    return prop.visible === visible && prop.selectable === selectable ? prop : { ...prop, visible, selectable };
  });
  const roomCards = mapShared(room.roomCards, card => card.selectable === !dark ? card : { ...card, selectable: !dark });
  const environment = room.environment || {};
  let eligibilityExpiresAt = null;
  for (const value of [environment.lighting_expires_at,
    ...Object.values(environment.hidden_props || {}).map(hidden => hidden?.expires_at)]) {
    const expires = Date.parse(value);
    if (Number.isFinite(expires) && expires > now && (eligibilityExpiresAt === null || expires < eligibilityExpiresAt)) {
      eligibilityExpiresAt = expires;
    }
  }
  return board === room.board && props === room.props && roomCards === room.roomCards
    && eligibilityExpiresAt === room.eligibilityExpiresAt
    ? room : { ...room, board, props, roomCards, eligibilityExpiresAt };
}
