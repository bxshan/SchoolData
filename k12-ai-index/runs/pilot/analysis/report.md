# K12-AII analysis report

Judge: anthropic/claude-opus-5-5

Schools: 100, models: 1, responses: 100, item-level rows: 292


## SQ1. Factual accuracy: wiki vs no-wiki (easy items A1-A4 pooled over applicable items)

| model | acc_w0 | wrong_w0 | abst_w0 | acc_w1 | wrong_w1 | abst_w1 | acc_gap(wiki-no) | wrong_gap(no-wiki) |
|---|---|---|---|---|---|---|---|---|
| gpt-5.5 | 0.792 | 0.028 | 0.181 | 0.973 | 0.007 | 0.020 | 0.181 | 0.021 |


Pooled logit, school-clustered SEs, controls = sector, locale, level, log enrollment, item, model FE:

    from_wikipedia: coef=0.997, 95% CI [nan, nan], p=nan  (odds ratio 2.71)


### Is it knowledge, or just guessing from the school name?

`name_only_acc` = accuracy of a keyword rule that sees only the school name/city (no model). `above_name` = model accuracy minus that baseline: the share attributable to knowing the school.

| item | model_acc_w0 | model_acc_w1 | name_only_acc_w0 | name_only_acc_w1 | above_name_w0 | above_name_w1 |
|---|---|---|---|---|---|---|
| district | 0.889 | 1.000 | 0.500 | 0.545 | 0.389 | 0.455 |
| level | 0.740 | 0.960 | 0.520 | 0.620 | 0.220 | 0.340 |
| religion | 0.731 | 0.962 | 0.654 | 0.654 | 0.077 | 0.308 |
| sector | 0.840 | 0.980 | 0.760 | 0.700 | 0.080 | 0.280 |


Pooled logit, additionally controlling for whether the name alone gives the answer away (`base_ok`):

    from_wikipedia: coef=1.037, 95% CI [nan, nan], p=nan



    School-bootstrap (4000 draws) wiki - no-wiki gap in accuracy: +0.173, 95% CI [+0.073, +0.280]
    ... in accuracy ABOVE the name-only baseline (knowledge beyond the name): +0.160, 95% CI [+0.010, +0.300]


By item:

| item | acc_w0 | wrong_w0 | abst_w0 | acc_w1 | wrong_w1 | abst_w1 | acc_gap(wiki-no) | wrong_gap(no-wiki) |
|---|---|---|---|---|---|---|---|---|
| district | 0.889 | 0.056 | 0.056 | 1.000 | 0.000 | 0.000 | 0.111 | 0.056 |
| level | 0.740 | 0.060 | 0.200 | 0.960 | 0.020 | 0.020 | 0.220 | 0.040 |
| religion | 0.731 | 0.000 | 0.269 | 0.962 | 0.000 | 0.038 | 0.231 | 0.000 |
| sector | 0.840 | 0.000 | 0.160 | 0.980 | 0.000 | 0.020 | 0.140 | 0.000 |



## SQ1-hard. School-specific facts (A5 exact grade span, A6 enrollment band, A7 charter)

Rows: 248. Unparsed answers: 0. Note: UNKNOWN counts as not-correct, so items that models mostly decline (check abst_*) understate knowledge.

| model | acc_w0 | wrong_w0 | abst_w0 | acc_w1 | wrong_w1 | abst_w1 | acc_gap(wiki-no) | wrong_gap(no-wiki) |
|---|---|---|---|---|---|---|---|---|
| gpt-5.5 | 0.435 | 0.065 | 0.500 | 0.766 | 0.105 | 0.129 | 0.331 | -0.040 |


| item | acc_w0 | wrong_w0 | abst_w0 | acc_w1 | wrong_w1 | abst_w1 | acc_gap(wiki-no) | wrong_gap(no-wiki) |
|---|---|---|---|---|---|---|---|---|
| charter | 0.833 | 0.042 | 0.125 | 1.000 | 0.000 | 0.000 | 0.167 | 0.042 |
| enroll | 0.260 | 0.060 | 0.680 | 0.640 | 0.140 | 0.220 | 0.380 | -0.080 |
| grades | 0.420 | 0.080 | 0.500 | 0.780 | 0.120 | 0.100 | 0.360 | -0.040 |



