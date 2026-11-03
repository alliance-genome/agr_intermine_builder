#!/usr/bin/env python3
"""Docker CLI stand-in for launcher subprocess tests."""

import json
import os
import signal
import sys
from pathlib import Path

record = Path(os.environ["COMMAND_RECORD"])
if os.environ.get("COMMAND_WAIT"):

    def cancelled(number, frame):
        record.with_suffix(".stopped").write_text(str(number))
        raise SystemExit(128 + number)

    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(number, cancelled)

record.write_text(
    json.dumps(
        {
            "args": sys.argv[1:],
            "cwd": os.getcwd(),
            "rc": os.environ.get("RC_NUMBER"),
            "pid": os.getpid(),
        }
    )
)
print("container stdout", flush=True)
print("container stderr", file=sys.stderr, flush=True)
if os.environ.get("COMMAND_WAIT"):
    signal.pause()
sys.exit(int(os.environ.get("COMMAND_EXIT", "0")))
