# K12-AII analysis report

Judge: mock/mock

Schools: 100, models: 3, responses: 300, item-level rows: 891


## SQ1. Factual accuracy: wiki vs no-wiki (easy items A1-A4 pooled over applicable items)

| model | acc_w0 | wrong_w0 | abst_w0 | acc_w1 | wrong_w1 | abst_w1 | acc_gap(wiki-no) | wrong_gap(no-wiki) |
|---|---|---|---|---|---|---|---|---|
| gpt-4o | 0.329 | 0.000 | 0.671 | 0.534 | 0.000 | 0.466 | 0.205 | 0.000 |
| gpt-5 | 0.819 | 0.020 | 0.161 | 0.932 | 0.014 | 0.054 | 0.114 | 0.007 |
| gpt-5.5 | 0.926 | 0.034 | 0.040 | 0.973 | 0.007 | 0.020 | 0.047 | 0.027 |


Pooled logit, school-clustered SEs, controls = sector, locale, level, log enrollment, item, model FE:

    from_wikipedia: coef=1.030, 95% CI [0.160, 1.899], p=0.0203  (odds ratio 2.80)


### Is it knowledge, or just guessing from the school name?

`name_only_acc` = accuracy of a keyword rule that sees only the school name/city (no model). `above_name` = model accuracy minus that baseline: the share attributable to knowing the school.

| item | model_acc_w0 | model_acc_w1 | name_only_acc_w0 | name_only_acc_w1 | above_name_w0 | above_name_w1 |
|---|---|---|---|---|---|---|
| district | 0.536 | 0.697 | 0.435 | 0.545 | 0.101 | 0.152 |
| level | 0.693 | 0.807 | 0.860 | 0.620 | -0.167 | 0.187 |
| religion | 0.795 | 0.910 | 0.846 | 0.654 | -0.051 | 0.256 |
| sector | 0.707 | 0.820 | 0.900 | 0.700 | -0.193 | 0.120 |


Pooled logit, additionally controlling for whether the name alone gives the answer away (`base_ok`):

    from_wikipedia: coef=1.234, 95% CI [0.330, 2.139], p=0.0075



    School-bootstrap (4000 draws) wiki - no-wiki gap in accuracy: +0.120, 95% CI [+0.024, +0.218]
    ... in accuracy ABOVE the name-only baseline (knowledge beyond the name): +0.283, 95% CI [+0.150, +0.414]
    PAIRED (enrollment-matched pairs, n=50) wiki - no-wiki accuracy: +0.120, 95% CI [+0.047, +0.196]
    PAIRED, accuracy ABOVE the name-only baseline: +0.283, 95% CI [+0.159, +0.411]


By item:

| item | acc_w0 | wrong_w0 | abst_w0 | acc_w1 | wrong_w1 | abst_w1 | acc_gap(wiki-no) | wrong_gap(no-wiki) |
|---|---|---|---|---|---|---|---|---|
| district | 0.536 | 0.043 | 0.420 | 0.697 | 0.000 | 0.303 | 0.161 | 0.043 |
| level | 0.693 | 0.027 | 0.280 | 0.807 | 0.020 | 0.173 | 0.113 | 0.007 |
| religion | 0.795 | 0.000 | 0.205 | 0.910 | 0.000 | 0.090 | 0.115 | 0.000 |
| sector | 0.707 | 0.007 | 0.287 | 0.820 | 0.000 | 0.180 | 0.113 | 0.007 |



## SQ1-hard. School-specific facts (A5 exact grade span, A6 enrollment band, A7 charter)

Rows: 744. Unparsed answers: 0. Note: UNKNOWN counts as not-correct, so items that models mostly decline (check abst_*) understate knowledge.

| model | acc_w0 | wrong_w0 | abst_w0 | acc_w1 | wrong_w1 | abst_w1 | acc_gap(wiki-no) | wrong_gap(no-wiki) |
|---|---|---|---|---|---|---|---|---|
| gpt-4o | 0.113 | 0.032 | 0.855 | 0.298 | 0.024 | 0.677 | 0.185 | 0.008 |
| gpt-5 | 0.500 | 0.113 | 0.387 | 0.742 | 0.185 | 0.073 | 0.242 | -0.073 |
| gpt-5.5 | 0.589 | 0.040 | 0.371 | 0.758 | 0.073 | 0.169 | 0.169 | -0.032 |


