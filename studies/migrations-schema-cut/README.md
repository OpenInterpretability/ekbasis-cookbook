# Schema cut in the migration guard (positive result, non-inferior)

* **Pre-registration:** `PREREG.md`, sha256 `02f3ba6c…`, frozen on 2026-10-11 before any call to Ekbasis and before
  the T2 and T3 states were built.
* **Deviations:** `DEVIATIONS.md`, covering the session interruption (no answer lost), the OLD state of T3, chirpstack
  and the documentation written after the test.
* **Numbers:** `results_t2.txt`, `results_t3.txt` and `dev_d2_summary.txt`.
* **Code:** local branch `schema-pruning` of ekbasis.
  * `fab1d95` is the code that was tested.
  * `aea2632` only adds documentation.
  * The diff against `main` (`ec91a41`, 0.1.17) is in `schema-pruning.diff`.
  * There was no push, no PR and no deploy.

## Question

The request assumed that the guard sends the whole schema to the model. **It does not.** 0.1.17 already cuts the
schema, by regex:

* the tables whose name appears in the migration text come in, including inside strings;
* their FK neighbors come in too, with a cap of 8 tables;
* the remaining tables become a line of names;
* views, triggers, functions, sequences and domains do not come in.

The question was reframed before the PREREG. **Does a cut by parser, which shows what the migration actually touches
and what depends on it, do at least as well as the cut by regex?** And what happens to the tokens? The hypothesis on
tokens was left two-sided.

## What NEW does

* **Touched tables, in full DDL and with no cap.** They are found by parser:
  * ALTER, INSERT, UPDATE, DELETE, TRUNCATE, DROP, CREATE INDEX/TRIGGER/POLICY ON;
  * FROM/JOIN, including from subqueries and CTEs;
  * REFERENCES, LIKE and PARTITION OF;
  * indexes and sequences, resolved to the owning table; types and domains, resolved to the tables that use them;
  * qualified and quoted names;
  * bodies of DO and of sql/plpgsql functions, without comments;
  * the tables written by the trigger functions.
* **FK neighbors at 1 hop, in both directions: one line each,** with the key, the ON DELETE and the NOT NULL, plus the
  "Rows" line. In the first version, with the full DDL of the neighbors, the states of the real cases grew 2 to 3.5
  times. This swap was decided during development, with no model.
* **Dependent views,** via `pg_depend` and transitively, in one line: "v reads T(columns)".
* **Triggers with the function bodies** up to 20,000 characters, plus owned sequences, enums and domains.
* **One fact line:** "N other tables omitted: not touched by this migration and not linked to it by a foreign key".
* **Fallback to the 0.1.17 state, with a note,** when:
  * there is dynamic SQL (EXECUTE);
  * there is a command outside the list;
  * there is a name the parser does not resolve;
  * there is a body in another language;
  * the cut state still goes over `MAX_CHARS`.

  This is why coverage never gets worse.
* **What does not change:** probes, decisions in code, questions, thresholds and `MAX_CHARS`. The `VerdictCache` gets
  the cut version in its key. `EKBASIS_SCHEMA_CUT=off` turns the cut off.
* **Tests:** 5 new offline and 1 with PostgreSQL. The whole suite gives 259 passed, 2 skipped, with a local PG 16.

## T2: the 184 migrations of v3 (128 benign, 56 risky)

OLD is checkout `ec91a41`; NEW is `fab1d95`. Both read the same inputs, and the OLD state is byte for byte that of v4.

* There were 734 calls to the hosted API, with concurrency 2 and shuffled order. None went unanswered.
* On the only item in fallback (EXECUTE), NEW inherited the OLD answer.

