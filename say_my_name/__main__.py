"""Command line: generate, match, evaluate, or run all three."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .evaluate import evaluate
from .generator import write_dataset
from .matcher import match


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="say_my_name", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    gen = sub.add_parser("generate", help="write a synthetic dataset")
    gen.add_argument("--seed", type=int, required=True)
    gen.add_argument("--companies", type=int, default=1000)
    gen.add_argument("--out", type=Path, required=True)

    mat = sub.add_parser("match", help="run the matcher on records.csv")
    mat.add_argument("--records", type=Path, required=True)
    mat.add_argument("--out", type=Path, required=True)

    ev = sub.add_parser("evaluate", help="score a match run against truth.csv")
    ev.add_argument("--records", type=Path, required=True)
    ev.add_argument("--truth", type=Path, required=True)
    ev.add_argument("--out", type=Path, required=True)

    run = sub.add_parser("run", help="generate + match + evaluate")
    run.add_argument("--seed", type=int, required=True)
    run.add_argument("--companies", type=int, default=1000)
    run.add_argument("--name", required=True, help="folder name under data/ and out/")

    adj = sub.add_parser("adjudicate", help="phase 3: an LLM decides the REVIEW pairs of a run")
    adj.add_argument("--name", required=True, help="run folder under data/ and out/ (run `run` first)")
    adj.add_argument("--model", choices=["haiku", "sonnet"], default="haiku")
    adj.add_argument("--effort", choices=["low", "medium", "high"], default="medium")
    adj.add_argument("--limit", type=int, help="decide only a fixed sample of N pairs")
    adj.add_argument("--workers", type=int, default=8, help="parallel API calls")
    adj.add_argument("--dry-run", action="store_true", help="show a prompt and a cost estimate, no API calls")

    args = parser.parse_args(argv)
    if args.command == "generate":
        write_dataset(args.out, args.seed, args.companies)
    elif args.command == "match":
        print(json.dumps(match(args.records, args.out), indent=2))
    elif args.command == "adjudicate":
        from .adjudicate import run as adjudicate

        result = adjudicate(args.name, args.model, args.effort, args.limit, args.workers, args.dry_run)
        if not args.dry_run:
            report = Path("out") / args.name / f"llm-{args.model}-{args.effort}" / "report.md"
            print(report.read_text(encoding="utf-8"))
        else:
            print(json.dumps(result))
    elif args.command == "evaluate":
        evaluate(args.records, args.truth, args.out)
        print((args.out / "report.md").read_text(encoding="utf-8"))
    else:
        records, truth = write_dataset(Path("data") / args.name, args.seed, args.companies)
        out = Path("out") / args.name
        match(records, out)
        evaluate(records, truth, out)
        print((out / "report.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
