# Ekbasis as a guard for Dependabot bumps: "does this PR break CI?"

*Pre-registered vertical pilot, run on 2026-10-11 on the hosted API (client `ekbasis==0.1.16`). The PRs are public,
opened by Dependabot after 2026-06-01. The label is the result of the GitHub Actions check runs, never a model or a
reader. Nothing was published.*

## Summary

- **Question.** With facts collected by code in the state, does Ekbasis predict better than a fixed rule whether a bump
  of a package (npm or PyPI) breaks the PR's CI?
- **Data.** 1,800 repositories and 9,159 candidate PRs. Dev: 148 labeled PRs, 17 broken, 56 repositories. Test: 329
  labeled PRs, 42 broken, 104 repositories, with owners that do not appear in dev. Majors were oversampled (3 majors
  and 3 others per repository).
- **It discriminates: yes.** On test, AUROC 0.763 [0.662; 0.849] (H1 passed). Within semver-major, 0.704
  [0.555; 0.827] (H5 passed). It orders the top well: of the 10 highest-risk PRs, 8 broke (the base rate is 12.8%).
- **It beats the rule on F1: no.** F1 0.391 against 0.381 for R1 (major = break): ΔF1 +0.010 [−0.116; +0.126]
  (**H2 failed**). The gain over R1 is all in false alarm: 9.8% against 26.8% (H4 passed). McNemar on accuracy favors
  Ekbasis by 54 to 16 PRs, p < 0.001 (H3 passed), but this reflects the same reduction in false alarm on a sample
  where 87% of the PRs do not break.
- **Against the rule "major + breaking" (R2), it ties.** F1 0.400, false alarm 9.1%, McNemar 14 to 16 (p = 0.86), and
  the verdicts coincide on 299 of 329 PRs. On dev, R2 was worse (0.233), which is why R1 was registered as the
  comparison rule.
- **Where it is right: when there is a concrete mechanism.** Incompatible peer, Node below the new minimum, an ESM-only
  package loaded with `require()`: mean score of 0.91 to 0.95 on the broken ones, and all of these PRs were flagged.
  With no mechanism fact at all (248 PRs, 21 broken), the score stays at 0.13 on the broken ones and at 0.07 on the
  ones that pass.
- **Decision (prereg criterion): it does not become a gate.** H1 without H2: it is useful for **ranking risk**, not
  for blocking the PR.
- **Cost.** 1.31 M input tokens in 625 requests (dev twice, test once), about US$ 0.05. Median of 1.3 s per request
  end to end. Concurrency 1 throughout.

## 1. Design

**Hypothesis.** Ekbasis only beats the rule when the fact points to a mechanism. Without such a fact, it should stay
close to "major = break" (PREREG §1).

**Sample (§2).** Search of TypeScript, JavaScript and Python repositories in three star bands. Dependabot PRs for a
single package, with no groups, created after 2026-06-01, one per (repository, package). Dev/test split by **owner**
via sha256; lists frozen by hash before any label. Dependabot only, because Renovate's format is different.

