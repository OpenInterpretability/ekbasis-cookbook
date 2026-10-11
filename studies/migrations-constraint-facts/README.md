# Migrations v4: constraint facts about existing rows (a negative result)

*Pre-registered, run 2026-10-11 on the hosted API (Ekbasis-27B-INT4). The plan, `frozen/PREREG_v4.md` (sha256
`924d370388880c9b278eb1c3c91832815c8cd05d2e0d1bc7112a76cb5dc03d73`), was frozen before any model call. The addenda are
in `frozen/DEVIATIONS_v4.md`, the numbers in `frozen/results_v4.txt`, and the hashes of the scripts and inputs in
`frozen/MANIFEST_v4.sha256`. The plan and the addenda are in Portuguese, as they were sealed.*

## The question

In the backtest on real incidents ([`../migrations-real-incidents/`](../migrations-real-incidents/)), the pattern
that most often got past the migration guard was **a new constraint (CHECK, UNIQUE, FK, NOT NULL, enum), or a write
under an existing constraint, that old rows violate**. That was 6 of the 8 "missed".

The question: if the state says this explicitly, with facts decided in code, does the guard get it right for the
right reason more often, without paying a high price in false alarms? The facts come from the catalog, the statements
and the replica's aggregate statistics (NULL fraction and number of distinct values). Values never enter, nor do
minimum and maximum.

## Design

**Product.**

* `constraint_facts(catalog, statements, stats)`, on the `constraint-facts` branch of the ekbasis client: commit
  `5999e53`, from `8071e38`. The branch **is local and was never published**; there is no PR.
* The function writes one sentence per statement that checks a constraint against existing rows. Statistics enter
  only when they show a violation.
* There is a single decision in code: with a replica, a NOT NULL on a column where the replica shows NULLs, with
  nothing earlier in the file that fills them.
* Questions, thresholds (0.5) and the statistics query do not change.

**Development** (data already seen):

* the 34 candidates of the earlier backtest;
* the 582 migrations of study v1.

Two wordings were tried. The long one ("the statistics do not show whether…") lowered P(fail) on migrations that do
fail. The short one stayed, and the commit was frozen **before** the test incidents were chosen.

**Test.**

* **T1, new incidents:** from 12 repositories never used before (windmill, sourcegraph-public-snapshot, harness, ente,
  openmeter, inbox-zero, linkwarden, openpanel, teable, authelia, supabase/storage and atuin).
  * The mining has fixed rules: up to 25 commits with a strong signal per repository. The 119 commits were read one
    by one.
  * **9 incidents** were in scope (failure on the data or failure on the schema). The list was frozen with a hash
    before any call.
  * T1b is a secondary extension, 25 more commits in the two repositories that hit the cap, and gave 1 more.
* **T2, the 184 migrations of v3,** with their frozen labels: 128 benign and 56 risky. It measures the cost in false
  alarms.

**Arms.**

