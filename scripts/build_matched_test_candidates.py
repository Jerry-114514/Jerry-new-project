"""Build private input-layout-matched but wording-heldout test candidates."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from intentlab.matched_test_data import build

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('base','plan','private-seed','out'):
        parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args()
    result=build(args.base,args.plan,args.private_seed,args.out)
    print(json.dumps({k:result[k] for k in ['matched_test_source_tasks','matched_test_views','development_exports_byte_identical','strict_iid_claim','formal_protocol_frozen']},indent=2))
