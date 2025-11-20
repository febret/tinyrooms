import threading
import code
import readline
import rlcompleter
import queue
import eventlet

# Queue for sending command lines from input thread to eventlet console thread
command_queue = queue.Queue()

def input_thread_func(locals_dict):
    # Enable tab completion
    readline.set_completer(rlcompleter.Completer(locals_dict).complete)
    readline.parse_and_bind("tab: complete")
    
    banner = """
    =================================================
    TinyRooms Server Console 🛖
    =================================================
    Tab completion enabled. Type help() for Python help.
    Special commands: /k to kill, /r to reboot
    =================================================
    """
    print(banner)
    
    while True:
        try:
            line = input(">>> ")
            command_queue.put(line)
        except EOFError:
            locals_dict["reboot"]()
            break
        except KeyboardInterrupt:
            print("\nKeyboardInterrupt")
            command_queue.put("")  # Send empty line to reset


def console_eventlet_thread(locals_dict):
    """Runs in an eventlet greenthread to execute commands."""
    console = code.InteractiveConsole(locals=locals_dict)
    
    while True:
        eventlet.sleep(0)  # Yield to other greenthreads
        if command_queue.empty():
            continue        
        with locals_dict["server"].app.app_context():
            for line in iter(command_queue.get, None):
                console.push(line)


def start_console(locals_dict=None):
    """Start the console with input thread and eventlet execution thread."""
    if locals_dict is None:
        locals_dict = {}
    
    # Start the input thread (physical thread for blocking I/O)
    input_thread = threading.Thread(target=input_thread_func, args=(locals_dict,), daemon=True)
    input_thread.start()
    
    # Start the eventlet console thread (runs in eventlet greenthread)
    eventlet.spawn(console_eventlet_thread, locals_dict)
    
    return input_thread