* OLD = `8071e38`; NEW = `5999e53`.
* Each in two regimes: R (seeded replica) and N (no replica, the Action's default).
* Hosted API, concurrency 1, cache off.
* When NEW's state is identical to OLD's, NEW inherits OLD's answer.

## Criteria and result

| | Criterion | Result | |
|---|---|---|---|
| P1 | Right for the right reason on T1, regime N: NEW − OLD ≥ +3 and one-sided McNemar p ≤ 0.10 | 3/9 → 3/9, gain **0** | **fail**, and underpowered (n = 9) |
| P2 | False alarms on T2, regime R, ≤ 15.6% + 3 pp (≤ 23/128) | 21/128 = 16.4% | pass |
| P3 | False alarms on T2, regime N: NEW − OLD ≤ +3 items | +3 | pass, at the limit |
| P4 | Recall on T2, regime R: NEW ≥ OLD − 2 | 54/56 → 54/56 | pass |

**Pre-registered decision: "does not improve what it promised".** No PR. The line of per-pattern facts is closed with
a negative result.

## Why it did not improve

* **The new incidents slip through patterns the event list does not cover:**
  1. `INSERT ... VALUES` of a key that already exists, without `ON CONFLICT` (windmill, `global_settings`);
  2. `INSERT` with a scalar subquery that returns NULL into a NOT NULL column when a row is missing (windmill,
     ducklake);
  3. `DELETE` of rows still referenced by an FK (sourcegraph, `batch_specs`). The guard flags it, but as "loses
     data";
  4. `INSERT` inside a `WITH` that omits a NOT NULL column with no default (openmeter, `subjects.updated_at`).
* **The only covered incident was already caught.** It is teable's UNIQUE with duplicates, and OLD already got it
  right.
* **An irrelevant fact got in the way.** On openmeter, the fact about the SET NOT NULL after the backfill lowered
  P(fail) from 0.25 to 0.08.
* **The model needs a concrete mechanism.** In development it only came to believe in a violation when the fact
  pointed to a concrete mechanism: a DEFAULT that the FK rejects, or rows that the earlier UPDATE does not cover. For
  pure CHECK and FK, the sentence "an old row may violate" did not move the probability.
* **Covering pattern by pattern has no power.** Each round brings about 9 new incidents, and covering one pattern at
  a time turns into chasing cases one by one, with no statistical power.

## Exploratory

* **Exact reason** on the flagged risky items of T2: in regime R, from 49 to 51 of 54; in regime N, from 46 to 50.
  NEW says "fails" more often and recall does not change.
* **Decision in code:** fired 2 times on T2 (regime R), and both truly fail. On T1, never.
* **API drift:** on the 136 states identical to v3's, no verdict changed (max |Δp| of 0.03).
* **Cost:** about 1,050 development calls, 14 on T1 and 452 on T2 (1.87 M input tokens).

## Caveats

* **Few incidents.** T1 has 9, below the 10 the pre-registration asked for P1 to have power. A small gain would not
  show.
* **Curation.** One person did the curation, after the product was frozen, with class and evidence fixed before any
  call. In 4 of the 9, the evidence is inferred from the fix's diff.
* **Synthetic labels.** T2's labels come from synthetic data (distinct rows, FKs only to seeded parents, NULL at 25%).
  They measure the false-alarm cost in that world, not in production.
* **One answer per item,** no repetition.
* **Maintenance window.** Part of the **development** calls (03:53–04:20 UTC) fell inside a scheduled server
  maintenance window. They came before the operational rule about it arrived. 13 of them returned HTTP 502, in a
  variant that was later discarded. The **test** calls (T1 and T2) ran afterwards, between 04:41 and 05:05 UTC, with
  no errors.

## Recompute

```
python recompute.py
```

Standard library only, under a second. It applies the frozen verdict logic (`frozen/analysis_v4.py` for T1,
`frozen/score_v4.py` for T2) to the released answers and writes `recompute_output.txt`. **The T1 and T2 sections are
byte-identical to `frozen/results_v4.txt`**, and P1–P4 come out as above. The exploratory lines (API drift against
v3, cost) are not recomputed here: the drift needs v3's answers ([`../migrations/v3/`](../migrations/v3/)).

## Files

| File | What it is |
|---|---|
| `answers_t1.jsonl` | the 10 incidents (T1 + T1b): upstream class, base and head commits, replica size, and for OLD and NEW in each regime the guard's per-file output (verdict kind, P(lost), P(fail), reason, notes, schema error); the state text is replaced by its sha256 |
| `answers_t2.jsonl` | the 184 migrations of T2: identifiers, pinned commit, file sha256, frozen label, and for each regime the code decision of OLD and NEW, whether NEW's state is byte-identical to OLD's, each state's sha256, and the model's P(yes) per arm |
| `recompute.py`, `recompute_output.txt` | the recompute above and its output |
| `dev/` | development answers, reduced to `id`, P(lost), P(fail), input tokens and request id (or the HTTP error): `d1_*` on the 34 backtest cases (variants A and B), `d2_*` on the v1 migrations whose state changed (`new` = variant A, `newB` = variant B, the frozen one) |
| `frozen/PREREG_v4.md`, `frozen/PREREG_v4.sha256` | the pre-registration and its hash |
| `frozen/DEVIATIONS_v4.md` | addendum 1 (frozen product and development), addendum 2 (T1 frozen) and addendum 3 (result) |
| `frozen/MANIFEST_v4.sha256` | hashes of the scripts, the incident list, the curation and the labels; every listed file is included and checks out (`cd frozen && shasum -a 256 -c MANIFEST_v4.sha256`) |
| `frozen/incidents_v4.jsonl`, `frozen/curation_v4.json` | the 10 incidents, with public links, and the reason for each discarded commit |
| `frozen/data/labels_v3.jsonl` | the frozen T2 labels (identifiers and labels only; the same file v3 hashed) |
| `frozen/mine_t1.py`, `frozen/mine_t1b.py` | the mining |
| `frozen/build_v4.py`, `frozen/states_v4.py` | the raw v3 inputs and the states of each version |
| `frozen/run_t1.py` | the incident PRs, checked the way the Action checks them |
| `frozen/ask.py` | the API at concurrency 1 |
| `frozen/score_v4.py`, `frozen/analysis_v4.py`, `frozen/results_v4.txt` | the analysis as it ran and its output |
| `frozen/dev_states.py`, `frozen/mkreq_dev.py` | the development runs |

All files under `frozen/` are published exactly as they were hashed; none was edited. The scripts expect sibling
folders of the original working directory (`pr_study/`, `real_cases/`, a local PostgreSQL on 127.0.0.1) and read the
study key from `~/.config/ekbasis/study_api_key`; they are there to show what ran, not to run as-is. `PREREG_v4.md`
names its folder as `scratchpad/v4/`, the original working directory.

**Not released:**

* the states and requests (`st/`, `data/items_*`, `req_*`, `dev_new*.jsonl`, the `state` field of the T1 results):
  they contain the statements of third-party migrations. Their sha256 is kept in the answer files;
* the raw answer records' `server_timing` field (internal infrastructure detail); everything else needed is in the
  reduced files;
* the product branch checkouts, virtualenvs, repository clones and run logs.
