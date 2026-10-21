export const PEEP_GROUP_LIMIT = 5;

export function layoutPeeps(peeps = [], { selfId = "", pinned = new Set(), expanded = false, limit = PEEP_GROUP_LIMIT } = {}) {
  const pinnedIds = pinned instanceof Set ? pinned : new Set(pinned || []);
  const hasBubble = peep => Boolean(peep.bubble && !peep.bubbleDismissed);
  const self = peeps.filter(peep => peep.id === selfId);
  const others = peeps.filter(peep => peep.id !== selfId);
  const pinnedOthers = others.filter(peep => pinnedIds.has(peep.id));
  const unpinnedOthers = others.filter(peep => !pinnedIds.has(peep.id));
  const ordered = [...self, ...pinnedOthers, ...unpinnedOthers];

  if (peeps.length <= limit) {
    return { visible: ordered, grouped: [], canCollapse: false };
  }

  const grouped = peeps.filter(peep => peep.id !== selfId && !pinnedIds.has(peep.id) && !hasBubble(peep));
  if (expanded) {
    return { visible: ordered, grouped: [], canCollapse: grouped.length > 0 };
  }

  const visible = [
    ...self,
    ...others.filter(peep => pinnedIds.has(peep.id) || hasBubble(peep)),
  ];
  return { visible, grouped, canCollapse: false };
}