| item | acc_w0 | wrong_w0 | abst_w0 | acc_w1 | wrong_w1 | abst_w1 | acc_gap(wiki-no) | wrong_gap(no-wiki) |
|---|---|---|---|---|---|---|---|---|
| charter | 0.556 | 0.000 | 0.444 | 0.667 | 0.000 | 0.333 | 0.111 | 0.000 |
| enroll | 0.280 | 0.127 | 0.593 | 0.567 | 0.133 | 0.300 | 0.287 | -0.007 |
| grades | 0.447 | 0.027 | 0.527 | 0.600 | 0.100 | 0.300 | 0.153 | -0.073 |



### Is it knowledge, or just guessing from the school name?

`name_only_acc` = accuracy of a keyword rule that sees only the school name/city (no model). `above_name` = model accuracy minus that baseline: the share attributable to knowing the school.

| item | model_acc_w0 | model_acc_w1 | name_only_acc_w0 | name_only_acc_w1 | above_name_w0 | above_name_w1 |
|---|---|---|---|---|---|---|
| charter | 0.556 | 0.667 | 0.958 | 0.875 | -0.403 | -0.208 |
| enroll | 0.280 | 0.567 | 0.520 | 0.420 | -0.240 | 0.147 |
| grades | 0.447 | 0.600 | 0.560 | 0.440 | -0.113 | 0.160 |


Pooled logit, additionally controlling for whether the name alone gives the answer away (`base_ok`):

    from_wikipedia: coef=1.461, 95% CI [0.885, 2.037], p=0.0000



    School-bootstrap (4000 draws) wiki - no-wiki gap in accuracy: +0.229, 95% CI [+0.116, +0.340]
    ... in accuracy ABOVE the name-only baseline (knowledge beyond the name): +0.316, 95% CI [+0.170, +0.461]
    PAIRED (enrollment-matched pairs, n=50) wiki - no-wiki accuracy: +0.229, 95% CI [+0.139, +0.321]
    PAIRED, accuracy ABOVE the name-only baseline: +0.316, 95% CI [+0.198, +0.437]

Hard items, pooled logit, school-clustered:

    from_wikipedia: coef=1.425, 95% CI [0.861, 1.990], p=0.0000

Wrong-answer (confident error) logit:

    from_wikipedia: coef=-0.042, 95% CI [-0.782, 0.698], p=0.9119


## SQ1-forced. Forced answers (no UNKNOWN allowed): latent knowledge

Rows: 2157. Abstentions that slipped through: 5; unparsed: 1. With guessing forced, accuracy is directly comparable to the name-only baseline.


### HARD (A5-A7), forced

| model | acc_w0 | wrong_w0 | abst_w0 | acc_w1 | wrong_w1 | abst_w1 | acc_gap(wiki-no) | wrong_gap(no-wiki) |
|---|---|---|---|---|---|---|---|---|
| gpt-4 | 0.765 | 0.218 | 0.017 | 0.788 | 0.212 | 0.000 | 0.023 | 0.007 |
| gpt-4o | 0.790 | 0.210 | 0.000 | 0.815 | 0.185 | 0.000 | 0.024 | 0.024 |
| gpt-5 | 0.758 | 0.242 | 0.000 | 0.798 | 0.194 | 0.000 | 0.040 | 0.048 |
| gpt-5.5 | 0.855 | 0.145 | 0.000 | 0.831 | 0.169 | 0.000 | -0.024 | -0.024 |



### Is it knowledge, or just guessing from the school name?

`name_only_acc` = accuracy of a keyword rule that sees only the school name/city (no model). `above_name` = model accuracy minus that baseline: the share attributable to knowing the school.

| item | model_acc_w0 | model_acc_w1 | name_only_acc_w0 | name_only_acc_w1 | above_name_w0 | above_name_w1 |
|---|---|---|---|---|---|---|
| charter | 0.968 | 1.000 | 0.958 | 0.872 | 0.011 | 0.128 |
| enroll | 0.646 | 0.753 | 0.520 | 0.419 | 0.126 | 0.333 |
| grades | 0.854 | 0.773 | 0.561 | 0.439 | 0.293 | 0.333 |


Pooled logit, additionally controlling for whether the name alone gives the answer away (`base_ok`):

    from_wikipedia: coef=0.488, 95% CI [0.031, 0.946], p=0.0363



    School-bootstrap (4000 draws) wiki - no-wiki gap in accuracy: +0.036, 95% CI [-0.039, +0.112]
    ... in accuracy ABOVE the name-only baseline (knowledge beyond the name): +0.122, 95% CI [+0.005, +0.238]
    PAIRED (enrollment-matched pairs, n=50) wiki - no-wiki accuracy: +0.036, 95% CI [-0.038, +0.112]
    PAIRED, accuracy ABOVE the name-only baseline: +0.122, 95% CI [+0.033, +0.207]


### EASY (A1-A4), forced

