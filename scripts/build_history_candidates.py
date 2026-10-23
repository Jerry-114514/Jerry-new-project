"""Coordinator-side construction only; never evaluate heldout model outputs."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from intentlab.history_candidate_data import build

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--base',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();result=build(a.base,a.out)
    print(json.dumps({k:result[k] for k in ['views_by_split','source_groups_by_split','history_views_by_split','formal_protocol_frozen']},indent=2))
