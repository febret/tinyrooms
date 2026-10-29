/**
 * Own the board's requestAnimationFrame lifecycle.
 *
 * The renderer is idle most of the time: a static room should not wake the CPU
 * sixty times a second. `schedule` starts one frame, `once` coalesces named
 * setup work into that frame, and `onFrame` returns whether another frame is
 * needed. Visibility changes restart the loop after the browser pauses it.
 */
export function createBoardScheduler({ onFrame, onError, isHidden = () => document.hidden }) {
  let frame = 0;
  let ticks = 0;
  let disposed = false;
  const tasks = new Map();

  function schedule() {
    if (frame || disposed || isHidden()) return;
    frame = requestAnimationFrame(run);
  }

  function once(key, task) {
    if (disposed) return;
    tasks.set(key, task);
    schedule();
  }

  function run() {
    frame = 0;
    if (disposed) return;
    ticks += 1;
    try {
      if (isHidden()) return;
      for (const [key, task] of [...tasks]) {
        tasks.delete(key);
        task();
      }
      if (onFrame()) schedule();
    } catch (error) {
      onError?.(error);
    }
  }

  function handleVisibilityChange() {
    if (!disposed && !isHidden()) schedule();
  }

  document.addEventListener("visibilitychange", handleVisibilityChange);

  return {
    schedule,
    once,
    get ticks() {
      return ticks;
    },
    stop() {
      disposed = true;
      cancelAnimationFrame(frame);
      frame = 0;
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    },
  };
}
