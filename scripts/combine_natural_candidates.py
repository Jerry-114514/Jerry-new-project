"""Coordinator-only merge of fixed natural development runs and base cases."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from intentlab.combine_natural_data import build

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('base','selection','execution','out'):
        parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args()
    result=build(args.base,args.selection,args.execution,args.out)
    print(json.dumps({k:result[k] for k in ['views_by_split','source_groups_by_split','natural_views','heldout_cases_and_gold_byte_identical','formal_protocol_frozen']},indent=2))
