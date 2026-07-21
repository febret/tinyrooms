function attachRefEventHandlers(tgt) {
  const spans = tgt.querySelectorAll('span.ref');
  const touchHandler = (e) => {
    e.preventDefault();
    const src = e.currentTarget;
    if (src.dataset.cmdText) {
      // Spec-format command link [[display|command]]
      socket.emit("message", { text: src.dataset.cmdText });
    } else if (src.dataset.cmd) {
      let actionCmd = `.${src.dataset.cmd}`;
      if (src.dataset.target) {
        actionCmd += ` @${src.dataset.target}`;
      }
      socket.emit("message", { text: actionCmd });
    } else {
      const refText = src.id?.length ? `@${src.id}` : src.textContent;
      if (refText?.length) {
        msgInput.value = `${msgInput.value} ${refText}`.trim();
      }
    }
  };

  spans.forEach(span => {
    span.addEventListener('click', touchHandler);
    span.addEventListener('touchend', touchHandler);
  });
}