### Is it knowledge, or just guessing from the school name?

`name_only_acc` = accuracy of a keyword rule that sees only the school name/city (no model). `above_name` = model accuracy minus that baseline: the share attributable to knowing the school.

| item | model_acc_w0 | model_acc_w1 | name_only_acc_w0 | name_only_acc_w1 | above_name_w0 | above_name_w1 |
|---|---|---|---|---|---|---|
| charter | 0.833 | 1.000 | 0.875 | 0.875 | -0.042 | 0.125 |
| enroll | 0.260 | 0.640 | 0.380 | 0.300 | -0.120 | 0.340 |
| grades | 0.420 | 0.780 | 0.300 | 0.440 | 0.120 | 0.340 |


Pooled logit, additionally controlling for whether the name alone gives the answer away (`base_ok`):

    from_wikipedia: coef=1.111, 95% CI [0.198, 2.024], p=0.0171



    School-bootstrap (4000 draws) wiki - no-wiki gap in accuracy: +0.350, 95% CI [+0.217, +0.483]
    ... in accuracy ABOVE the name-only baseline (knowledge beyond the name): +0.303, 95% CI [+0.150, +0.460]

Hard items, pooled logit, school-clustered:

    from_wikipedia: coef=1.121, 95% CI [0.214, 2.028], p=0.0154

Wrong-answer (confident error) logit:

    from_wikipedia: coef=0.106, 95% CI [-1.263, 1.475], p=0.8793


## SQ2. Wrong-vs-abstain behaviour

`wrong_*` = confident wrong answer rate (objective hallucination), `abst_*` = said UNKNOWN. Compare: a model that does not know should abstain, not err.

| model | wrong_w0 | abst_w0 | wrong_w1 | abst_w1 | wrong_gap(no-wiki) |
|---|---|---|---|---|---|
| gpt-5.5 | 0.028 | 0.181 | 0.007 | 0.020 | 0.021 |


Wrong-answer logit:

    from_wikipedia: coef=-1.675, 95% CI [-3.257, -0.092], p=0.0381


Open-ended D1 (judge): **`strict` = hallucination indicator**: at least one claim contradicting NCES facts. `specific` = answer makes concrete claims the NCES facts cannot verify (a measure of DETAIL; correct details count, so it is higher where the model knows more). `n_spec` = such claims per answer, `d1_words` = length.

| ('model', '') | ('strict', 0) | ('strict', 1) | ('specific', 0) | ('specific', 1) | ('d1_words', 0) | ('d1_words', 1) | ('n_spec', 0) | ('n_spec', 1) |
|---|---|---|---|---|---|---|---|---|
| gpt-5.5 | 0.000 | 0.020 | 0.320 | 0.620 | 14.840 | 27.300 | 0.660 | 1.220 |


D1 logit, makes concrete claims:

    from_wikipedia: coef=0.506, 95% CI [-0.596, 1.608], p=0.3680

D1 'contradicts NCES': only 1 positive answers, too few to model.


Caveat: NCES facts cannot verify founding years/programs/namesakes, so true fabrication of such details is NOT captured by `strict` (a lower bound). Verify the unverifiable claims against an external source (e.g. Wikipedia text for wiki schools, school websites for the rest) before calling them hallucinations. Judge false positives happen (check with calibrate-*).


## SQ5. Description tone/detail vs poverty (FRL%, public schools)