| Regime | | Accuracy | False alarm | Recall | Exact reason |
|---|---|---|---|---|---|
| R (replica, primary) | OLD | 162/184 = 0.880 | 20/128 | 54/56 | 49 |
| | NEW | **165/184 = 0.897** | **17/128** | 54/56 | 48 |
| N (no replica, the Action's default) | OLD | 163/184 = 0.886 | 19/128 | 54/56 | 46 |
| | NEW | 163/184 = 0.886 | 18/128 | 53/56 | 46 |

| Criterion (threshold) | R | N |
|---|---|---|
| C1 accuracy ≥ OLD − 2 pp | +1.6 pp, 95% CI [−1.1; +4.3], McNemar 5×2, p = 0.45: **passes** | +0.0 pp, CI [−2.7; +2.7], McNemar 3×3, p = 1.0: **passes** |
| C2 false alarm ≤ OLD + 3 | 17 against 20: **passes** | 18 against 19: **passes** |
| C3 recall ≥ OLD − 2 | 54 against 54: **passes** | 53 against 54: **passes** |
| C4 exact reason ≥ OLD − 2 | 48 against 49: **passes** | 46 against 46: **passes** |

**Pre-registered decision:** all criteria pass in both regimes, and **the cut is recommended as the default**, with
`MAX_CHARS` as a safety net.

**Statistical caveat (pre-registered):** in regime N, the CI of the accuracy difference goes down to −2.7 pp.
Non-inferiority passes on the point estimate, but **is not statistically demonstrated** with n = 184. In regime R, the
CI sits entirely above −2 pp.

**Tokens and latency** (183 pairs; API `usage`):

| | Median input tokens, OLD → NEW | Paired median reduction (p10; p90) | Total | Model time (median) |
|---|---|---|---|---|
| R | 4,196 → 2,854 | −22.6% (+74%; −48%) | 840,883 → 793,191 (−5.7%) | 2.52 → 2.60 s |
| N | 3,286 → 1,762 | −30.3% (+33%; −61%) | 674,420 → 527,519 (−21.8%) | 2.25 → 2.01 s |

The typical case gets cheaper, but the tail gets more expensive. On one tenth of the items, NEW costs 33% to 74% more,
because it shows all the touched tables, with no cap, and the trigger function bodies. This is why the total falls
little in regime R. Latency does not change in any relevant way: the queue was 3 ms, and wall time stayed between 2.7
and 3.2 s in both arms.

**Items that changed** (full list in `results_t2.txt`):

* **R:** 10 changed. 5 false alarms improved (cratesio dumped_migration_30, lemmy reply_materialized_view, lemmy
  username-instance-unique, mattermost 000051 and 000112) and 1 reason (calcom remove_fields: from fails to loses,
  which is the correct one). 2 new alarms on benign items got worse (calcom allow_one_schedule and langfuse
  score_configs_rename, the latter with P(fail) = 0.50, exactly at the threshold) and so did 2 reasons on risky items.
* **N:** the only risky item missed was triggerdev/more_kv_types, with P(fail) going from 0.68 to 0.06. The relevant
  facts are in both states: the enum loses 'KEY_VALUE' and the column is converted. NEW has 3,000 characters against
  7,000 for OLD. No structural cause was found; I treat it as model variation with a different text.

**Mechanism (c), a view that depends on the dropped column.**

* In T2, no migration drops or changes the type of a column read by a view (`view_mech.py`: 0 items). The mechanism
  could not be measured in the test.
* 30 items have dependent views in the NEW state: OLD is right on 24 and NEW on 25.
* In development (D2), 3 lemmy migrations touch columns read by views. All of them handle the views themselves (DROP
  VIEW first). NEW shows the dependency, and OLD cannot show it.

## T3: large schemas in 8 new repositories (coverage, no model)

The repositories are AFFiNE, ghostfolio, typebot, webstudio, harbor, concourse, chirpstack and fider. In each one, the
PostgreSQL folder that the product finds on its own was included, and each migration was evaluated before being
applied.

| | Migrations | With state | OLD > 60k | NEW > 60k | Became answered | NEW fallback |
|---|---|---|---|---|---|---|
| Total | 696 | 644 | **0** | 0 | **0** | 35 (5.4%) |

* **Primary measure: 0 of 644.** No migration gives "cannot foresee" for size today. The largest OLD state has 43,338
  characters, and the largest schema, 70 tables (AFFiNE).
* As pre-registered, there were no labels and no calls in T3: there was no item that went from "too long" to answered.
* **Conclusion:** in these projects, `MAX_CHARS` does not overflow, because the 8-table cap of 0.1.17 already holds the
  size down. The cut unlocks nothing here; what it changes is *which* tables appear.
* **Generalization of the parser to code never seen:**
  * fallback in 5.4%, against 0.9% in development;
  * 31 of the 35 fallbacks are EXECUTE inside DO blocks, 29 of them in concourse, which builds dynamic DDL;
  * 2 are unresolved index names, 1 is a state that is too long and 1 is DROP FUNCTION CASCADE.
  * In all of these cases, the state is the 0.1.17 one.
* **Size:** the NEW/OLD ratio has median 0.69 (p10 0.42; p90 1.13).
* **Limits of T3** (detailed in `DEVIATIONS.md`):
  * chirpstack went in with 1 migration, because its main folder does not match the default globs;
  * in fider, 46 of 49 migrations became `cannot_foresee_base`, because one base migration requires a privilege.

## Development (already seen)

* **D2, the 582 of v1 (530 with state):**
  * fallback in 0.9%;
  * median state from 6,235 to 4,238 characters;
  * in **59** items, OLD omitted a table that the migration touches, because of the cap of 8 or the regex;
  * in 18, OLD showed tables that the migration does not touch, almost always because of a name matched inside strings;
  * views come in on 56 items; triggers, on 47.
* **34 real cases:** 2 fallbacks, one EXECUTE (mattermost) and two unresolved transition tables (coder), and no verdict
  in code changed. The PREREG described these fallbacks wrongly (deviation 6). In most cases the state got smaller; in
  lemmy, where there are many triggers, it got larger.

## Limits

* T2 has the power to detect differences of a few points, not of 1 pp. The result is "non-inferior", and in regime N
  only by the point estimate.
* The accuracy gain in R (+1.6 pp, 5 against 2) is not significant (p = 0.45).
* The view mechanism (c) did not show up in the test.
* The token reduction is a median, not a total. In projects with many triggers, or with migrations that touch many
  tables, the state grows.
* T3 showed that "cannot foresee for size" is rare today, and it does not support the premise that large projects
  overflow the limit.

## Reproduction

Use a local PostgreSQL 16 with locale C, timezone UTC and `lc_messages=C`.

1. `build_cut.py`: D2 and T2 inputs with the extended catalog.
2. `same_as_v4.py`: checks the OLD states against v4.
3. `compare_states.py`: state comparison in development.
4. `dev_real.py`: the real cases.
5. `states_t2.py`: T2 states, run once with `PYTHONPATH=ekbasis_old` and once with `PYTHONPATH=ekbasis`.
6. `ask_t2.py`: the API calls.
7. `analysis_t2.py`: the T2 criteria.
8. `t3_cover.py` and `t3_summary.py`: T3.
9. `view_mech.py`: mechanism (c).