| model | acc_w0 | wrong_w0 | abst_w0 | acc_w1 | wrong_w1 | abst_w1 | acc_gap(wiki-no) | wrong_gap(no-wiki) |
|---|---|---|---|---|---|---|---|---|
| gpt-4 | 0.916 | 0.063 | 0.021 | 0.965 | 0.035 | 0.000 | 0.049 | 0.028 |
| gpt-4o | 0.946 | 0.054 | 0.000 | 0.993 | 0.007 | 0.000 | 0.047 | 0.047 |
| gpt-5 | 0.953 | 0.047 | 0.000 | 0.986 | 0.014 | 0.000 | 0.033 | 0.033 |
| gpt-5.5 | 0.960 | 0.040 | 0.000 | 0.986 | 0.014 | 0.000 | 0.027 | 0.027 |



### Is it knowledge, or just guessing from the school name?

`name_only_acc` = accuracy of a keyword rule that sees only the school name/city (no model). `above_name` = model accuracy minus that baseline: the share attributable to knowing the school.

| item | model_acc_w0 | model_acc_w1 | name_only_acc_w0 | name_only_acc_w1 | above_name_w0 | above_name_w1 |
|---|---|---|---|---|---|---|
| district | 0.824 | 0.988 | 0.440 | 0.558 | 0.385 | 0.430 |
| level | 0.944 | 0.960 | 0.864 | 0.616 | 0.081 | 0.343 |
| religion | 0.981 | 0.990 | 0.845 | 0.654 | 0.136 | 0.337 |
| sector | 0.980 | 1.000 | 0.904 | 0.697 | 0.076 | 0.303 |


Pooled logit, additionally controlling for whether the name alone gives the answer away (`base_ok`):

    from_wikipedia: coef=2.191, 95% CI [1.031, 3.350], p=0.0002



    School-bootstrap (4000 draws) wiki - no-wiki gap in accuracy: +0.040, 95% CI [+0.005, +0.078]
    ... in accuracy ABOVE the name-only baseline (knowledge beyond the name): +0.203, 95% CI [+0.105, +0.303]
    PAIRED (enrollment-matched pairs, n=50) wiki - no-wiki accuracy: +0.040, 95% CI [+0.003, +0.080]
    PAIRED, accuracy ABOVE the name-only baseline: +0.203, 95% CI [+0.103, +0.308]


### Hard items: free-form vs forced, by model and wiki status

`dares_gap` = how much accuracy rises when the model is forced to answer = knowledge the model had but would not commit to.

| model | from_wikipedia | free_acc | free_abstain | forced_acc | dares_gap(forced-free) |
|---|---|---|---|---|---|
| gpt-4o | 0 | 0.113 | 0.855 | 0.790 | 0.677 |
| gpt-4o | 1 | 0.298 | 0.677 | 0.815 | 0.516 |
| gpt-5 | 0 | 0.500 | 0.387 | 0.758 | 0.258 |
| gpt-5 | 1 | 0.742 | 0.073 | 0.798 | 0.056 |
| gpt-5.5 | 0 | 0.589 | 0.371 | 0.855 | 0.266 |
| gpt-5.5 | 1 | 0.758 | 0.169 | 0.831 | 0.073 |



## SQ1-masked. How much is knowledge of the specific school? (real name+city vs hidden name, no city)

Both conditions force an answer. `masked` = guessable from name structure + state; `real` = with the true name and city; `identity_gain` = real - masked. District item excluded (it needs the city).

| model | item | from_wikipedia | masked | real | identity_gain |
|---|---|---|---|---|---|
| gpt-4 | charter | 0 | 0.938 | 0.957 | 0.019 |
| gpt-4 | charter | 1 | 1.000 | 1.000 | 0.000 |
| gpt-4 | enroll | 0 | 0.419 | 0.604 | 0.185 |
| gpt-4 | enroll | 1 | 0.235 | 0.771 | 0.536 |
| gpt-4 | grades | 0 | 0.645 | 0.833 | 0.188 |
| gpt-4 | grades | 1 | 0.529 | 0.708 | 0.179 |
| gpt-4 | level | 0 | 0.935 | 0.938 | 0.002 |
| gpt-4 | level | 1 | 0.706 | 0.938 | 0.232 |
| gpt-4 | religion | 0 | 0.867 | 0.920 | 0.053 |
| gpt-4 | religion | 1 | 0.545 | 0.962 | 0.416 |
| gpt-4 | sector | 0 | 0.968 | 0.979 | 0.011 |
| gpt-4 | sector | 1 | 0.765 | 1.000 | 0.235 |
| gpt-4o | charter | 0 | 0.917 | 0.958 | 0.042 |
| gpt-4o | charter | 1 | 0.875 | 1.000 | 0.125 |
| gpt-4o | enroll | 0 | 0.420 | 0.680 | 0.260 |
| gpt-4o | enroll | 1 | 0.260 | 0.780 | 0.520 |
| gpt-4o | grades | 0 | 0.680 | 0.820 | 0.140 |
| gpt-4o | grades | 1 | 0.580 | 0.760 | 0.180 |
| gpt-4o | level | 0 | 0.920 | 0.940 | 0.020 |
| gpt-4o | level | 1 | 0.840 | 0.980 | 0.140 |
| gpt-4o | religion | 0 | 0.846 | 1.000 | 0.154 |
| gpt-4o | religion | 1 | 0.538 | 1.000 | 0.462 |
| gpt-4o | sector | 0 | 0.900 | 0.980 | 0.080 |
| gpt-4o | sector | 1 | 0.700 | 1.000 | 0.300 |


