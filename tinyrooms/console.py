import threading
import code

def start_console(locals=None):
    banner = """
    =================================================
    TinyRooms Server Console 🛖
    =================================================
    Tab completion enabled. Type help() for Python help.
    Type kill() to immediately terminate the server.
    =================================================
    """
    console = code.InteractiveConsole(locals=locals)
    console.interact(banner=banner, exitmsg="Exiting console...")


def start_console_thread(locals=None):
    console_thread = threading.Thread(target=start_console, args=[locals], daemon=True)
    console_thread.start()
    return console_thread
