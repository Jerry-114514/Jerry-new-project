"""Wait for the supervisor to persist this child's PID before importing ML."""

import argparse
import json
import os
from pathlib import Path
import sys
import time


def wait_for_ack(path, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            ack = json.loads(path.read_text(encoding="utf-8"))
            if ack.get("pid") != os.getpid() or path.stem != ack.get("attempt", "") + ".ack":
                raise ValueError("Worker acknowledgement does not identify this process and attempt")
            return
        time.sleep(0.1)
    raise TimeoutError("Supervisor did not acknowledge recorded worker PID; training was not started")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ack", type=Path, required=True)
    args, training_args = parser.parse_known_args()
    wait_for_ack(args.ack)
    # No model/tokenizer/dependency import happens before authorization.
    from .neural import main as train_main
    train_main(training_args)


if __name__ == "__main__":
    main()