**Label (§3).** A GitHub Actions job fails on the PR head **and the same job passed on the base commit**. It uses
`filter=latest` (a re-run that passed counts as passed). Bot jobs and repository task jobs are left out. A "systematic"
job (fails in at least half of the repository's PRs, with at least 4) is ignored. Excluded were: no CI, human commits
and not attributable (the job also fails on the base).

| | dev | test |
|---|---|---|
| sampled | 200 | 450 |
| broken / not broken | 17 / 131 | 43 / 292 → 42 / 287 after an extraction failure |
| no CI / human commits / not attributable | 37 / 7 / 8 | 66 / 26 / 23 |

**State (§4).** The client's `world_state` layout. Facts extracted by code:

- semver delta;
- lines from the release notes between the versions (Dependabot body and GitHub releases) that mention breaking,
  removed, deprecated and the like;
- `engines.node` or `requires_python` before and after, against the versions in the workflows, with "below the
  minimum" decided in code;
- ESM format and who `require()`s the package;
- peers, with the conflict against the version declared in the repository;
- transitives from the lockfile;
- files that import the package and a count of the names cited in the notes, with `file:line` examples;
- CI commands.

The repository name does not enter the state.

**Questions (§5).** `api` (an API the repository uses was removed or changed), `other` (install, build, types, lint,
tests, runtime) and `any`. One request per PR. The choices made on dev (§7, `ADDENDUM_DEV.md`, hash sent before the
test) were: score `max(api, other)`, threshold 0.2 and R1 as the comparison rule.

## 2. Result on test (registered)

| | F1 | precision | recall | false alarm | accuracy |
|---|---|---|---|---|---|
| **Ekbasis** (max ≥ 0.2) | 0.391 | 0.378 | 0.405 | **0.098** | 0.839 |
| R1: major | 0.381 | 0.267 | 0.667 | 0.268 | 0.723 |
| R2: major + "breaking" | 0.400 | 0.395 | 0.405 | 0.091 | 0.845 |

| Criterion | Value | |
|---|---|---|
| H1 AUROC ≥ 0.70, CI > 0.5 | 0.763 [0.662; 0.849] | passed |
| H2 ΔF1 vs R1 ≥ +0.05, CI > 0 | +0.010 [−0.116; +0.126] | **failed** |
| H3 McNemar vs R1 | 54 to 16, p < 0.001 | passed |
| H4 false alarm ≤ R1 | 0.098 vs 0.268 | passed |
| H5 AUROC within major ≥ 0.65 | 0.704 [0.555; 0.827] | passed |

Reported without a criterion: AUROC per question (api 0.758, other 0.768, any 0.730); npm 0.778 (35 positives) and
PyPI 0.685 (only 7 positives); non-major 0.648, but the 0.2 threshold flags none of the 14 non-major positives; ECE
0.078. The threshold sweep gives F1 between 0.34 and 0.39 across the whole range from 0.2 to 0.8, with no point that
changes the conclusion.

**Power.** There are 42 positives, above the prereg floor of 30, but the CI of ΔF1 is ±0.12 wide. A real gain of +0.05
would not be detected with this sample.

## 3. Exploratory analyses (not registered, done after seeing the test; `explore.py`)

- **Code rules with the same facts.** "Peer, runtime or ESM" has F1 0.303 and a false alarm of 4.9%. "R2 or mechanism"
  reaches F1 0.400. Nothing goes above about 0.40. The ceiling seems to be in the labels and the facts, not in the
  model.
- **Precision at the top.** Of the 10 PRs with the highest score, 8 broke; of the top 20, 11; of the top 45, 17. Among
  the 105 majors, the half with the highest score concentrates 19 of the 28 broken ones.
- **Strata.** Among the 43 PRs that R2 flags, the AUROC is 0.645. Among majors with no "breaking", it is 0.685, and
  there Ekbasis finds 4 of 11 broken ones with a 13.7% false alarm. This is what it adds to the rule, and it is little.

## 4. Failure modes

1. **Half of the broken ones have no fact that explains the break (21 of 42).** These are jobs that check their own
   lockfile or `dist/` ("Hash lock", "check-dist", "Check licenses", "dependency-check", "Enforce style"), CI on Node
   26 or macOS, and e2e. No fact in the state points to them, and the model gives 0.02 to 0.10, which is the right
   behavior for the state it received.
2. **A true mechanism fact that does not break.** `runtime_below_min` is right on 4 of 12. The CI matrix lists Node 18,
   but the job does not run the package on that version, or `engines` is not enforced. `peer_mismatch` is right on 5
   of 11, because npm installs with a warning and the build passes. The model believes the fact (score of 0.8 to 0.9),
   and from this come 11 of the 18 false alarms with score ≥ 0.5.
3. **Useless release notes.** TypeScript 7 points to a blog post. Monorepos have tags for other packages. With no
   breaking line and no mechanism, a major that breaks comes out with a low score (TS 7 on dev, commander, pino,
   Modernizr).
4. **Clustered repositories.** The positives are concentrated (voyager 4, bull, koa and Modernizr 3 each), which is why
   the bootstrap is by repository.

## 5. Caveats

- The label has noise: a flaky job that fails on the PR and passes on the base counts as a break, and we did not
  re-run anything. The systematic-job rule only catches repositories with at least 4 PRs.
- The sample over-represents majors (32% on test), and the numbers do not hold for Dependabot's natural flow, which is
  almost all patches.
- PRs after 2026-06-01 reduce, but do not eliminate, memorization (the release notes may be older).
- PyPI has only 7 positives on test and does not allow a conclusion.
- A single extraction revision on dev (cache corrupted by a race between threads) and 7 registered deviations, none of
  them after seeing the test that changes a metric (`frozen/DEVIATIONS.md`).

## 6. Is it worth making a product?

**As a merge gate, no.** By the registered criterion (H2), and because a one-line rule, "major with 'breaking' in the
notes", delivers the same F1 and the same false alarm.

**As triage, maybe.** What works is ordering the queue of Dependabot PRs and explaining why. The top of the queue has
80% precision, and when the state carries a mechanism (peer, runtime, ESM-only, removed name in use) Ekbasis
recognizes it. A product version would have to fetch the facts that were missing, and not change the model. The most
promising ones:

- whether the CI job really runs on the Node and Python versions of the matrix;
- whether npm enforces peer and engines (`engine-strict`, `legacy-peer-deps`);
- whether the CI checks the lockfile, `dist/` and licenses.

Only after that is a second pilot worth it. Today, this vertical stays behind the migration guard.

## Files

`frozen/` contains:

- `PREREG.md`: sha256 90ffb46e…, sent before any call;
- `MANIFEST.sha256`, with the dev and test lists;
- `ADDENDUM_DEV.md`: sha256 1e81eda1…, sent before the test;
- `DEVIATIONS.md`;
- copies of the code.

At the root are the pipeline scripts: `collect.py`, `sample.py`, `label.py`, `facts.py`, `state.py`,
`build_facts.py`, `run_ekbasis.py`, `analysis.py` and `explore.py`. In `data/` are labels, facts, answers,
`test_analysis.json` and `test_explore.txt`. The GitHub and source-code cache is in `cache/`, which must not be
redistributed.
