export const PEEP_GROUP_LIMIT = 5;

export function layoutPeeps(peeps = [], {
  selfId = "",
  pinned = new Set(),
  expanded = false,
  limit = PEEP_GROUP_LIMIT,
  dialogId = "",
} = {}) {
  const pinnedIds = pinned instanceof Set ? pinned : new Set(pinned || []);
  const isImportant = peep => Boolean(peep.bubble && !peep.bubbleDismissed) || peep.id === dialogId;
  const self = peeps.filter(peep => peep.id === selfId);
  const others = peeps.filter(peep => peep.id !== selfId);
  const pinnedOthers = others.filter(peep => pinnedIds.has(peep.id));
  const unpinnedOthers = others.filter(peep => !pinnedIds.has(peep.id));
  const ordered = [...self, ...pinnedOthers, ...unpinnedOthers];

  if (peeps.length <= limit) {
    return { visible: ordered, grouped: [], canCollapse: false };
  }

  const grouped = peeps.filter(peep => peep.id !== selfId && !pinnedIds.has(peep.id) && !isImportant(peep));
  if (expanded) {
    return { visible: ordered, grouped: [], canCollapse: grouped.length > 0 };
  }

  const visible = [
    ...self,
    ...others.filter(peep => pinnedIds.has(peep.id) || isImportant(peep)),
  ];
  return { visible, grouped, canCollapse: false };
}
