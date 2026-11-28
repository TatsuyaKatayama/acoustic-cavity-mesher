"""Send a STEP assembly or BREP to the local OCP web viewer."""

import argparse
from pathlib import Path

import cadquery as cq

from b4_geometry import read_brep


def load_model(path):
    extension = path.suffix.lower()
    if extension in (".step", ".stp"):
        return cq.Assembly.load(str(path), importType="STEP")
    if extension == ".brep":
        return cq.Shape.cast(read_brep(path.read_bytes()))
    raise ValueError("Use a .step, .stp or .brep file")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model", type=Path, help="STEP assembly or BREP from the workflow")
    parser.add_argument("--port", type=int, default=3939)
    parser.add_argument("--camera", default="iso",
                        choices=("iso", "front", "back", "left", "right", "top", "bottom"))
    parser.add_argument("--png", type=Path, help="Save the browser view to a new PNG")
    args = parser.parse_args()
    try:
        from ocp_viewer import Camera, save_screenshot, show

        if args.png is not None and (args.png.suffix.lower() != ".png" or args.png.exists()):
            raise ValueError("--png requires a new .png path")
        show(load_model(args.model), port=args.port, reset_camera=getattr(Camera, args.camera.upper()))
        if args.png is not None:
            path = args.png.resolve()
            path.parent.mkdir(parents=True, exist_ok=True)
            save_screenshot(str(path), port=args.port)
            if not path.is_file() or path.stat().st_size == 0:
                raise RuntimeError("No PNG received. Open the local viewer page and retry.")
            print(path)
    except ImportError as error:
        parser.exit(1, f"Web viewer dependency missing: {error}\n")
    except (OSError, ValueError, RuntimeError) as error:
        parser.exit(1, f"Web preview failed: {error}\n")


if __name__ == "__main__":
    main()