Per-school mean gain over items (wiki vs no-wiki), by model:

| model | gain no-wiki | gain wiki | wiki - no-wiki (95% CI, bootstrap over schools/pairs) |
|---|---|---|---|
| gpt-4 | +0.087 | +0.259 | +0.080 [-0.020, +0.180] |
| gpt-4o | +0.120 | +0.288 | +0.168 [+0.088, +0.248] |

Reading: `gain wiki > gain no-wiki` means knowing the real identity helps more for wiki schools, i.e. a genuine school-specific knowledge gap, net of what the name structure gives away. Near-equal gains mean the models' knowledge of the two groups is similar once guessing is controlled.


## SQ2. Wrong-vs-abstain behaviour

`wrong_*` = confident wrong answer rate (objective hallucination), `abst_*` = said UNKNOWN. Compare: a model that does not know should abstain, not err.

| model | wrong_w0 | abst_w0 | wrong_w1 | abst_w1 | wrong_gap(no-wiki) |
|---|---|---|---|---|---|
| gpt-4o | 0.000 | 0.671 | 0.000 | 0.466 | 0.000 |
| gpt-5 | 0.020 | 0.161 | 0.014 | 0.054 | 0.007 |
| gpt-5.5 | 0.034 | 0.040 | 0.007 | 0.020 | 0.027 |


Wrong-answer logit:

    from_wikipedia: coef=-1.008, 95% CI [-2.324, 0.309], p=0.1335


## Sample balance (wiki vs no-wiki)

| variable | wiki_mean | no_wiki_mean | SMD |
|---|---|---|---|
| log enrollment | 6.132 | 6.128 | 0.004 |
| log name frequency in state | 0.014 | 0.090 | -0.283 |
| free/reduced lunch share (public) | 0.547 | 0.615 | -0.282 |


Design: 50 enrollment-matched pairs (max |log ratio| = 0.19).


## SQ3. Do models agree on the gap?

Per-model gaps are in the SQ1 table. Interaction test (wiki x model):

    LR chi2=0.18, df=2, p=0.9160  (item-level; ignores clustering, indicative only)


## SQ4. Urban/suburban/rural beyond wiki status

| locale3 | 0 | 1 |
|---|---|---|
| rural | 0.654 | 0.809 |
| suburban | 0.708 | 0.868 |
| urban | 0.716 | 0.761 |


Logit with wiki x locale interaction (reference = urban):

    C(locale3, Treatment('urban'))[T.rural]: coef=-0.270, 95% CI [-1.645, 1.104], p=0.6999
    C(locale3, Treatment('urban'))[T.suburban]: coef=-0.315, 95% CI [-1.786, 1.156], p=0.6748
    from_wikipedia:C(locale3, Treatment('urban'))[T.rural]: coef=1.117, 95% CI [-0.790, 3.023], p=0.2511
    from_wikipedia:C(locale3, Treatment('urban'))[T.suburban]: coef=1.346, 95% CI [-0.619, 3.312], p=0.1795


## SQ6. Gap across model versions (same family)

| model | family | release | cutoff | acc_w0 | acc_w1 | acc_gap(wiki-no) | wrong_w0 |
|---|---|---|---|---|---|---|---|
| gpt-4o | gpt | 2024-05 | 2023-10 | 0.329 | 0.534 | 0.205 | 0.000 |
| gpt-5 | gpt | 2025-08 | 2024-09 | 0.819 | 0.932 | 0.114 | 0.020 |
| gpt-5.5 | gpt | 2026-04 | None | 0.926 | 0.973 | 0.047 | 0.034 |


Caveat: schools founded after a model's knowledge cutoff cannot be known; check `cutoff` vs school open dates before reading a shrinking gap as progress.
