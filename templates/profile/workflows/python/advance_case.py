"""Schedule and resume short CAD case tasks from saved, revision-bound evidence."""

import argparse
from hashlib import file_digest as hash_stream, sha256
import json
from itertools import count
from pathlib import Path
import sys
from uuid import uuid4


def digest(value):
    return sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def file_digest(path):
    with path.open("rb") as source:
        return hash_stream(source, "sha256").hexdigest()


class Case:
    def __init__(self, root):
        self.root = root.resolve()
        self.state = self.root / "workflow-state"
        self.metadata = self.root / "case.json"
        data = json.loads(self.metadata.read_text(encoding="utf-8"))
        self.source = Path(data["input"])
        self.records = {}

    def task(self, key, role, base, inputs, outcomes=("ok",)):
        return dict(key=key, role=role, base=base, inputs=inputs, outcomes=list(outcomes))

    def task_folder(self, ticket):
        return self.state / ticket[:32]

    def saved(self, task):
        folder = self.task_folder(digest(task))
        for path in folder.glob("result.json"):
            record = json.loads(path.read_text(encoding="utf-8"))
            if record["task"] != task:
                continue
            try:
                if all(file_digest(Path(p)) == checksum for p, checksum in record["evidence"].items()):
                    self.records[digest(record)] = (path, record)
                    return record
            except FileNotFoundError:
                continue
        return None

    def next(self):
        self.records.clear()
        def chain(key, role, base, inputs, outcomes=("ok",)):
            task = self.task(key, role, base, inputs, outcomes)
            record = self.saved(task)
            if record is None:
                pending.append(task)
            return record

        pending = []
        seed = [file_digest(self.metadata), file_digest(self.source)]
        extraction = chain("B1", "assembly-extractor", "extract-and-verify", seed)
        if extraction is None:
            return pending
        parts = extraction["placements"]
        approvals = []
        for part in parts:
            previous = digest(extraction)
            for attempt in count(1):
                proposal = chain(f"B2/propose/{part}/{attempt}", "simplification-proposer",
                                 "prepare-and-check-proposal", [previous])
                if proposal is None:
                    break
                review = chain(f"B2/check/{part}/{attempt}", "b3-checker",
                               "prepare-and-check-proposal", [digest(proposal)], ("presentable", "revise"))
                if review is None:
                    break
                if review["outcome"] == "revise":
                    previous = digest(review)
                    continue
                approval = chain(f"B2/approve/{part}/{attempt}", "user",
                                 "prepare-and-check-proposal", [digest(proposal), digest(review)],
                                 ("approved", "revise"))
                if approval is None:
                    break
                if approval["outcome"] == "revise":
                    previous = digest(approval)
                    continue
                approvals.append(digest(approval))
                break
        if pending:
            return pending
        final = chain("B2/final", "user", "prepare-and-check-proposal", approvals, ("approved",))
        if final is None:
            return pending

        checked = []
        for part in parts:
            previous = digest(final)
            for attempt in count(1):
                built = chain(f"B3/{part}/{attempt}", "b3-worker", "rebuild-and-evaluate", [previous])
                if built is None:
                    break
                verdict = chain(f"B4/{part}/{attempt}", "b4-checker", "rebuild-and-evaluate",
                                [digest(built)], ("ok", "revise"))
                if verdict is None:
                    break
                if verdict["outcome"] == "revise":
                    previous = digest(verdict)
                    continue
                checked.append(digest(verdict))
                break
        if pending:
            return pending

        previous = checked
        reassemble = True
        for cycle in count(1):
            if reassemble:
                built = chain(f"B5.1/build/{cycle}", "assembly-space-author", "review-assembly", previous)
                if built is None:
                    return pending
                reviewed = chain(f"B5.1/check/{cycle}", "b3-checker", "review-assembly",
                                 [digest(built)], ("ok", "revise"))
                if reviewed is None:
                    return pending
                previous = [digest(reviewed)]
                if reviewed["outcome"] == "revise":
                    continue
            space = chain(f"B5.2/build/{cycle}", "assembly-space-author", "review-space", previous)
            if space is None:
                return pending
            verdict = chain(f"B5.2/check/{cycle}", "b3-checker", "review-space",
                            [digest(space)], ("ok", "repair", "reassemble"))
            if verdict is None:
                return pending
            previous = [digest(verdict)]
            if verdict["outcome"] == "ok":
                break
            reassemble = verdict["outcome"] == "reassemble"
            if reassemble:
                continue
            repair_inputs = previous
            for attempt in count(1):
                repair = chain(f"B5.3/repair/{cycle}/{attempt}", "assembly-space-author",
                               "repair-space", repair_inputs)
                if repair is None:
                    return pending
                review = chain(f"B5.3/check/{cycle}/{attempt}", "b3-checker", "repair-space",
                               [digest(repair)], ("ok", "reassemble", "revise"))
                if review is None:
                    return pending
                previous = [digest(review)]
                if review["outcome"] != "revise":
                    reassemble = review["outcome"] == "reassemble"
                    break
                repair_inputs = previous

        delivered = chain("B5/deliver", "coordinator", "review-space", previous)
        if delivered is None:
            return pending
        improvements = chain("B6/propose", "memory-reflection", "reflect-case", [digest(delivered)])
        if improvements is None:
            return pending
        adoption = chain("B6/adopt", "user", "reflect-case", [digest(improvements)], ("approved", "declined"))
        if adoption is None:
            return pending
        result = adoption
        if adoption["outcome"] == "approved":
            result = chain("B6/apply", "memory-reflection", "reflect-case", [digest(adoption)])
            if result is None:
                return pending
        chain("B6/report", "coordinator", "reflect-case", [digest(result)])
        return pending

    def record(self, ticket, outcome, files, placements, revision=None):
        task = next((item for item in self.next() if digest(item) == ticket), None)
        if task is None or outcome not in task["outcomes"]:
            raise ValueError("Ticket is stale or the outcome is invalid. Run status again.")
        if task["key"] == "B1":
            if not placements or len(set(placements)) != len(placements):
                raise ValueError("B1 requires the unique placement IDs from the checked extraction.")
        elif placements:
            raise ValueError("Placement inventory belongs to B1.")
        if task["key"].startswith(("B2/propose/", "B2/check/", "B2/approve/")):
            if not revision:
                raise ValueError("B2 requires the displayed proposal revision.")
            if not task["key"].startswith("B2/propose/"):
                expected = self.records[task["inputs"][0]][1]["proposal_revision"]
                if revision != expected:
                    raise ValueError("The proposal revision does not match the saved proposal.")
        elif revision is not None:
            raise ValueError("Proposal revision is only used for placement-level B2.")
        evidence = {}
        for file in files:
            path = file.resolve(strict=True)
            if not path.is_relative_to(self.root) or path.is_relative_to(self.state):
                raise ValueError("Evidence must be a case artifact outside workflow-state.")
            if path == self.root / "improvements.md":
                raise ValueError("Save a snapshot of improvements.md as evidence.")
            evidence[str(path)] = file_digest(path)
        if task["key"].startswith("B2/approve/") and outcome == "approved":
            part = task["key"].removeprefix("B2/approve/").rsplit("/", 1)[0]
            confirmed = False
            for name in evidence:
                path = Path(name)
                if path.suffix != ".json":
                    continue
                data = json.loads(path.read_text(encoding="utf-8"))
                saved = data.get("parts", {}).get(part, {}) if isinstance(data, dict) else {}
                if (saved.get("proposal_revision") == revision
                        and saved.get("approval_source") == "human_part_confirmation"):
                    confirmed = True
                    break
            if not confirmed:
                raise ValueError("Provide a snapshot of the matching B2 human confirmation.")
        record = dict(id=uuid4().hex, task=task, outcome=outcome, evidence=evidence, placements=placements,
                      dependencies=self.describe(task)["dependency_records"],
                      proposal_revision=revision)
        folder = self.task_folder(ticket)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "result.json"
        if path.exists():
            # A result with changed evidence is stale even if its task inputs match.
            path.rename(path.with_name(f"superseded-{uuid4().hex}.json"))
        with path.open("x", encoding="utf-8") as output:
            json.dump(record, output, ensure_ascii=False, indent=2)
        return path

    def reopen(self, key):
        self.next()
        for path, record in self.records.values():
            if record["task"]["key"] == key:
                history = path.with_name(f"superseded-{uuid4().hex}.json")
                path.rename(history)
                return history
        raise ValueError("There is no current result for that task.")

    def describe(self, task):
        return dict(task, ticket=digest(task), dependency_records=[
            str(self.records[key][0]) for key in task["inputs"] if key in self.records
        ])

    def dispatch(self, ticket):
        task = next((item for item in self.next() if digest(item) == ticket), None)
        if task is None:
            raise ValueError("Ticket is stale. Run status again.")
        profile = Path(__file__).resolve().parents[2]
        sys.path.insert(0, str(profile.parents[1] / "tools"))
        from agent_roles import load_role
        instructions = None if task["role"] == "user" else load_role(task["role"])
        return dict(self.describe(task), case=str(self.root), instructions=instructions,
                    procedure=(profile / "workflows" / "base" / (task["base"] + ".md"))
                    .read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case", type=Path)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status")
    dispatch = commands.add_parser("dispatch")
    dispatch.add_argument("ticket")
    record = commands.add_parser("record")
    record.add_argument("ticket")
    record.add_argument("outcome")
    record.add_argument("--evidence", type=Path, action="append", required=True)
    record.add_argument("--placement", action="append", default=[])
    record.add_argument("--proposal-revision")
    reopen = commands.add_parser("reopen")
    reopen.add_argument("key")
    args = parser.parse_args()
    try:
        case = Case(args.case)
        if args.command == "status":
            pending = case.next()
            print(json.dumps([case.describe(task) for task in pending], indent=2))
        elif args.command == "dispatch":
            print(json.dumps(case.dispatch(args.ticket), indent=2))
        elif args.command == "reopen":
            print(case.reopen(args.key))
        else:
            print(case.record(args.ticket, args.outcome, args.evidence, args.placement,
                              args.proposal_revision))
    except (ValueError, OSError, KeyError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
