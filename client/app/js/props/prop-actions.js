export function activePropAction(action) {
  if (typeof action?.command !== "string" || !action.command.trim() || action.disabled) return false;
  return !/^\.(?:look|inspect)(?:\s|$)/i.test(action.command.trim());
}

export function defaultPropAction(prop) {
  const actions = (prop?.quickActions || []).filter(action => (
    typeof action.command === "string" && action.command.trim() && !action.disabled
  ));
  return actions.find(action => action.default) || (actions.length === 1 ? actions[0] : null);
}

export function hasActivePropActions(prop) {
  return Boolean(prop?.quickActions?.some(activePropAction));
}
