"""Assumption-only paired-source planning; never reads data or model scores."""
import argparse
import json
import math
from pathlib import Path
from statistics import NormalDist


def planning(alpha=0.05, desired_power=0.8):
    if not 0 < alpha < 1 or not 0.5 < desired_power < 1:
        raise ValueError('Require 0 < alpha < 1 and 0.5 < desired_power < 1')
    normal = NormalDist()
    z = normal.inv_cdf(1-alpha/2)
    z_power = normal.inv_cdf(desired_power)
    grid = []
    for groups in (100, 150, 200, 300, 500):
        for sd in (0.1, 0.2, 0.3, 0.5):
            for effect in (0.025, 0.05, 0.10, 0.15):
                signal = effect*math.sqrt(groups)/sd
                power = normal.cdf(signal-z)+normal.cdf(-signal-z)
                grid.append({'source_groups':groups,'assumed_paired_task_sd':sd,
                    'absolute_error_rate_effect':effect,'normal_approx_power':power,
                    'normal_approx_sufficient_n':math.ceil(((z+z_power)*sd/effect)**2)})
    # For independent D_i in [-1,1], Hoeffding gives
    # P(|mean(D)-E mean(D)| >= t) <= 2 exp(-n t^2/2).
    # Reject beyond sqrt(2 log(2/alpha)/n). A true positive effect
    # exceeding that threshold by sqrt(2 log(1/beta)/n) has power >=1-beta.
    beta = 1-desired_power
    numerator=(math.sqrt(2*math.log(2/alpha))+math.sqrt(2*math.log(1/beta)))**2
    return {'kind':'paired_source_design_sensitivity_not_empirical_power',
        'alpha_two_sided':alpha,'desired_power':desired_power,
        'data_files_read':False,'model_outputs_read':False,'formal_budget_approved':False,
        'primary_unit':'Source-task mean status error, aggregating all its evidence views; paired model difference in [-1,1].',
        'training_seeds':'Three fixed trained models do not multiply independent task sample size. Task inference is conditional on fitted models; seed variability is separate.',
        'normal_approximation_grid':grid,
        'distribution_free_sufficient_bound':{
            'source':'https://www.tandfonline.com/doi/abs/10.1080/01621459.1963.10500830',
            'paired_difference_range':[-1,1],
            'minimum_effect_at_n':{str(n):math.sqrt(numerator/n) for n in (100,150,200,300,500)},
            'sufficient_n_by_effect':{str(effect):math.ceil(numerator/effect**2) for effect in (0.025,0.05,0.1,0.15)},
            'is_necessary_sample_size':False,
            'assumptions':'Independent bounded source-task draws conditional on fixed fitted models and generator families. Does not establish this assumption for the dataset.',
            'is_final_analysis_procedure':False},
        'limitations':['Normal grid assumes task-difference SD; none is estimated or asserted here.',
            'Gaussian planning approximation is not calibrated power for the final clustered bootstrap/sign-flip analysis.',
            'A conservative sufficient bound failing to certify power does not prove the experiment is underpowered.',
            'Finite generator families, near-neighbors, and shared templates can invalidate an independence interpretation.',
            'No empirical D-versus-B effect or seed variation exists yet. Do not infer a probability of experimental success.',
            'No sample size or test set is changed by this calculation. Power evidence gate remains incomplete.']}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    result=planning()
    args.out.mkdir(parents=True,exist_ok=False)
    (args.out/'sensitivity.json').write_text(json.dumps(result,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    print(json.dumps({'out':str(args.out),'formal_budget_approved':False,
                      'rows':len(result['normal_approximation_grid'])},indent=2))


if __name__=='__main__':
    main()
