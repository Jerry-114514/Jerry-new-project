"""Compare development model interfaces without loading or inventing gold."""
from collections import Counter
import math
from pathlib import Path
import sys

if (Path(__file__).resolve().parents[3]/'intentlab').is_dir():
    sys.path.insert(0,str(Path(__file__).resolve().parents[3]))
from intentlab.budget import TokenLedger
from intentlab.core import canonical,digest
from intentlab.formal_data import validate_cases,validate_findings
from intentlab.formal_eval import parse_prediction


def without_event_times(snapshot):
    return {**snapshot,'events':[{k:v for k,v in row.items() if k!='elapsed_seconds'} for row in snapshot['events']]}


def analyze(cases,manifest,preflight,records):
    validate_cases(cases)
    if manifest['status']!='completed' or manifest['cases_hash']!=digest(cases) or preflight['cases_hash']!=digest(cases):
        raise ValueError('Complete matching development comparison required')
    if any(c['split'] not in {'train','validation'} for c in cases):
        raise ValueError('No held-out material in development comparison')
    if manifest['gold_loaded'] is not False or manifest['human_accuracy'] is not None:
        raise ValueError('This analysis cannot claim truth or accuracy')
    n=len(cases)
    if manifest['views']!=n or manifest['planned_calls']!=2*n or len(records)!=2*n:
        raise ValueError('All planned calls including failures must be retained')
    conditions=('full','compact')
    expected={(c['case_id'],condition) for c in cases for condition in conditions}
    tokens={(r['case_id'],r['condition']):r for r in preflight['rows']}
    if len(tokens)!=len(preflight['rows']) or set(tokens)!=expected:
        raise ValueError('Missing, duplicate or foreign preflight entries')
    order=[]
    for i,case in enumerate(cases):
        order.extend((i,case['case_id'],condition) for condition in (conditions if i%2==0 else conditions[::-1]))
    initial={'views':n,'requested_items':sum(len(c['public']['requirements']) for c in cases)}
    for key in ('generated_views','generation_errors','generation_errors_before_reservation','generation_seconds','preflight_prompt_tokens',
                'charged_model_tokens','known_completion_tokens','failed_generation_reservations',
                'predicted_satisfied_items','predicted_violated_items','predicted_unknown_items'):
        initial[key]=0
    for mode in ('strict','normalized'):
        for key in ('invalid_views','parsed_views','visible_reference_constraint_valid_views','visible_reference_constraint_invalid_views'):
            initial[mode+'_'+key]=0
    groups={condition:Counter(initial) for condition in conditions}
    parsed={condition:{} for condition in conditions}
    for i,(row,(index,cid,condition)) in enumerate(zip(records,order)):
        if (row['call_index'],row['case_index'],row['case_id'],row['condition'])!=(i,index,cid,condition):
            raise ValueError('Missing, duplicate, reordered or foreign paired call')
        key=(cid,condition);public=cases[index]['public'];counts=groups[condition]
        if row['prompt_hash']!=tokens[key]['prompt_hash']:
            raise ValueError('Executed prompt hash differs from preflight')
        prompt_tokens=tokens[key]['prompt_tokens']
        ledger=TokenLedger(manifest['token_budget_per_call'])
        assert prompt_tokens+manifest['max_new_tokens']<=min(manifest['context_limit'],manifest['token_budget_per_call'])
        if row['status']=='generated':
            ticket,allowance=ledger.begin('analyzer',prompt_tokens,manifest['max_new_tokens'],manifest['context_limit'],row['prompt_hash'])
            assert allowance==manifest['max_new_tokens']
            assert row['usage']['prompt_tokens']==prompt_tokens
            ledger.finish(ticket,row['usage']['completion_tokens'])
            counts['generated_views']+=1
        elif row['status']=='error':
            assert row['text']==''
            assert isinstance(row['error_type'],str) and row['error_type']
            if row['budget']['events']:
                ticket,_=ledger.begin('analyzer',prompt_tokens,manifest['max_new_tokens'],manifest['context_limit'],row['prompt_hash'])
                ledger.fail(ticket,row['error_type'])
            else:
                counts['generation_errors_before_reservation']+=1
            counts['generation_errors']+=1
        else:
            raise ValueError('Unknown generation status')
        if canonical(without_event_times(ledger.snapshot()))!=canonical(without_event_times(row['budget'])):
            raise ValueError('Token accounting does not replay')
        assert math.isfinite(row['generation_seconds']) and row['generation_seconds']>=0
        counts['generation_seconds']+=row['generation_seconds']
        counts['preflight_prompt_tokens']+=prompt_tokens
        counts['charged_model_tokens']+=row['budget']['charged_tokens']
        counts['known_completion_tokens']+=row['budget']['known_completion_tokens']
        counts['failed_generation_reservations']+=row['budget']['failed_reservations']
        for mode,normalize in (('strict',False),('normalized',True)):
            try:
                findings=parse_prediction(row['text'],public['requirements'],normalize)
            except (ValueError,KeyError,TypeError):
                counts[mode+'_invalid_views']+=1
                if mode=='normalized':parsed[condition][cid]={}
                continue
            counts[mode+'_parsed_views']+=1
            try:
                validate_findings(list(findings.values()),public)
                counts[mode+'_visible_reference_constraint_valid_views']+=1
            except (ValueError,KeyError,TypeError):
                counts[mode+'_visible_reference_constraint_invalid_views']+=1
            if mode=='normalized':
                parsed[condition][cid]=findings
                for finding in findings.values():
                    counts['predicted_'+finding['status']+'_items']+=1
    paired=Counter(views=n,requested_items=sum(len(c['public']['requirements']) for c in cases),
        noncomparable_views=0,noncomparable_items=0,comparable_views=0,comparable_items=0,
        status_disagreements=0,evidence_reference_set_disagreements=0,all_states_equal_views=0)
    for case in cases:
        cid=case['case_id'];a,b=parsed['full'][cid],parsed['compact'][cid]
        if not a or not b:
            paired['noncomparable_views']+=1
            paired['noncomparable_items']+=len(case['public']['requirements'])
            continue
        paired['comparable_views']+=1
        same=True
        for requirement in case['public']['requirements']:
            rid=requirement['id'];paired['comparable_items']+=1
            if a[rid]['status']!=b[rid]['status']:
                paired['status_disagreements']+=1;same=False
            if sorted(a[rid]['evidence'])!=sorted(b[rid]['evidence']):paired['evidence_reference_set_disagreements']+=1
        paired['all_states_equal_views']+=same
    assert paired['comparable_items']+paired['noncomparable_items']==paired['requested_items']
    return {'scope':'unreviewed_development_prompt_interface_comparison',
        'conditions':{key:dict(value) for key,value in groups.items()},'paired':dict(paired),
        'human_accuracy':None,'gold_loaded':False,'formal_training_started':False,'formal_budget_approved':False,
        'warning':'Prediction disagreements are not errors against truth. Reference existence and nonempty constraints do not prove semantic evidence support. No cases, failures or noncomparable items are dropped; no fence stripping or post-hoc retries.'}