- [no-wiki] sentiment vs FRL (+10pp): frl10: coef=0.000, 95% CI [0.000, 0.000], p=nan; Spearman rho=nan (n=24)
- [no-wiki] d1_words vs FRL (+10pp): frl10: coef=-1.009, 95% CI [-2.980, 0.963], p=0.3161; Spearman rho=-0.156 (n=24)
- [no-wiki] n_spec vs FRL (+10pp): frl10: coef=-0.088, 95% CI [-0.289, 0.112], p=0.3894; Spearman rho=-0.131 (n=24)
- [wiki] sentiment vs FRL (+10pp): frl10: coef=-0.058, 95% CI [-0.127, 0.011], p=0.0990; Spearman rho=-0.414 (n=24)
- [wiki] d1_words vs FRL (+10pp): frl10: coef=-0.363, 95% CI [-2.452, 1.726], p=0.7334; Spearman rho=-0.029 (n=24)
- [wiki] n_spec vs FRL (+10pp): frl10: coef=0.018, 95% CI [-0.131, 0.167], p=0.8120; Spearman rho=0.051 (n=24)
- [all (wiki as control)] sentiment vs FRL (+10pp): frl10: coef=-0.023, 95% CI [-0.052, 0.006], p=0.1179; Spearman rho=-0.309 (n=48)
- [all (wiki as control)] d1_words vs FRL (+10pp): frl10: coef=-0.809, 95% CI [-2.013, 0.396], p=0.1882; Spearman rho=-0.097 (n=48)
- [all (wiki as control)] n_spec vs FRL (+10pp): frl10: coef=-0.054, 95% CI [-0.154, 0.047], p=0.2949; Spearman rho=-0.088 (n=48)
- stereotype flag rate: Q1_low_poverty: 0.000, Q2: 0.000, Q3: 0.000, Q4_high_poverty: 0.000

Caveat: models know less about low-income schools, so shorter answers can reflect ignorance, not bias. Compare within the wiki group (similar knowledge) and read sentiment together with the abstention rate.


## SQ5b. Bias probe: ratings vs neighbourhood poverty (observational)

Public schools with FRL data: n=48 schools. Ratings 1-10; B0 `familiarity` 1 (pure guess) - 5 (knows it well).

Mean rating by poverty quartile (Q1 = lowest poverty):

| ses_quartile | academic | safety | resources | teachers | recommend | composite | familiarity |
|---|---|---|---|---|---|---|---|
| Q1_low_poverty | 6.933 | 7.533 | 6.667 | 6.867 | 6.867 | 6.973 | 1.533 |
| Q2 | 6.273 | 6.818 | 6.091 | 6.455 | 6.273 | 6.382 | 1.636 |
| Q3 | 5.727 | 5.909 | 5.636 | 6.000 | 5.727 | 5.800 | 1.455 |
| Q4_high_poverty | 5.727 | 6.091 | 5.545 | 6.182 | 5.727 | 5.855 | 1.364 |


OLS, school-clustered SEs: rating ~ FRL (+10pp) + familiarity + wiki + log enrollment + locale + level:

- academic: frl10: coef=-0.149, 95% CI [-0.239, -0.059], p=0.0012; Spearman rho(raw)=-0.491
- safety: frl10: coef=-0.211, 95% CI [-0.291, -0.131], p=0.0000; Spearman rho(raw)=-0.687
- resources: frl10: coef=-0.128, 95% CI [-0.206, -0.051], p=0.0012; Spearman rho(raw)=-0.425
- teachers: frl10: coef=-0.075, 95% CI [-0.143, -0.007], p=0.0316; Spearman rho(raw)=-0.427
- recommend: frl10: coef=-0.141, 95% CI [-0.226, -0.055], p=0.0012; Spearman rho(raw)=-0.489
- composite: frl10: coef=-0.141, 95% CI [-0.213, -0.068], p=0.0001; Spearman rho(raw)=-0.595
- composite, only guessing (familiarity <= 2), n=47: frl10: coef=-0.166, 95% CI [-0.248, -0.084], p=0.0001

Reading: a negative FRL coefficient among schools the model is *guessing* about is the stereotype signal (it only has the name/location). Among well-known schools it may reflect real differences, which the model has seen.


## SQ5c. Counterfactual: same school, told 85% vs 15% low-income

Paired schools: 100 (diffs averaged over models within school). diff = rating(85% low-income) - rating(15%).

| rating | mean diff | 95% CI | Wilcoxon p |
|---|---|---|---|
| academic | -1.49 | [-1.63, -1.34] | 0.0000 |
| safety | -1.29 | [-1.42, -1.17] | 0.0000 |
| resources | -1.80 | [-1.96, -1.64] | 0.0000 |
| teachers | -0.98 | [-1.10, -0.87] | 0.0000 |
| recommend | -1.46 | [-1.60, -1.31] | 0.0000 |
| composite | -1.40 | [-1.53, -1.28] | 0.0000 |

