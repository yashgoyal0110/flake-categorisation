# flaketriage

Pulls failing GitHub Actions jobs, works out which failures were flakes, categorises why, and puts
it on a dashboard and in a weekly report.

Python 3.11+, no runtime dependencies, no API key needed to try it.

## Why

I'm applying to build agentic CI flake analysis for Podman. This is a small version of the same
idea, so the proposal is something you can run instead of something you have to take my word for.
I have not contributed to Podman before, so it seemed better to show the shape of what I mean.

## Try it

```
pip install -e .
flaketriage demo      # 15 sample failures modelled on Podman's real matrix
flaketriage serve     # dashboard on :8000
flaketriage report    # markdown digest
```

Against a real repository:

```
export GITHUB_TOKEN=...
flaketriage ingest containers/podman --workflow ci.yml --runs 50
flaketriage classify --backend heuristic     # or --backend ollama
flaketriage report --issues
```

## How it works

**Detect.** Two rules, because "what counts as a flake" is a decision, not a fact.
`rerun-passed` is red then green on the same run, which is nearly ground truth but only exists
when a human clicked re-run. `same-sha-passed` is one commit producing both a pass and a failure,
which catches far more and is occasionally fooled by the environment changing between runs.

**Reduce.** A failed job log is tens of thousands of lines. Handing all of it to a model is slow,
expensive and worse, because the model starts explaining the package manager. `logs.py` cuts it to
the block around the last failure marker. Podman already does the equivalent for step summaries in
`hack/ci/github_log_summary.py`, over the HTML artifact rather than the plain-text job log.

**Classify.** One interface, two backends. `heuristic` is pattern matching with no key and no
network. `ollama` is a local model. Both return the same `Verdict`, and both are allowed to answer
`unknown`.

**Report.** Failures are grouped into signatures before anything is filed, because one issue per
occurrence means forty issues about one registry timeout, and the next thing that happens is
somebody mutes the bot.

## Two decisions worth arguing with

**The heuristic backend is not a fallback, it is the baseline.** Without something to compare
against there is no way to say whether a model is earning its cost. It also means the tool runs in
CI and on a laptop with nothing configured.

**The model is treated as a component that fails.** It is asked for one JSON object with a fixed
shape at temperature 0. An invented category, prose instead of JSON, an empty summary or an
unreachable host all fall back to the heuristic and say so in the output. `test_ollama.py` is
mostly a list of ways the model can misbehave, because that is the interesting half.

## Dimensions do most of the work

Podman names jobs `<test> <mode> <priv> <distro>` and uploads logs under the same shape, so the
matrix axes are available before anything reads a log line. That is why the report can say:

```
| 2 | resource | sys | always debian-sid, always root, always local |
| 2 | network  | int | always fedora-rawhide, always rootless      |
```

"Always rootless on rawhide" is usually the whole diagnosis. "12 flakes" is not.

## Deploy it

```
docker compose up -d --build          # http://127.0.0.1:8123
```

With no `GITHUB_TOKEN` it loads the sample data, so the dashboard is never empty. With one, it
ingests real runs on start and every hour after:

```
echo "GITHUB_TOKEN=ghp_..." > .env
echo "FLAKE_REPO=containers/podman" >> .env
docker compose up -d --build
```

The container binds to localhost only. Put a reverse proxy in front of it, because the dashboard
is read-only but has no authentication:

```
flakes.example.com {
    reverse_proxy 127.0.0.1:8123
}
```

The database is on a named volume, so a redeploy keeps the flake history, which is the one thing
here that gets more useful the longer it runs.

## Not here

Correlating the same failing test across unrelated pull requests, which would catch the most and
needs a stable test identity parsed out of the log. Getting that wrong quietly poisons the data, so
it wants agreeing first. Also no hosted-model backend, no auto-filing against a live repo, and the
sample data is synthetic.
