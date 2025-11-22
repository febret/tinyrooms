from pathlib import Path
import yaml

from . import room


def load_world(yaml_path=None):
    """Load world definitions from YAML file or directory."""
    global world_info
    global root_path
    if yaml_path is None:
        yaml_path = Path(__file__).parent.parent / "data" / "worlds" / "home" / "world.yaml"
    
    yaml_path = Path(yaml_path)
    if not yaml_path.is_file():
        raise FileNotFoundError(f"World definition file not found: {yaml_path}")

    with open(yaml_path, 'r', encoding='utf-8') as f:
        root_path = yaml_path.parent
        world_info = yaml.safe_load(f)
    
    print(f"Loaded world definition from {yaml_path}")
    
    room.create_rooms(yaml_path.parent / "rooms")
    
    return world_info

root_path = None
world_info = None
