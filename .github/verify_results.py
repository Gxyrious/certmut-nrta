from argparse import ArgumentParser
import json
from pathlib import Path


ARCHIVE = Path(__file__).resolve().parents[1] / "2_experiment_materials" / "run_data"
KEYS = {
    "learning_runs.json": ("group", "case", "method", "seed", "word_budget"),
    "certificate_counts.json": ("group", "case", "round"),
}


def compare(expected, actual, columns):
    def identity(row):
        return tuple(row[column] for column in columns)

    reference = {identity(row): row for row in expected}
    reproduced, errors = {}, []
    for row in actual:
        key = identity(row)
        if key in reproduced:
            errors.append(f"Duplicate record {key}")
        reproduced[key] = row

    errors.extend(f"Missing record {key}" for key in sorted(reference.keys() - reproduced.keys()))
    errors.extend(f"Unexpected record {key}" for key in sorted(reproduced.keys() - reference.keys()))
    matched = 0
    for key in sorted(reference.keys() & reproduced.keys()):
        before, after = reference[key], reproduced[key]
        fields = (before.keys() | after.keys()) - {"cumulative_delay"}
        changed = [f"{field} (expected {before.get(field)!r}, got {after.get(field)!r})"
                   for field in sorted(fields)
                   if field not in before or field not in after or before[field] != after[field]]
        if changed:
            errors.append(f"Different values for {key}: {', '.join(changed)}")
        else:
            matched += 1
    return matched, errors


def main():
    parser = ArgumentParser(description="Compare the regenerated experiment results with the archive.")
    parser.add_argument("shards", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    merged = {}
    failed = False
    print("## Reproduction results")
    print()
    for name, keys in KEYS.items():
        expected = json.loads((ARCHIVE / name).read_text())
        rows = [row for shard in sorted(args.shards.rglob(name)) for row in json.loads(shard.read_text())]
        matched, errors = compare(expected, rows, keys)
        print(f"- `{name}`: {matched}/{len(expected)} records match on checked fields ({len(rows)} generated).")
        for error in errors[:10]:
            print(f"  - {error}")
        if len(errors) > 10:
            print(f"  - {len(errors) - 10} more differences.")
        failed |= matched != len(expected) or bool(errors)
        merged[name] = rows

    if failed:
        raise SystemExit(1)

    args.output.mkdir(parents=True, exist_ok=True)
    for name, rows in merged.items():
        (args.output / name).write_text(json.dumps(rows, indent=2) + "\n")


if __name__ == "__main__":
    main()
