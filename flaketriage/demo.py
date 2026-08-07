"""Sample data, so the dashboard shows something without a token or a network call.

The job names and log lines are modelled on Podman's actual matrix and the kinds of failure that
turn up in it. It is synthetic, and labelled as such in the UI, but the shape is right, which is
enough to judge whether the reporting is useful before wiring up a real repository.
"""

from __future__ import annotations

from .classify.heuristic import HeuristicClassifier
from .models import Flake
from .store import Store

SAMPLES: list[tuple[str, str, str]] = [
    ("int local rootless fedora-rawhide", "rerun-passed",
     "Error: initializing source docker://quay.io/libpod/testimage:20241011: "
     "pinging container registry quay.io: Get \"https://quay.io/v2/\": "
     "dial tcp 34.225.10.1:443: i/o timeout"),
    ("int local rootless fedora-rawhide", "rerun-passed",
     "Error: pinging container registry quay.io: connection reset by peer"),
    ("int remote root fedora-current", "same-sha-passed",
     "[FAILED] Timed out after 90.001s.\nExpected container to be running\n"
     "context deadline exceeded waiting for container to start"),
    ("int remote root fedora-current", "rerun-passed",
     "[FAILED] timed out waiting for the healthcheck to report healthy"),
    ("sys local root debian-sid", "rerun-passed",
     "# copying system image from manifest list: writing blob: "
     "write /var/tmp/container_images_storage: no space left on device"),
    ("sys local root debian-sid", "same-sha-passed",
     "Error: mkdir /var/lib/containers/storage/overlay: no space left on device"),
    ("sys local rootless fedora-prior", "rerun-passed",
     "Error response from daemon: manifest unknown: manifest unknown\n"
     "##[error]Process completed with exit code 125."),
    ("machine-linux", "rerun-passed",
     "The runner has received a shutdown signal. "
     "This can happen when the runner service is stopped."),
    ("unit local root fedora-current", "same-sha-passed",
     "--- FAIL: TestParseNetworkFlag (0.00s)\n"
     "    network_test.go:112: expected 0 to equal 1"),
    ("apiv2 local root fedora-current", "rerun-passed",
     "Error: unable to connect to Podman socket: "
     "Get \"http://d/v5.0.0/libpod/_ping\": dial unix /run/podman/podman.sock: connect: "
     "connection refused"),
    ("int local rootless fedora-rawhide", "rerun-passed",
     "Error: cannot listen on the TCP port: listen tcp4 :8080: bind: address already in use"),
    ("bud local root fedora-current", "same-sha-passed",
     "error building at STEP \"RUN dnf -y install golang\": "
     "Curl error (28): Timeout was reached for https://mirrors.fedoraproject.org"),
    ("windows-e2e", "rerun-passed",
     "The operation was canceled.\n##[error]The operation was canceled."),
    ("int remote rootless fedora-current", "same-sha-passed",
     "panic: send on closed channel\n\ngoroutine 214 [running]:\n"
     "WARNING: DATA RACE detected in libpod/container_internal.go"),
    ("sys remote root fedora-current", "rerun-passed",
     "Cannot connect to the container registry: temporary failure in name resolution"),
]


def load_sample_data(store: Store) -> int:
    classifier = HeuristicClassifier()
    for index, (job_name, detected_by, excerpt) in enumerate(SAMPLES, start=1):
        flake = Flake(
            job_id=900000 + index,
            run_id=8800 + (index % 5),
            run_attempt=1,
            job_name=job_name,
            head_sha=f"{index:07x}deadbeef",
            html_url=f"https://github.com/containers/podman/actions/runs/{8800 + index}",
            detected_by=detected_by,
            failed_at=f"2026-08-{(index % 7) + 1:02d}T{(index % 12) + 8:02d}:15:00Z",
            excerpt=excerpt,
        )
        flake.verdict = classifier.classify(flake)
        store.save(flake)
    return len(SAMPLES)
