import threading
import code
import readline
import rlcompleter
import queue
import eventlet
import os
import atexit

# Queue for sending command lines from input thread to eventlet console thread
command_queue = []

# History file configuration
HISTORY_FILE = os.path.expanduser("~/.tinyrooms_history")
HISTORY_SIZE = 1000

def run_admin_cmd(cmd, locals_dict):
    if cmd == 'r':
        locals_dict["reboot"]()
    elif cmd == 'k':
        locals_dict["kill"]()
    elif cmd == 'rc':
        locals_dict["user"].reload_clients()
    elif cmd == 'rs':
        locals_dict["user"].reload_styles()
    elif cmd == 'ra':
        locals_dict["actions"].load_actions()
    elif cmd.startswith('rw'):
        w = locals_dict["world"]
        w.load_world(w.root_path / "world.yaml")  


def input_thread_func(locals_dict):
    # Enable tab completion
    readline.set_completer(rlcompleter.Completer(locals_dict).complete)  # type: ignore
    readline.parse_and_bind("tab: complete")  # type: ignore
    
    # Configure history
    readline.set_history_length(HISTORY_SIZE)  # type: ignore
    if os.path.exists(HISTORY_FILE):
        readline.read_history_file(HISTORY_FILE)  # type: ignore
    
    # Save history on exit
    def save_history():
        readline.write_history_file(HISTORY_FILE)  # type: ignore
    
    atexit.register(save_history)
    
    banner = """
    =================================================
    TinyRooms Server Console 🛖
    =================================================
    Tab completion enabled. Type help() for Python help.
    =================================================
    """
    print(banner)
    
    while True:
        try:
            line = input(">>> ")
            if line.startswith('/'):
                cmd = line[1:].strip()
                run_admin_cmd(cmd, locals_dict)
            else:
                command_queue.append(line)
        except EOFError:
            locals_dict["reboot"]()
            break
        except KeyboardInterrupt:
            print("\nKeyboardInterrupt")
            command_queue.append("")  # Send empty line to reset


def console_eventlet_thread(locals_dict):
    """Runs in an eventlet greenthread to execute commands."""
    console = code.InteractiveConsole(locals=locals_dict)
    
    while True:
        eventlet.sleep(0.1)
        if not command_queue:
            continue
        with locals_dict["server"].app.app_context():
            for line in command_queue:
                try:
                    console.push(line)
                    print(">>> ")
                except:
                    continue
            command_queue.clear()


def start_console(locals_dict=None):
    if locals_dict is None:
        locals_dict = {}
    
    # Start the input thread (physical thread for blocking I/O)
    input_thread = threading.Thread(target=input_thread_func, args=(locals_dict,), daemon=True)
    input_thread.start()
    
    # Start the eventlet console thread (runs in eventlet greenthread)
    eventlet.spawn(console_eventlet_thread, locals_dict)
    
    return input_thread

