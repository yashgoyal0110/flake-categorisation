"""Command line entry point."""

from __future__ import annotations

import argparse
import sys

from . import classify as classifiers
from .github import GitHub
from .pipeline import classify_pending, ingest
from .report import group, issue_body, issue_title, weekly_digest
from .store import Store


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="flaketriage", description=__doc__)
    parser.add_argument("--db", default="flakes.db")
    sub = parser.add_subparsers(dest="command", required=True)

    p_ingest = sub.add_parser("ingest", help="fetch recent runs and record the flakes")
    p_ingest.add_argument("repo", help="owner/name")
    p_ingest.add_argument("--workflow", default="ci.yml")
    p_ingest.add_argument("--runs", type=int, default=25)
    p_ingest.add_argument("--created", help="GitHub date filter, e.g. >=2026-08-01")

    p_classify = sub.add_parser("classify", help="categorise anything not yet categorised")
    p_classify.add_argument("--backend", default="heuristic", choices=["heuristic", "ollama"])
    p_classify.add_argument("--model", default="llama3.1:8b")
    p_classify.add_argument("--limit", type=int, default=100)

    p_report = sub.add_parser("report", help="print a markdown digest")
    p_report.add_argument("--since", default="", help="ISO timestamp")
    p_report.add_argument("--issues", action="store_true",
                          help="print issue titles and bodies instead of a digest")

    sub.add_parser("demo", help="load sample data so the dashboard has something to show")

    p_serve = sub.add_parser("serve", help="run the dashboard")
    p_serve.add_argument("--port", type=int, default=8000)
    p_serve.add_argument("--host", default="127.0.0.1",
                         help="0.0.0.0 to listen outside the container")

    args = parser.parse_args(argv)
    store = Store(args.db)

    if args.command == "ingest":
        client = GitHub(args.repo)
        runs = client.runs(workflow=args.workflow, per_page=args.runs, created=args.created)
        flakes = ingest(client, store, runs, log=_echo)
        print(f"stored {len(flakes)} flakes in {args.db}")
        return 0

    if args.command == "classify":
        backend = classifiers.get(args.backend, model=args.model) \
            if args.backend == "ollama" else classifiers.get(args.backend)
        count = classify_pending(store, backend, limit=args.limit, log=_echo)
        print(f"classified {count} flakes with {args.backend}")
        return 0

    if args.command == "report":
        flakes = store.since(args.since) if args.since else store.all()
        if args.issues:
            for sig, items in group(flakes).items():
                print(f"## {issue_title(sig, items)}\n")
                print(issue_body(sig, items))
                print("---\n")
        else:
            print(weekly_digest(flakes))
        return 0

    if args.command == "demo":
        from .demo import load_sample_data
        count = load_sample_data(store)
        print(f"loaded {count} sample flakes into {args.db}. now run: flaketriage serve")
        return 0

    if args.command == "serve":
        from .web import serve
        serve(store, port=args.port, host=args.host)
        return 0

    return 1


def _echo(message: str) -> None:
    print(message, file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
