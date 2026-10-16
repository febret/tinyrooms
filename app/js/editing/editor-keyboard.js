/** Shared transform shortcuts; hosts decide which views and input targets accept them. */
export function editorKeyAction(event, editor) {
  if (!editor || event.ctrlKey || event.metaKey || event.altKey) return null;
  const step = editor.snapPosition ? 5 : 1;
  const moves = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] };
  if (moves[event.key]) {
    const [dx, dy] = moves[event.key];
    return { type: "editor-nudge", dx, dy };
  }
  if (event.key === "[" || event.key === "]") return { type: "editor-rotate", delta: event.key === "]" ? 15 : -15 };
  if (["+", "=", "-", "_"].includes(event.key)) {
    return { type: "editor-scale", factor: ["-", "_"].includes(event.key) ? 1 / 1.15 : 1.15 };
  }
  return null;
}
