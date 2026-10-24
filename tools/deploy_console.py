"""Animated, colored console output for the deploy tool.

``Console`` renders spinners and byte progress bars when stdout is a TTY and
degrades to plain lines otherwise; ``NO_COLOR`` and ``TERM=dumb`` disable
color and animation. All writes are serialized so status messages can safely
interrupt a running spinner.
"""

from __future__ import annotations

import contextlib
import os
import sys
import threading
from collections.abc import Callable, Iterator


class Console:
    """TTY-aware console with animated spinners and colored status lines.

    Spinners animate only when output is a terminal; otherwise every phase
    still prints one plain line. ``NO_COLOR`` and ``TERM=dumb`` disable
    color and animation. All writes are serialized so status messages can
    safely interrupt a running spinner.
    """

    RESET = "\x1b[0m"
    BOLD = "\x1b[1m"
    CYAN = "\x1b[36m"
    GREEN = "\x1b[32m"
    YELLOW = "\x1b[33m"
    RED = "\x1b[31m"
    SPINNER_FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")
    ASCII_FRAMES = ("|", "/", "-", "\\")
    PROGRESS_WIDTH = 24

    def __init__(self, stream=None, *, color: bool | None = None, animated: bool | None = None) -> None:
        self.stream = stream if stream is not None else sys.stdout
        tty = bool(getattr(self.stream, "isatty", lambda: False)())
        dumb = os.environ.get("TERM") == "dumb"
        self.color = (tty and "NO_COLOR" not in os.environ and not dumb) if color is None else color
        self.animated = (tty and not dumb) if animated is None else animated
        self._lock = threading.Lock()
        self._spinner_label: str | None = None
        self._spinner_frame = 0
        self._spinner_timer: threading.Timer | None = None
        if os.name == "nt" and self.color:
            self._enable_windows_ansi()

    @staticmethod
    def _enable_windows_ansi() -> None:
        """Enable virtual-terminal color sequences on Windows consoles."""

        try:
            import ctypes

            handle = ctypes.windll.kernel32.GetStdHandle(-11)
            mode = ctypes.c_uint32()
            if ctypes.windll.kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                ctypes.windll.kernel32.SetConsoleMode(handle, mode.value | 0x0004)
        except Exception:  # noqa: BLE001 - color is best effort
            pass

    def paint(self, text: str, *codes: str) -> str:
        """Wrap *text* in ANSI codes when color output is enabled."""

        if not self.color or not codes:
            return text
        return "".join(codes) + text + self.RESET

    def _glyph(self, fancy: str, fallback: str) -> str:
        """Return a Unicode glyph, falling back to ASCII when unencodable."""

        encoding = getattr(self.stream, "encoding", None) or "utf-8"
        try:
            fancy.encode(encoding)
        except (LookupError, UnicodeEncodeError):
            return fallback
        return fancy

    def _raw_write(self, text: str) -> None:
        self.stream.write(text)
        self.stream.flush()

    def _clear_live(self) -> None:
        if self.animated:
            self._raw_write("\r\x1b[K")

    def _redraw_live(self) -> None:
        if self._spinner_label is None or not self.animated:
            return
        frames = self.SPINNER_FRAMES if self._glyph("⠋", "") else self.ASCII_FRAMES
        frame = frames[self._spinner_frame % len(frames)]
        self._raw_write(f"\r{self.paint(frame, self.CYAN)} {self._spinner_label}\x1b[K")

    def write_line(self, text: str) -> None:
        """Print one line, briefly clearing any live spinner or progress bar."""

        with self._lock:
            self._clear_live()
            self._raw_write(text + "\n")

    def phase(self, index: int, total: int, title: str) -> None:
        """Print a numbered deployment phase header."""

        marker = self._glyph("▸", ">")
        self.write_line(self.paint(f"{marker} [{index}/{total}] {title}", self.BOLD, self.CYAN))

    def success(self, message: str) -> None:
        """Print a successful step with a green check."""

        self.write_line(f"{self.paint(self._glyph('✓', '[ok]'), self.GREEN)} {message}")

    def info(self, message: str) -> None:
        """Print an informational line."""

        self.write_line(f"  {message}")

    def warning(self, message: str) -> None:
        """Print a warning with a yellow marker."""

        self.write_line(f"{self.paint(self._glyph('!', '[!]'), self.YELLOW)} {message}")

    def error(self, message: str) -> None:
        """Print an error with a red marker."""

        self.write_line(f"{self.paint(self._glyph('✗', '[x]'), self.RED)} {message}")

    def start_spinner(self, label: str) -> None:
        """Begin a live spinner, or print the pending label in plain mode."""

        with self._lock:
            self._spinner_label = label
            self._spinner_frame = 0
            if self.animated:
                self._redraw_live()
                if self._spinner_timer is None:
                    self._schedule_tick()
            else:
                self._raw_write(f"{label} ...\n")

    def update_spinner(self, label: str) -> None:
        """Replace the message of the running spinner."""

        with self._lock:
            self._spinner_label = label
            if self.animated:
                self._redraw_live()

    def stop_spinner(self) -> None:
        """Stop the running spinner and clear its line."""

        with self._lock:
            self._spinner_label = None
            timer, self._spinner_timer = self._spinner_timer, None
            if timer is not None:
                timer.cancel()
            self._clear_live()

    def _schedule_tick(self) -> None:
        timer = threading.Timer(0.08, self._tick)
        timer.daemon = True
        self._spinner_timer = timer
        timer.start()

    def _tick(self) -> None:
        with self._lock:
            if self._spinner_label is None:
                self._spinner_timer = None
                return
            self._spinner_frame += 1
            self._redraw_live()
            self._schedule_tick()

    @contextlib.contextmanager
    def spinner(self, label: str, done: str | None = None) -> Iterator[None]:
        """Run a block under a spinner, printing *done* on success."""

        self.start_spinner(label)
        try:
            yield
        except BaseException:
            self.stop_spinner()
            raise
        self.stop_spinner()
        if done is not None:
            self.success(done)

    @contextlib.contextmanager
    def progress(self, label: str, total: int) -> Iterator[Callable[[int], None]]:
        """Render a live progress bar for *total* bytes, yielding an advancer."""

        tracker = _Progress(self, label, total)
        tracker.begin()
        try:
            yield tracker.advance
        finally:
            tracker.finish()


