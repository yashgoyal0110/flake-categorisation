# Changing what it says

Three levers, in the order you are likely to reach for them.

## 1. Add a pattern

`flaketriage/classify/heuristic.py`. `RULES` is an ordered list, and the first match wins, so put
the specific thing above the general one.

```python
(
    Category.RESOURCE, 0.85,
    "the runner ran out of a resource",
    "Check disk and memory headroom, and whether the job leaks containers.",
    ("no space left on device", "address already in use", ...),
),
```

Order is a real decision, not a formality. A disk-full runner usually also produces connection
errors, so RESOURCE sits above NETWORK. Reversed, the report would tell somebody to retry the pull
while the disk is full.

Add a test next to it. `tests/test_heuristic.py` is fast, needs nothing, and it is the only thing
stopping the rules from quietly contradicting each other as they grow.

## 2. Change the categories

`Category` in `flaketriage/models.py`, and the list inside `SYSTEM_PROMPT` in
`classify/ollama.py`. Both, or the model will return a category the parser rejects and every
verdict will silently fall back to the heuristic.

The test for whether a new category earns its place is whether it changes what a maintainer would
do next. If two categories lead to the same action, they are one category with two names, and the
only thing you have added is a new way for the classifier to be wrong.

## 3. Change the prompt

`SYSTEM_PROMPT` in `classify/ollama.py`. Worth knowing before you edit it:

- `format: json` and `temperature: 0` are set in the request, not the prompt. Asking the model
  nicely for JSON is much weaker than making the decoder enforce it.
- The parser rejects anything that is not one object with a known category and a non-empty
  summary. Loosening the prompt without loosening the parser just increases the fallback rate,
  which will show up as `heuristic (fell back: ...)` in the `classifier` column.
- "Prefer unknown over a confident guess" is load-bearing. Take it out and the model will fill
  every row, which reads better and is worse.

## Checking a change actually helped

```
flaketriage --db before.db classify --backend heuristic
# edit
flaketriage --db after.db classify --backend heuristic
```

There is no scoring harness here yet, and that is the honest gap. Comparing two runs by eye works
at fifteen samples and stops working somewhere around a hundred. A labelled set of real failures
and a confusion matrix against it is the first thing I would build before trusting any prompt
change.