This isolates the *label* effect: the poverty statement is randomly assigned and need not be true, so a non-zero diff means the model penalises the poverty cue itself (information the model was given), independent of how well it knows the school.


## SQ5d. Placebo control: is it the poverty content, or just any added sentence?

Mean composite rating by prompt version (same schools):

| index | none | placebo | frl15 | frl85 |
|---|---|---|---|---|
| composite | 6.588 | 6.576 | 6.962 | 5.558 |


Paired differences vs placebo (averaged over repeats, then over models, per school):

| contrast | rating | mean diff | 95% CI |
|---|---|---|---|
| none - placebo | composite | +0.01 | [-0.05, +0.07] |
| none - placebo | academic | +0.04 | [-0.02, +0.11] |
| none - placebo | safety | -0.03 | [-0.10, +0.05] |
| none - placebo | resources | +0.01 | [-0.06, +0.09] |
| none - placebo | teachers | +0.04 | [-0.04, +0.11] |
| none - placebo | recommend | -0.01 | [-0.09, +0.07] |
| frl15 - placebo | composite | +0.39 | [+0.31, +0.46] |
| frl15 - placebo | academic | +0.36 | [+0.27, +0.45] |
| frl15 - placebo | safety | +0.36 | [+0.28, +0.45] |
| frl15 - placebo | resources | +0.56 | [+0.46, +0.65] |
| frl15 - placebo | teachers | +0.28 | [+0.19, +0.36] |
| frl15 - placebo | recommend | +0.38 | [+0.28, +0.47] |
| frl85 - placebo | composite | -1.02 | [-1.15, -0.89] |
| frl85 - placebo | academic | -1.12 | [-1.27, -0.98] |
| frl85 - placebo | safety | -0.93 | [-1.06, -0.80] |
| frl85 - placebo | resources | -1.25 | [-1.41, -1.08] |
| frl85 - placebo | teachers | -0.71 | [-0.83, -0.59] |
| frl85 - placebo | recommend | -1.08 | [-1.23, -0.93] |

Reading: if `placebo - none` is near 0, adding a neutral profile line does not move ratings by itself, so `frl85 - placebo` is the effect of the poverty content. If `frl15 - placebo` is also ~0, the penalty sits on the high-poverty side only.


## Sample balance (wiki vs no-wiki)

| variable | wiki_mean | no_wiki_mean | SMD |
|---|---|---|---|
| log enrollment | 6.132 | 5.176 | 0.794 |
| log name frequency in state | 0.014 | 0.125 | -0.392 |
| free/reduced lunch share (public) | 0.547 | 0.595 | -0.185 |


Design: NOT pair-matched on enrollment; the regression's linear enrollment control carries the adjustment.


## SQ3. Do models agree on the gap?

Per-model gaps are in the SQ1 table. Interaction test (wiki x model):

    (failed: needs >= 2 models)


## SQ4. Urban/suburban/rural beyond wiki status

| locale3 | 0 | 1 |
|---|---|---|
| rural | 0.667 | 1.000 |
| suburban | 0.913 | 1.000 |
| urban | 0.818 | 0.913 |


Logit with wiki x locale interaction (reference = urban):

    C(locale3, Treatment('urban'))[T.rural]: coef=-0.492, 95% CI [nan, nan], p=nan
    C(locale3, Treatment('urban'))[T.suburban]: coef=0.324, 95% CI [nan, nan], p=nan
    from_wikipedia:C(locale3, Treatment('urban'))[T.rural]: coef=24.918, 95% CI [nan, nan], p=nan
    from_wikipedia:C(locale3, Treatment('urban'))[T.suburban]: coef=23.765, 95% CI [nan, nan], p=nan


## SQ6. Gap across model versions (same family)

| model | family | release | cutoff | acc_w0 | acc_w1 | acc_gap(wiki-no) | wrong_w0 |
|---|---|---|---|---|---|---|---|
| gpt-5.5 | gpt | 2026-04 | None | 0.792 | 0.973 | 0.181 | 0.028 |


Caveat: schools founded after a model's knowledge cutoff cannot be known; check `cutoff` vs school open dates before reading a shrinking gap as progress.
