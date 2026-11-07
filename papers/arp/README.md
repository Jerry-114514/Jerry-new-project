# Argmax Retention Profiling for Multimodal Model Downscaling

**Anonymous working draft**

## Abstract

Audits of multimodal model downscaling often rank capability losses measured by different probes. Because those probes have different baselines and scoring conventions, the identity of the largest loss can depend on the measurement scale. We introduce **Argmax Retention Profiling (ARP)**, which enumerates a specified family of scales, identifies redundant specifications, and reports how often each capability is ranked first. A pairwise analysis shows that reference-floor correction alone can reverse a raw ordering. Results reported for three released model families suggest different degrees of scale sensitivity, although the ruler-level tallies need reconciliation before exact retention estimates can be treated as final. A separate grounding audit shows that reinterpreting the same predicted boxes can reverse the ordering of training arms. An exploratory factorial experiment on a different model reports a positive effect of target coordinate representation on grounding. Across the five-seed LoRA arms, intervals for aggregate gains include zero. These results motivate reporting both the scoring contract and the sensitivity of capability rankings before using them to allocate training.

## 1. Introduction

Suppose a smaller model loses ten accuracy points on a balanced binary hallucination probe and ten points on an image grounding probe. The two losses are equal on the raw accuracy scale. They occupy different fractions of the score ranges above the probes' reference baselines. A training policy that targets the largest loss can therefore pick different capabilities depending on which scale it uses.

Endo and Yeung-Levy study how downscaling affects perception and reasoning in multimodal models [1]. AuditDM discovers capability gaps by generating examples that expose disagreement across models [2]. ReAD allocates supervision across capabilities under a fixed training budget [3]. ARP addresses a complementary question: how sensitive is a capability ranking to the rules used to construct it? The distinction matters whenever a ranking becomes an input to training or deployment decisions. The broader concern that aggregate evaluation scores depend on their aggregation rule has also been studied in language-model evaluation [4].

We make three contributions. First, we specify a finite sensitivity analysis for the identity of the most degraded capability. Second, we derive the reversal condition for reference-floor correction and the cancellation that occurs under a specific headroom denominator. Third, we use a grounding case study to distinguish changes in scoring an existing output from changes induced by a new prompt or training target.

## 2. Argmax retention profiling

### 2.1 Evaluation ledger and scales

For each checkpoint, retain item and source-image identifiers, probe and subgroup identifiers, correctness, and parse status. A binary correctness ledger alone cannot support parse exclusion or image-cluster resampling. The supplied experiment describes seven checkpoints across Qwen2.5-VL (3B/7B), InternVL3 (1B/2B/8B), and LLaVA-OneVision (0.5B/7B), with greedy FP16 inference. The four probes are POPE object hallucination [5], RefCOCO-family grounding at IoU ≥ 0.5, agreement across five scripted paraphrases of MMBench questions, and MMStar multiple-choice performance [6]. The reported design uses 9,000 POPE items, 2,400 grounding items, 800 paraphrase groups, and 1,500 MMStar items. The paraphrase probe measures agreement; its scoring rule must state whether agreement on an incorrect answer receives credit.

The nominal grid contains 120 settings: absolute or relative drop, reference-floor correction on or off, three headroom settings, five ordered weighted averaging settings, and parse failures counted as incorrect or excluded. The reported reference scores are 0.500 for always answering “no” on POPE, 0.028 for a centered reference box on grounding, 0.351 for the consistency reference, and 0.261 for the MMStar reference. These are scores under particular reference policies. For replication, the consistency baseline, random-option sampling rule, OWA subgroup weights, and eligibility rules for parse exclusions need an executable specification. Each exclusion rule should report its denominator and the number of discarded items.

### 2.2 When floor correction changes the ranking

Let $x_{L,a}$ and $x_{S,a}$ be the larger and smaller checkpoints' scores on axis $a$, and let $c_a<1$ be its reference score. Define the raw drop $d_a=x_{L,a}-x_{S,a}$. Applying $x\mapsto(x-c_a)/(1-c_a)$ gives the corrected absolute drop $d_a/(1-c_a)$. For positive drops and $c_a>c_b$, correction reverses a raw ordering with $d_a<d_b$ exactly when

$$
\frac{1-c_a}{1-c_b}<\frac{d_a}{d_b}<1.
$$

For POPE and grounding, using the reported reference scores gives a lower endpoint of **0.5144** and an interval width of **0.4856** on the ratio axis. The width gives the measure of the interval under a uniform ratio on $[0,1]$. Estimating how often a reversal occurs in practice requires the observed ratio distribution.

