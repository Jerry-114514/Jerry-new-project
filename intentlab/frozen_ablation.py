"""M7 first-stage controls, fixed before held-out evaluation and gated on M6."""

import argparse
import json
from pathlib import Path

from . import frozen_execution as execution
from .protocol import read_json


def interact(protocol, binding, predictions, diagnostic_reveal, execution_interactions, execution_reveal, out,
             engineering=False, pool_factory=None):
    return execution.interact(protocol, binding, predictions, diagnostic_reveal, out, engineering, pool_factory,
                              _ablation_context=(execution_interactions, execution_reveal))


def verify_interactions(protocol, binding, predictions, diagnostic_reveal, execution_interactions, execution_reveal,
                        directory, engineering=False):
    return execution.verify_interactions(protocol, binding, predictions, diagnostic_reveal, directory, engineering,
                                        _ablation_context=(execution_interactions, execution_reveal))


def reveal(protocol, binding, predictions, diagnostic_reveal, execution_interactions, execution_reveal,
           interactions, out, engineering=False):
    return execution.reveal(protocol, binding, predictions, diagnostic_reveal, interactions, out, engineering,
                            _ablation_context=(execution_interactions, execution_reveal))


def verify_scoring(protocol, binding, predictions, diagnostic_reveal, execution_interactions, execution_reveal,
                   interactions, directory, engineering=False):
    return execution.verify_scoring(protocol, binding, predictions, diagnostic_reveal, interactions, directory, engineering,
                                    _ablation_context=(execution_interactions, execution_reveal))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["interact", "verify", "reveal", "verify-reveal"])
    for name in ("protocol", "binding", "predictions", "diagnostic-reveal", "execution-interactions", "execution-reveal"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--interactions", type=Path)
    parser.add_argument("--ablation-reveal", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--engineering", action="store_true")
    args = parser.parse_args()
    common = (read_json(args.protocol), read_json(args.binding), args.predictions, args.diagnostic_reveal,
              args.execution_interactions, args.execution_reveal)
    if args.command == "interact":
        if args.out is None:
            parser.error("interact requires --out")
        result = interact(*common, args.out, args.engineering)
    else:
        if args.interactions is None:
            parser.error("verify/reveal requires --interactions")
        if args.command == "verify":
            result = verify_interactions(*common, args.interactions, args.engineering)[0]
        elif args.command == "reveal":
            if args.out is None:
                parser.error("reveal requires --out")
            result = reveal(*common, args.interactions, args.out, args.engineering)
        else:
            if args.ablation_reveal is None:
                parser.error("verify-reveal requires --ablation-reveal")
            result = verify_scoring(*common, args.interactions, args.ablation_reveal, args.engineering)
    print(json.dumps({key: result[key] for key in ("status", "scope", "protocol_hash")}, indent=2))


if __name__ == "__main__":
    main()
