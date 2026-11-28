"""Initialize the CAD Rebuilder workspace and create case directories."""

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / "local"
TEMPLATE = ROOT / "templates" / "profile"


def initialize():
    for directory in ("input", "profile", "part-rules", "cases"):
        (LOCAL / directory).mkdir(parents=True, exist_ok=True)
    for source in TEMPLATE.rglob("*"):
        if source.is_file() and "__pycache__" not in source.parts:
            target = LOCAL / "profile" / source.relative_to(TEMPLATE)
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                with target.open("xb") as output:
                    output.write(source.read_bytes())
            except FileExistsError:
                pass


def start(input_path, analysis, precision, workflow):
    source = input_path.resolve(strict=True)
    if not source.is_file() or source.suffix.lower() not in {".step", ".stp"}:
        raise ValueError("Select a STEP file.")
    initialize()
    if Path(workflow).name != workflow or not (LOCAL / "profile" / "workflows" / workflow).is_file():
        raise ValueError("Select a Python workflow in local/profile/workflows.")
    case = LOCAL / "cases" / source.stem
    case.mkdir()
    for name in ("review", "artifacts"):
        (case / name).mkdir()
    metadata = {"schema_version": 1, "input": str(source), "analysis": analysis,
                "precision": precision, "workflow": workflow}
    (case / "case.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (case / "improvements.md").write_text("# Improvements\n", encoding="utf-8")
    return case


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init")
    begin = commands.add_parser("start")
    begin.add_argument("input", type=Path)
    begin.add_argument("--analysis", required=True)
    begin.add_argument("--precision", default="default")
    begin.add_argument("--workflow", default="trial_rebuild_step_part.py")
    args = parser.parse_args()
    try:
        if args.command == "init":
            initialize()
        else:
            print(start(args.input, args.analysis, args.precision, args.workflow))
    except (OSError, ValueError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
