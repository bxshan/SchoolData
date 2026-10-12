# Exposure experiment

Model: gpt-4o. Split at its assumed knowledge cutoff 2023-10-01 (config; verify). exposed = Wikipedia page created on/before the cutoff, unexposed = after. Pool: {'exposed': 49, 'unexposed': 49, 'NCES_template': 40, 'famous': 15}


## Design 1. Verbatim continuation of the opening text

`recall4` = share of the true continuation's 4-grams the model reproduced; `run_frac` = longest verbatim run / target length. NCES_template = machine-generated paragraphs the model cannot have seen (reference for how predictable such text is).

| group | recall4 | run_frac | run | n |
|---|---|---|---|---|
| NCES_template | 0.019 | 0.081 | 2.125 | 40 |
| exposed | 0.030 | 0.112 | 2.857 | 49 |
| famous | 0.027 | 0.117 | 3.000 | 15 |
| unexposed | 0.026 | 0.095 | 2.429 | 49 |


| contrast | metric | diff | 95% CI (bootstrap over schools) |
|---|---|---|---|
| exposed - unexposed | recall4 | +0.004 | [-0.020, +0.027] |
| exposed - unexposed | run_frac | +0.017 | [-0.014, +0.046] |
| exposed - NCES_template | recall4 | +0.011 | [-0.011, +0.031] |
| exposed - NCES_template | run_frac | +0.032 | [+0.003, +0.059] |
| unexposed - NCES_template | recall4 | +0.006 | [-0.018, +0.032] |
| unexposed - NCES_template | run_frac | +0.015 | [-0.016, +0.047] |
| famous - exposed | recall4 | -0.003 | [-0.030, +0.032] |
| famous - exposed | run_frac | +0.004 | [-0.031, +0.047] |
| famous - NCES_template | recall4 | +0.008 | [-0.020, +0.045] |
| famous - NCES_template | run_frac | +0.036 | [-0.002, +0.080] |

Regression on wiki pages (OLS, HC3): recall4 ~ unexposed + months from cutoff (+ controls). `unexposed` is the jump at the cutoff.

- no controls: unexposed -0.006 [-0.056, +0.044] p=0.810 (n=98)
- + log page views, log enrollment, sector: unexposed -0.007 [-0.060, +0.047] p=0.811 (n=98)
- dose-response inside the exposed group: recall4 vs log page views rho=-0.14 p=0.330 (n=49)

## Design 2. Wiki-only facts (founding year, namesake, mascot, programs...)

Questions extracted from the article lead, graded against that reference by claude-opus-5-5. 282 questions over 106 schools.

| group | correct | abstain | wrong | n_schools |
|---|---|---|---|---|
| exposed | 0.019 | 0.981 | 0.000 | 44 |
| unexposed | 0.007 | 0.993 | 0.000 | 47 |


exposed - unexposed accuracy: +0.012, 95% CI [-0.014, +0.043] (bootstrap over schools)

Reading: if reading the Wikipedia page teaches the model, exposed > unexposed on both designs. Page creation date is not the date of the text the model saw; later pages may differ in school type or notability (see the balance table and the controlled regression).


## Direct forced questions: founding year, mascot, school colors (with confidence and basis)

School named, answer forced. Truth = what the Wikipedia article states. Year is scored as absolute error in years; mascot and colors are judged by claude-opus-5-5. `guess baseline` = always answering the median founding year of the wiki schools in this pool.

### Founding year

| group | n | median_error_years | within_2_years | guess_baseline_median_error | mean_confidence |
|---|---|---|---|---|---|
| exposed | 27 | 1.000 | 0.630 | 15.000 | 63.330 |
| famous | 14 | 0.000 | 0.930 | 84.000 | 75.710 |
| unexposed | 24 | 1.500 | 0.580 | 15.000 | 60.420 |


**Positive-control gate (famous schools)**: median error 0.0 y vs guess baseline 84.0 y -> PASS (rule: error <= half the baseline). The test can detect knowledge.

