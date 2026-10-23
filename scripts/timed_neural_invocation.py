"""Time existing loss evaluations without changing their inputs or results."""
import argparse
import json
from pathlib import Path
import sys
import time


def instrument_evaluation(evaluate, torch, output, invocation):
    def timed(*args,**kwargs):
        started=time.perf_counter()
        record={'invocation':invocation,'status':'failed'}
        try:
            if torch.cuda.is_available():
                torch.cuda.synchronize()
            started=time.perf_counter()
            result=evaluate(*args,**kwargs)
            if torch.cuda.is_available():
                torch.cuda.synchronize()
            record.update(status='completed',target_tokens=result['target_tokens'],loss=result['loss'])
            return result
        except BaseException as exc:
            record['error_type']=type(exc).__name__
            raise
        finally:
            record['wall_seconds']=time.perf_counter()-started
            with Path(output).open('a',encoding='utf-8') as stream:
                stream.write(json.dumps(record,sort_keys=True)+'\n')
    return timed


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--timing-output',type=Path,required=True)
    parser.add_argument('--invocation',required=True)
    parser.add_argument('neural_args',nargs=argparse.REMAINDER)
    args=parser.parse_args()
    if not args.neural_args or args.neural_args[0]!='--':
        parser.error('Separate original neural CLI arguments with --')
    sys.path.insert(0,str(args.source))
    from intentlab import neural
    torch,_=neural.dependencies()
    neural.evaluate_loss=instrument_evaluation(neural.evaluate_loss,torch,args.timing_output,args.invocation)
    neural.main(args.neural_args[1:])
