/**
 * Own the room canvas's WebGL context-loss recovery and frame-error retry.
 *
 * A lost context is temporary: the browser can restore it, so the board must not
 * latch into a permanent failure. Frame exceptions get a few retries before they
 * are reported as a hard error, and the real exception is always logged.
 */
export function createBoardRecovery({
  canvas,
  overlay,
  maxFrameErrors = 5,
  onLost,
  onRestored,
  onFrameError,
}) {
  let renderFailed = false;
  let frameErrors = 0;

  function contextLost(event) {
    event.preventDefault();
    renderFailed = true;
    onLost?.();
  }

  function contextRestored() {
    renderFailed = false;
    frameErrors = 0;
    onRestored?.();
  }

  function frameError(error) {
    console.error("Board frame failed", error);
    frameErrors += 1;
    if (frameErrors >= maxFrameErrors) {
      contextLost({ preventDefault() {} });
      overlay.dataset.status = "error";
      overlay.textContent = "3D rendering hit repeated errors. Reload to restore the board; Room view remains available.";
      return;
    }
    onFrameError?.();
  }

  function resetFrameErrors() {
    frameErrors = 0;
  }

  canvas.addEventListener("webglcontextlost", contextLost);
  canvas.addEventListener("webglcontextrestored", contextRestored);

  return {
    get renderFailed() {
      return renderFailed;
    },
    frameError,
    resetFrameErrors,
    dispose() {
      canvas.removeEventListener("webglcontextlost", contextLost);
      canvas.removeEventListener("webglcontextrestored", contextRestored);
    },
  };
}
