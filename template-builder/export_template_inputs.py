"""Export accepted B2 decisions for B3 and B5."""

import argparse
from pathlib import Path

from b2_faces import load_parts, write_json
from b2_review import make_handoff, open_review


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("candidates", type=Path)
    parser.add_argument("review", type=Path)
    parser.add_argument("output", type=Path, help="New B3 handoff file")
    args = parser.parse_args()
    try:
        if not args.review.is_file():
            raise ValueError("Save a review before exporting")
        if args.output.exists():
            raise ValueError(f"Output already exists: {args.output}")
        digest, parts = load_parts(args.bundle)
        _, draft = open_review(digest, parts, args.candidates, args.review)
        write_json(args.output, make_handoff(draft, parts))
    except (OSError, ValueError, RuntimeError, TypeError, KeyError) as error:
        parser.exit(1, f"Template input export failed: {error}\n")


if __name__ == "__main__":
    main()
