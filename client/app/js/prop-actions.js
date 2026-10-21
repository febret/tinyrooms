export function activePropAction(action) {
  if (typeof action?.command !== "string" || !action.command.trim() || action.disabled) return false;
  return !/^\.(?:look|inspect)(?:\s|$)/i.test(action.command.trim());
}

export function defaultPropAction(prop) {
  return prop?.quickActions?.find(action => action.default && action.command && !action.disabled) || null;
}

export function hasActivePropActions(prop) {
  return Boolean(prop?.quickActions?.some(activePropAction));
}
