"""Export accepted B2 decisions for B3 and B5."""

import argparse
import json
from pathlib import Path

from b2_faces import load_parts, write_json
from b2_review import make_handoff, open_review


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("candidates", type=Path)
    parser.add_argument("review", type=Path)
    parser.add_argument("output", type=Path, help="New B3 handoff file")
    parser.add_argument("--simplification-review", type=Path,
                        help="Defaults to CONTACT_REVIEW_STEM.simplification.json")
    args = parser.parse_args()
    try:
        if not args.review.is_file():
            raise ValueError("Save a review before exporting")
        if args.output.exists():
            raise ValueError(f"Output already exists: {args.output}")
        digest, parts = load_parts(args.bundle)
        _, draft = open_review(digest, parts, args.candidates, args.review)
        simplification_path = args.simplification_review or args.review.with_name(args.review.stem+".simplification.json")
        if not simplification_path.is_file():
            raise ValueError("Complete the simplification review before exporting")
        simplification = json.loads(simplification_path.read_text(encoding="utf-8"))
        write_json(args.output, make_handoff(draft, parts, simplification))
    except (OSError, ValueError, RuntimeError, TypeError, KeyError) as error:
        parser.exit(1, f"Template input export failed: {error}\n")


if __name__ == "__main__":
    main()
