import yaml
from pathlib import Path

def load_defs(yaml_path, id_key_func=None):
    """
    Load definitions from YAML file or directory.
    Args:
        yaml_path: Path to YAML file or directory containing YAML files
        id_key_func: Optional function to generate ID from key and value dict.
                     If None, uses the key as-is.
    """
    yaml_path = Path(yaml_path)
    defs = {}
    if yaml_path.is_dir():
        for yaml_file in yaml_path.glob("*.yaml"):
            with open(yaml_file, 'r', encoding='utf-8') as f:
                loaded_defs = yaml.safe_load(f)
                if loaded_defs:
                    for key, value in loaded_defs.items():
                        if id_key_func:
                            def_id = id_key_func(key, value)
                        else:
                            def_id = key
                        
                        if def_id in defs:
                            print(f"Error: Definition '{def_id}' from '{yaml_file.name}' clashes with existing definition. Skipping.")
                        else:
                            defs[def_id] = value
    elif yaml_path.is_file():
        with open(yaml_path, 'r', encoding='utf-8') as f:
            loaded_defs = yaml.safe_load(f)
            if loaded_defs:
                if id_key_func:
                    for key, value in loaded_defs.items():
                        def_id = id_key_func(key, value)
                        defs[def_id] = value
                else:
                    defs.update(loaded_defs)
    else:
        raise FileNotFoundError(f"Path not found: {yaml_path}")
    print(f"Loaded {len(defs)} definitions from {yaml_path}")
    return defs
