"""Extract a STEP assembly into a manifest and local part geometry."""

import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from b1_step import read_assembly


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path, help="New bundle directory")
    args = parser.parse_args()
    try:
        if args.output.exists():
            raise ValueError(f"Output already exists: {args.output}")
        manifest, definitions = read_assembly(args.source)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(dir=args.output.parent) as temp:
            bundle = Path(temp) / "bundle"
            parts = bundle / "parts"
            parts.mkdir(parents=True)
            for digest, data in definitions.items():
                (parts / f"{digest}.brep").write_bytes(data)
            (bundle / "assembly.json").write_text(
                json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )
            bundle.rename(args.output)
    except (OSError, ValueError, RuntimeError) as error:
        parser.exit(1, f"Extraction failed: {error}\n")


if __name__ == "__main__":
    main()
