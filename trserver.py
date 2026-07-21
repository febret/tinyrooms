import os
import signal
import sys
import argparse
import logging

from flask_socketio import emit
from tinyrooms import server, console, db, user, connection, room, world
from tinyrooms import peep_behavior


# Add kill function to quickly terminate the server
def kill():
    """Immediately terminate the server process."""
    print("\n💀 Killing server immediately...")
    server.shutdown_char_editor()
    server.shutdown_object_editor()
    db.save_userdb_state()
    if server.feature_enabled("world-server"):
        peep_behavior.stop_tick_loop()
        world.active_world().save_state()
    os._exit(0)


def reboot():
    """Reboot the server process."""
    print("\n🔄 Rebooting server...")
    server.shutdown_char_editor()
    server.shutdown_object_editor()
    db.save_userdb_state()
    if server.feature_enabled("world-server"):
        peep_behavior.stop_tick_loop()
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
        help="Temporary directory for character-editor main-image generation jobs",
    )
    parser.add_argument(
        "--sprite-temp-dir",
        default="",
        help="Deprecated alias for --char-temp-dir",
    )
    parser.add_argument(
        "--object-temp-dir",
        default="",
        help="Temporary directory for object icon generation jobs",
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
    parser.add_argument(
        "--log-api",
        action="store_true",
        help="Log REST API requests to stderr",
    )
    parser.add_argument(
        "--tick-secs",
        type=float,
        default=1.0,
        help="Tick interval in seconds for NPC peep behaviors (default: 1.0)",
    )
    parser.add_argument(
        "--feature",
        action="append",
        default=[],
        help="Enable optional feature flag (repeatable; also accepts comma-separated values, e.g. --feature sprite-editor,prop-editor)",
    )
    args = parser.parse_args()

    # Set up signal handlers
    signal.signal(signal.SIGINT, signal_handler_kill)  # Ctrl-C
    signal.signal(signal.SIGBREAK, signal_handler_reboot)  # Ctrl-\
    print("Signal handlers: Ctrl-C = kill, Ctrl-\\ = reload")

    temp_dir = args.char_temp_dir or args.sprite_temp_dir or None
    server.configure_char_editor(temp_dir)
    server.configure_object_editor(args.object_temp_dir or None)
    features = {f.strip() for raw in (args.feature or []) for f in raw.split(",") if f.strip()}
    server.configure_features(features)
    
    # Initialize database
    db.init_db()
    
    # Initialize world (only when world-server feature is enabled)
    if server.feature_enabled("world-server"):
        world.load_world()
        peep_behavior.start_tick_loop(world.active_world, interval=args.tick_secs)
    
    # Start the interactive console in a separate thread
    print("Starting interactive console...")
    console_vars = {
        "kill": kill,
        "reboot": reboot,
        "emit": emit,
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

    logging.getLogger("werkzeug").setLevel(
        logging.INFO if args.log_api else logging.ERROR
    )
    
    try:
        server.socketio.run(server.app, port=args.port, host=args.host)
    except KeyboardInterrupt:
        print("\n\nServer stopped by user")
    except Exception as e:
        print(f"\nServer error: {e}")
    finally:
        print("Shutting down...")
        server.shutdown_char_editor()
        server.shutdown_object_editor()
        # Save state of all connected users before shutdown
        db.save_userdb_state()
        if server.feature_enabled("world-server"):
            peep_behavior.stop_tick_loop()
            world.active_world().save_state()