If the numerator and headroom denominator undergo the same affine transform, their common factor cancels. For headroom $u_a-x_{S,a}$ with $u_a>x_{S,a}$, the resulting statistic is $d_a/(u_a-x_{S,a})$. In a two-member comparison with $u_a=x_{L,a}$, every eligible positive-drop axis receives 1. Such a tie follows from the formula. It provides no evidence that the underlying raw losses are equal, and it does not constrain winners under the other scales. Relative drop uses $x_{L,a}$ as the primary raw denominator and $x_{L,a}-c_a$ after correction. Zero denominators, nonpositive headroom, and exclusions for scores at or below a reference floor should be recorded separately.

### 2.3 Retention, ties, and sampling uncertainty

For each eligible specification $r$, report the complete winner set $W_r$. For the tie-inclusive profile, assign each member of $W_r$ weight $1/|W_r|$ and average across the included specifications. Its dispersion statistic is $F_{\mathrm{all}}=1-\max_a\pi(a)$. For strict reversals, apply the same calculation only to specifications with a unique winner and report their number. A profile with no unique-winner specification has an undefined strict reversal rate. Report the intersection of the winner sets separately from the set of axes that win uniquely everywhere. List partial ties, full ties, and specifications with no eligible axes explicitly.

Algebraic equivalences can be collapsed before estimation. Equal vectors in one observed ledger can separate after resampling, so report the nominal-grid and equivalence-class profiles separately and state whether classes are fixed or recomputed inside each resample. The manuscript's reported quotient sizes are 9, 54, and 10 for the three families. Replication needs the exact ladder-pair aggregation rule, the grid-to-class mapping, and a complete winner ledger.

Scale sensitivity and sampling sensitivity answer different questions. The former varies the specification on a common sample. The latter resamples observations under a fixed specification. To estimate the latter, preserve pairing across checkpoints and use source-image clusters when prompts share images. The supplied ARP analysis reports 1,000 stratified item bootstrap replicates. Its results should be checked with source-cluster resampling before using interval separation as evidence against sampling variability.

## 3. Evidence from the reported experiments

### 3.1 Model-family audit

The supplied summary reports eight unique-winner specifications for Qwen2.5-VL, all selecting MMStar, and reports strict reversal rates of 0.500 and 0.250 for InternVL3 and LLaVA-OneVision. The latter rates remain provisional until the individual class assignments and winners are reconciled. Two of InternVL3's 54 classes are unaccounted for in the unique-winner and full-tie subtotals. Qwen's reported maximum retention of 0.908 implies a tie-inclusive rate of 0.092 under the stated formula, whereas its source table gives 0.083. Pending reconciliation, we report these values as discrepancies and defer the stable-set counts and attribution estimates. InternVL3's near-zero grounding scores further limit interpretation on that axis.

### 3.2 Grounding scoring contract

Table 1 preserves the supplied Qwen2.5-VL-7B grounding scores. The first three columns reinterpret the same stored responses. The final column uses new outputs from a prompt specifying the processor grid.

| Arm | Original pixels, rescored (%) | Normalized 0–1000, rescored (%) | Processor pixels, rescored (%) | Processor pixels, regenerated (%) |
|---|---:|---:|---:|---:|
| No-op (N) | 67.79 | 0.08 | 85.50 | 84.71 |
| MMStar targeted (A1) | 66.13 | 0.03 | 83.74 | 85.59 |
| Consistency targeted (A2) | 67.46 | 0.02 | 85.38 | 84.97 |
| Mixed (U) | 77.66 | 0.06 | 73.56 | 82.27 |

With the same stored outputs, A1 trails U by 11.53 percentage points under original-image pixels and leads by 10.18 points under processor pixels. This establishes a ranking reversal under alternative scoring contracts for the stored outputs. Under the processor-grid prompt, the regenerated A1–U difference is 3.32 points. The latter contrast includes a change to the prompt and the outputs. The reported LoRA gain table's grounding deltas align with the regenerated column, up to rounding. The scoring-contract comparison does not establish which arm learned better localization independently of its output format.

### 3.3 Targeted training and coordinate intervention

The supplied study compares three Qwen2.5-VL-7B LoRA arms with a no-op baseline. The trained arms use 1,000 steps, rank 16, alpha 32, learning rate $10^{-4}$, and five seeds. The aggregate is the sum of axis deltas divided by their respective $1-c_a$.

