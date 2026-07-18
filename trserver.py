import os
import signal
import sys
import argparse

from flask_socketio import emit
from tinyrooms import server, console, db, user, connection, actions, room, world


# Add kill function to quickly terminate the server
def kill():
    """Immediately terminate the server process."""
    print("\n💀 Killing server immediately...")
    server.shutdown_char_editor()
    db.save_userdb_state()
    world.active_world().save_state()
    os._exit(0)


def reboot():
    """Reboot the server process."""
    print("\n🔄 Rebooting server...")
    server.shutdown_char_editor()
    db.save_userdb_state()
    world.active_world().save_state()
    os._exit(42)


def signal_handler_kill(sig, frame):
    kill()


def signal_handler_reboot(sig, frame):
    reboot()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run tinyrooms server")
    parser.add_argument(
        "--char-temp-dir",
        default="",
        help="Temporary directory for character sprite generation jobs",
    )
    parser.add_argument(
        "--sprite-temp-dir",
        default="",
        help="Deprecated alias for --char-temp-dir",
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Host interface to bind (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=5000,
        help="Port to bind (default: 5000)",
    )
    args = parser.parse_args()

    # Set up signal handlers
    signal.signal(signal.SIGINT, signal_handler_kill)  # Ctrl-C
    signal.signal(signal.SIGBREAK, signal_handler_reboot)  # Ctrl-\
    print("Signal handlers: Ctrl-C = kill, Ctrl-\\ = reload")

    temp_dir = args.char_temp_dir or args.sprite_temp_dir or None
    server.configure_char_editor(temp_dir)
    
    # Initialize database
    db.init_db()
    
    # Initialize world
    world.load_world()
    
    # Start the interactive console in a separate thread
    print("Starting interactive console...")
    console_vars = {
        "kill": kill,
        "reboot": reboot,
        "emit": emit,
        "actions": actions,
        "server": server,
        "user": user,
        "room": room,
        "world": world,
        "db": db,
    }
    console.start_console(console_vars)
    
    # Start the Flask-SocketIO server
    print(f"Starting Flask-SocketIO server on http://{args.host}:{args.port}")
    print("Accepting connections on localhost and all network interfaces")
    
    try:
        server.socketio.run(server.app, port=args.port, host=args.host)
    except KeyboardInterrupt:
        print("\n\nServer stopped by user")
    except Exception as e:
        print(f"\nServer error: {e}")
    finally:
        print("Shutting down...")
        server.shutdown_char_editor()
        # Save state of all connected users before shutdown
        db.save_userdb_state()
        world.active_world().save_state()
