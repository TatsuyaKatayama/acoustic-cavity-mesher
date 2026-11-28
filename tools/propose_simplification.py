"""Propose small faces for B2 review after all contact decisions are saved."""

import argparse
import json
from pathlib import Path

from b2_faces import load_parts
from b2_review import open_review
from b2_simplification import build_proposal


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("candidates", type=Path)
    parser.add_argument("review", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--threshold-mm", type=float, default=5)
    args = parser.parse_args()
    try:
        if not args.review.is_file():
            raise ValueError("Save a contact review first")
        digest, parts = load_parts(args.bundle)
        _, draft = open_review(digest, parts, args.candidates, args.review)
        record = build_proposal(parts, draft, args.threshold_mm)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(record, indent=2, ensure_ascii=False)+"\n")
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
        parser.exit(1, f"Simplification proposal failed: {exc}\n")


if __name__ == "__main__":
    main()
