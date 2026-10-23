# M3i: assumption-only paired-source design sensitivity

No dataset, gold or model outputs are read. `python scripts/power_sensitivity.py --out NEW_PRIVATE_OR_PUBLIC_DIRECTORY` regenerates the 80-row planning grid and conservative sufficient bound. Existing output directories are refused.

Normal approximations depend on assumed task-difference standard deviations, not measured ones. Hoeffding bounds require independent bounded source-task differences and are sufficient, not necessary. Neither calculation is calibrated power of the final analysis, evidence that source independence holds, or probability of an experimental advantage. Three fixed training seeds do not multiply independent source count.

Local numerical checks: three targeted tests passed, including a hand-calculated normal-power case and bound scaling. AutoDL replay has 18 Gaussian-power entries differing in the final floating-point digits (maximum 2.22e-16); all other values match exactly. Both outputs and a tolerance check are retained. This work does not complete or approve the formal power evidence gate. See [interpretation](../../../docs/design-sensitivity.md).
