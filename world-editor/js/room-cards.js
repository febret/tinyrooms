/** Preserve authored stack metadata for each retained occurrence of a card. */
export function reconcileRoomCards(cards, ids) {
  const remaining = [...(cards || [])];
  return ids.map(id => {
    const index = remaining.findIndex(card => card.card === id);
    if (index >= 0) return remaining.splice(index, 1)[0];
    return { card: id, quantity: 1, pos: [50, 50, 0] };
  });
}