class _Progress:
    """Byte progress bar that degrades to percentage milestones off-TTY."""

    def __init__(self, console: Console, label: str, total: int) -> None:
        self._console = console
        self._label = label
        self._total = max(total, 1)
        self._done = 0
        self._last_mark = -1

    def begin(self) -> None:
        """Announce the transfer in plain mode; animated bars draw on first advance."""

        if not self._console.animated:
            self._console.write_line(f"{self._label} ...")

    def advance(self, count: int) -> None:
        """Record *count* transferred bytes and refresh the display."""

        console = self._console
        with console._lock:
            self._done = min(self._total, self._done + count)
            if console.animated:
                console._clear_live()
                console._raw_write(f"\r{self._render()}\x1b[K")
            else:
                mark = int(100 * self._done / self._total) // 25
                if mark > self._last_mark:
                    self._last_mark = mark
                    console._raw_write(f"{self._label} ... {int(100 * self._done / self._total)}% "
                                       f"({_format_bytes(self._done)}/{_format_bytes(self._total)})\n")

    def finish(self) -> None:
        """Clear the live bar; callers print the final summary line."""

        with self._console._lock:
            self._console._clear_live()

    def _render(self) -> str:
        width = Console.PROGRESS_WIDTH
        filled = int(width * self._done / self._total)
        if self._console._glyph("█", ""):
            bar = "█" * filled + "░" * (width - filled)
        else:
            bar = "#" * filled + "-" * (width - filled)
        percent = int(100 * self._done / self._total)
        return (f"{self._label} {self._console.paint(f'[{bar}]', Console.CYAN)} "
                f"{percent:3d}% {_format_bytes(self._done)}/{_format_bytes(self._total)}")


def _format_bytes(count: int) -> str:
    """Format a byte count for progress display."""

    value = float(count)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{int(value)} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


CONSOLE = Console()
