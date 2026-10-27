"""Acknowledged use of the frozen SFT implementation with evaluation timing."""
import argparse
from pathlib import Path
import subprocess
import sys


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path,required=True);p.add_argument('--core-commit',required=True)
    p.add_argument('--ack',type=Path,required=True);p.add_argument('--timing-output',type=Path,required=True)
    p.add_argument('--owned-module',choices=('intentlab.neural',),required=True)
    p.add_argument('training_args',nargs=argparse.REMAINDER);a=p.parse_args()
    if not a.training_args or a.training_args[0]!='--':p.error('Separate neural arguments with --')
    if subprocess.check_output(['git','-C',str(a.source),'rev-parse','HEAD'],text=True).strip()!=a.core_commit \
            or subprocess.check_output(['git','-C',str(a.source),'status','--porcelain']):
        raise ValueError('Frozen scientific source changed')
    sys.path.insert(0,str(a.source))
    from intentlab.matrix_worker import wait_for_ack
    wait_for_ack(a.ack)
    from intentlab import neural
    from timed_neural_invocation import instrument_evaluation
    torch,_=neural.dependencies()
    neural.evaluate_loss=instrument_evaluation(neural.evaluate_loss,torch,a.timing_output,a.owned_module)
    neural.main(a.training_args[1:])