| Arm vs. no-op | Floor-corrected aggregate gain | Reported 95% interval |
|---|---:|---:|
| A1, MMStar targeted | +1.76 | [−2.31, +6.12] |
| A2, consistency targeted | +0.00 | [−4.23, +4.18] |
| U, mixed | −2.34 | [−9.38, +3.49] |

These are sums of rescaled percentage-point deltas, not a single benchmark's accuracy change. Each interval includes zero. The A1 point estimate on its target axis is −1.09 points, so the experiment provides no clear improvement from targeting the highest-ranked axis. The source describes image-cluster resampling. Seed-level generalization requires clarification of whether the resampling also incorporates variation across independently trained runs.

In a separate 2×2 experiment on Qwen3.5-9B with cached supervision from a 122B teacher, the factors are pixel versus normalized coordinate targets and ground-truth-only versus combined ground-truth and teacher supervision. Each cell uses two seeds and 1,000 updates. The supplied grounding coordinate main effect is +22.75 points on development (adjusted interval [10.0, 36.1]) and +21.88 points on 960 held-out rows ([5.3, 40.9]). The intervals are reported as Bonferroni-adjusted across 24 comparisons. Teacher and interaction intervals include zero and still allow practically meaningful effects. The finding supports a coordinate-representation effect in this setup. Its uncertainty across training runs remains provisional pending documentation of the seed and image hierarchy. The Qwen3.5-9B experiment does not establish the correct parser for the separate Qwen2.5-VL-7B evaluation.

## 4. Discussion and limitations

ARP reports robustness conditional on the scales, weights, axes, and scoring contracts chosen by the analyst. A high retention value describes agreement within that family of choices. Changing eligibility, the representation of equivalent scales, or the weights across them can change the profile. With three model families and heterogeneous probes, the current evidence does not estimate how often reversals occur across multimodal systems generally.

The practical implication is to report a capability ranking alongside the scoring contract and its sensitivity to defensible changes. The grounding example motivates checking coordinate units and image transforms before aggregating scores. The LoRA experiment leaves open whether ARP-guided targeting improves downstream utility under a fixed budget.

## 5. Conclusion

An axis ranking combines measured changes in performance with a choice of scale. Reference-floor correction has a calculable reversal region, and particular headroom denominators force ties. ARP makes these choices inspectable by exposing the winner sets and their sensitivity. The grounding case study shows that a scoring contract can change a ranking even before normalization. The current experiments motivate auditing the ranking used to allocate training. Whether that audit improves allocation outcomes remains an empirical question.

## Data and reproducibility

This working draft revises the supplied six-page ARP manuscript. The item ledgers, training logs, seed-level results, and analysis code were unavailable for this revision. Numerical corrections are derived from the displayed formulas and tables. The experiment summaries above are attributed to the supplied manuscript. Before submission, reconcile the ruler-level counts, reproduce the bootstrap intervals with documented resampling units, and supply the model revisions, evaluation split identifiers, coordinate transforms, and analysis artifacts. This manuscript is separate from the IntentLab experiment reports in this repository.

## References

1. Mark Endo and Serena Yeung-Levy. *Downscaling Intelligence: Exploring Perception and Reasoning Bottlenecks in Small Multimodal Models*. [arXiv:2511.17487](https://arxiv.org/abs/2511.17487).
2. Qihao Liu, Chengzhi Mao, Yaojie Liu, Alan Yuille, and Wen-Sheng Chu. *Differences That Matter: Auditing Models for Capability Gap Discovery and Rectification*. [arXiv:2512.16921](https://arxiv.org/abs/2512.16921).
3. Xueqi Cheng, Xugui Zhou, Tyler Derr, and Yushun Dong. *ReAD: Reinforcement-Guided Capability Distillation for Large Language Models*. [arXiv:2605.11290](https://arxiv.org/abs/2605.11290).
4. Sankalp Gilda and Shlok Gilda. *Position: Evaluation Scores Are Perishable Knowledge Claims*. [arXiv:2607.26191](https://arxiv.org/abs/2607.26191).
5. Yifan Li et al. *Evaluating Object Hallucination in Large Vision-Language Models*. [arXiv:2305.10355](https://arxiv.org/abs/2305.10355).
6. Lin Chen et al. *Are We on the Right Way for Evaluating Large Vision-Language Models?* [arXiv:2403.20330](https://arxiv.org/abs/2403.20330).
