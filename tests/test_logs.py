from flaketriage.logs import clean, reduce_log, signal_lines


def test_clean_strips_timestamp_and_colour():
    line = "2026-08-03T10:00:00.1234567Z \x1b[31mError: boom\x1b[0m"
    assert clean(line) == "Error: boom"


def test_reduce_keeps_the_failure_and_what_led_to_it():
    lines = [f"2026-08-03T10:00:0{i % 10}.0000000Z setup step {i}" for i in range(500)]
    lines.append("2026-08-03T10:01:00.0000000Z [FAILED] Expected 0 to equal 1")
    lines += [f"2026-08-03T10:01:0{i}.0000000Z teardown {i}" for i in range(20)]

    out = reduce_log("\n".join(lines))

    assert "[FAILED] Expected 0 to equal 1" in out
    assert "setup step 0" not in out, "should not drag in the whole log"
    assert len(out) < 6100


def test_reduce_falls_back_to_the_tail_when_nothing_matches():
    # Better to return the end of the log than nothing at all.
    raw = "\n".join(f"line {i}" for i in range(200))
    out = reduce_log(raw, context_lines=10)
    assert "line 199" in out
    assert "line 0" not in out


def test_reduce_handles_an_empty_log():
    assert reduce_log("") == ""
    assert reduce_log("\n\n\n") == ""


def test_last_failure_wins():
    # A job that fails, retries something internally, then fails again should be read at the end.
    raw = "\n".join([
        "[FAILED] first attempt, later recovered",
        *[f"noise {i}" for i in range(100)],
        "[FAILED] the one that actually ended the run",
        "teardown",
    ])
    out = reduce_log(raw, context_lines=5)
    assert "the one that actually ended the run" in out
    assert "first attempt" not in out


def test_signal_lines_are_deduplicated():
    excerpt = "\n".join([
        "Error: pull failed",
        "some detail",
        "Error: pull failed",
        "[FAILED] Expected success",
    ])
    assert signal_lines(excerpt) == ["Error: pull failed", "[FAILED] Expected success"]


def test_a_test_failure_beats_the_job_level_error():
    # GitHub appends "##[error]Process completed with exit code N" after the post-steps, so it is
    # always the last marker and always the least useful one. Anchoring there put every real
    # Podman excerpt inside artifact-upload boilerplate.
    raw = "\n".join([
        *[f"setup {i}" for i in range(80)],
        "not ok 42 |450| podman volume export should fail",
        *[f"Uploading artifact chunk {i}" for i in range(80)],
        "##[error]Process completed with exit code 2.",
    ])
    out = reduce_log(raw, context_lines=20)
    assert "not ok 42" in out
    assert "Uploading artifact chunk 79" not in out


def test_the_job_level_error_is_still_used_when_nothing_better_exists():
    raw = "\n".join([*[f"line {i}" for i in range(50)],
                     "##[error]Process completed with exit code 1."])
    assert "##[error]" in reduce_log(raw, context_lines=10)