| contrast (exposed - unexposed) | diff | 95% CI (bootstrap over schools) |
|---|---|---|
| mean log(1+error) | -0.238 | [-1.092, +0.582] |
| share within 2 years | +0.046 | [-0.222, +0.319] |

Mann-Whitney on absolute error: p=0.575 (n=27 vs 24); median error 1.0 (exposed) vs 1.5 (unexposed)

- OLS log(1+error) ~ unexposed + school age + enrollment + page views + sector, all schools: unexposed -0.404 [-1.115, +0.308] p=0.266 (n=51)
- OLS log(1+error) ~ unexposed + school age + enrollment + page views + sector, founded before 2015 only: unexposed +0.061 [-1.177, +1.300] p=0.923 (n=30)

### Confidence and stated basis (founding year)

| group | conf_when_correct | conf_when_wrong |
|---|---|---|
| exposed | 67.100 | 57.000 |
| famous | 75.400 | 80.000 |
| unexposed | 65.000 | 54.000 |


Stated basis (A = recalls this school, B = inferred from name/place, C = random guess): share and accuracy within 2 years

| group | year_basis | n | within_2_years |
|---|---|---|---|
| exposed | A | 1 | 1.000 |
| exposed | B | 26 | 0.620 |
| famous | A | 11 | 0.910 |
| famous | B | 3 | 1.000 |
| unexposed | A | 1 | 0.000 |
| unexposed | B | 23 | 0.610 |


These are self-reports and are NOT evidence of where the knowledge came from; they only show whether the model's stated certainty tracks being right.

### Mascot and school colors (accuracy)

| field | group | n | accuracy |
|---|---|---|---|
| colors | exposed | 14 | 0.214 |
| colors | famous | 3 | 0.667 |
| colors | unexposed | 9 | 0.222 |
| mascot | exposed | 21 | 0.810 |
| mascot | famous | 3 | 1.000 |
| mascot | unexposed | 26 | 0.769 |


- mascot: exposed - unexposed accuracy +0.040 [-0.189, +0.269]
- colors: exposed - unexposed accuracy -0.008 [-0.373, +0.317]
- guess baseline for mascot: the most common true mascot ('tigers') covers 6% of schools


## Design 2 (multiple choice). Wiki-only facts, 4 options, forced choice

Random guessing = 0.25. `blind` = the same questions with the school name withheld (checks that the options do not give the answer away). `knowledge` = accuracy with the school named minus blind accuracy, per school.

| group | acc | n_schools | n_questions | blind_acc |
|---|---|---|---|---|
| exposed | 0.557 | 44 | 107 | 0.621 |
| famous | 0.667 | 15 | 45 | 0.667 |
| unexposed | 0.599 | 47 | 130 | 0.617 |


Knowledge above the blind baseline (mean per school):

| group | knowledge |
|---|---|
| exposed | -0.064 |
| famous | 0.000 |
| unexposed | -0.018 |


| contrast | accuracy diff | 95% CI (bootstrap over schools) |
|---|---|---|
| exposed - unexposed | -0.042 | [-0.182, +0.100] |
| famous - exposed | +0.110 | [-0.071, +0.302] |
| famous - unexposed | +0.067 | [-0.108, +0.246] |
| exposed - unexposed, knowledge above blind | -0.047 | [-0.161, +0.075] |
| famous - exposed, knowledge above blind | +0.064 | [-0.052, +0.177] |

Regression (OLS, HC3) acc ~ unexposed + months from cutoff + log page views + log enrollment + sector: unexposed +0.008 [-0.261, +0.277] p=0.953 (n=91)

Letters chosen (position-bias check; the correct letter is uniformly shuffled): A=0.28, B=0.27, C=0.28, D=0.17

Reading: positive control (famous) well above 0.25 and above blind shows the test can detect knowledge. If exposed > unexposed, reading the page taught GPT-4o school-specific facts. If blind is well above 0.25, the options leak the answer.
