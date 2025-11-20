import os
import signal
import sys

from tinyrooms import server, console, db, user, connection


# Add kill function to quickly terminate the server
def kill():
    """Immediately terminate the server process."""
    print("\n💀 Killing server immediately...")
    os._exit(0)


def reboot():
    """Reboot the server process."""
    print("\n🔄 Rebooting server...")
    os._exit(42)


def signal_handler_kill(sig, frame):
    kill()


def signal_handler_reboot(sig, frame):
    reboot()


if __name__ == "__main__":
    # Set up signal handlers
    signal.signal(signal.SIGINT, signal_handler_kill)  # Ctrl-C
    signal.signal(signal.SIGBREAK, signal_handler_reboot)  # Ctrl-\
    print("Signal handlers: Ctrl-C = kill, Ctrl-\\ = reload")
    
    # Initialize database
    db.init_db()
    
    # Start the interactive console in a separate thread
    print("Starting interactive console...")
    console_vars = {
        "k": kill,
        "r": reboot
    }
    console.start_console_thread(locals=console_vars)
    
    # Start the Flask-SocketIO server
    print("Starting Flask-SocketIO server on http://0.0.0.0:5000")
    print("Accepting connections on localhost and all network interfaces")
    
    try:
        server.socketio.run(server.app, port=5000, host="0.0.0.0")
    except KeyboardInterrupt:
        print("\n\nServer stopped by user")
    except Exception as e:
        print(f"\nServer error: {e}")
    finally:
        print("Shutting down...")