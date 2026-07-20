import shutil
import subprocess
import sys
import yaml
from pathlib import Path

def run_image_subprocess(
    script: Path,
    temp_output: Path,
    log_label: str,
    extra_args: list | None = None,
) -> None:
    """Run the make-image script as a subprocess.

    Streams stdout/stderr to the console with the given log_label prefix.
    Raises ValueError on non-zero exit, missing output file, or non-PNG output.
    """
    cmd = [sys.executable, str(script), str(temp_output), "--size", "256x256", *(extra_args or [])]
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    except OSError as err:
        raise ValueError(str(err)) from err
    captured_lines: list[str] = []
    if proc.stdout is not None:
        for raw_line in proc.stdout:
            line = raw_line.rstrip("\n")
            captured_lines.append(line)
            print(f"[make-image:{log_label}] {line}", flush=True)
    return_code = proc.wait()
    if return_code != 0:
        raise ValueError("\n".join(captured_lines).strip() or "image generation failed")
    if not temp_output.exists():
        raise ValueError("image output missing")
    if temp_output.suffix.lower() != ".png":
        raise ValueError("image output must be png")


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
