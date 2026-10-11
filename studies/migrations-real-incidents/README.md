# Real incidents: the Ekbasis migration guard (client 0.1.12) against public incidents

*Run 2026-10-10 on the hosted API (Ekbasis-27B-INT4), concurrency 1. Not pre-registered: the candidates, their class
and their evidence were fixed before the guard ran (one exception, marked below). Nobody upstream was contacted.*

**Result in one line:** of 25 confirmed in-scope incidents (failure or loss), the guard flagged 15 as risky, but only
**9 for the right reason**; it declined 2 (cannot foresee) and **missed 8**.

## Method, in one screen

1. **Mining** (`scripts/mine.py`). 16 repositories cloned with `--filter=blob:none`:
   * the 11 of the [migrations study](../migrations/) whose layout the product discovers: cal.com, langfuse,
     trigger.dev, documenso, formbricks, hoppscotch, umami, lemmy, crates.io, vaultwarden and mattermost;
   * plus coder, supabase/auth, papermark, rallly and hatchet.

   kratos was left out for the same reason as in v3: the product does not discover the pop layout. 1,045
   first-parent commits touch PostgreSQL migrations with some signal (a message with revert/hotfix/fix/fail/constraint…,
   an edit or deletion of an existing migration, a migration name with fix/backfill). 332 of them had a strong signal
   and were listed. We read the diff and, where there was one, the PR or issue text of about 60 of them (GitHub API:
   ~35 calls). **34 became candidates** (`scripts/candidates.py`) and **29 were screened out with a reason**
   (`scripts/screened.py`). Examples of screening out: renumbering of a duplicate migration, idempotency for re-runs,
   product behaviour. The class and evidence of the upstream problem were fixed before the guard ran. One exception
   was corrected afterwards and is marked (rallly).
2. **Rebuilding the PR** (`scripts/run_cases.py`).
   * head = the commit that added the bad migration; base = its first parent.
   * For the state with statistics we built a replica: the base's migrations, in order and with the guard's fallback,
     then the study's seeder (20 rows per table, NULL with p = 0.25, FKs to seeded parents) and ANALYZE.
   * `ekbasis migrate-check --base B --head H --json` ran twice, against the hosted API, with the study key and
     concurrency 1:
     * with `--stats-url` pointing at the replica (primary arm);
     * without a replica, which is the Action's default.
   * `--glob` was restricted to the repository's PostgreSQL folder. That is the configuration a user would set;
     without it, vaultwarden would send its mysql and sqlite folders to PostgreSQL.
   * The study's regex baselines R3 and F1 also ran on the head file, plus a synthetic label: the file executed on the
     seeded replica.
3. **Classification** (`scripts/table.py`). The categories are:
   * `caught`: risky for the right reason (failure → schema/fails; loss → loses).
   * `caught_wrong_why`: risky for another reason.
   * `flagged_spurious`: risky for a reason that would not hold in production.
   * `cannot_foresee`: fail closed.
   * `missed`: the guard answered ok.
   * `out_of_scope`: the problem was duration or locking.
   * `n/a`: no confirmable incident upstream.

## Result (34 candidates)

| | Guard with statistics | Guard without replica | Regex R3/F1 |
|---|---|---|---|
| caught | **9** | 9 | 13 |
| caught_wrong_why | 5 | 6 | 3 |
| flagged_spurious | 1 | 1 | 0 |
| cannot_foresee | 2 | 2 | — |
| missed | **8** | 7 | 9 |
| out_of_scope (duration/lock) | 2 | 2 | 2 |
| n/a (no confirmed incident) | 7 | 7 | 7 |

**Base: 25 confirmed incidents within scope** (failure or loss).

* The guard flagged 15 of 25 as risky: 9 for the right reason, 5 for another reason and 1 for a spurious reason. It
  declined 2 (cannot foresee) and let 8 through.
* Of the 9 hits, 3 come from the code probe (the file fails on the base schema) and 6 come from the model.
* The regex catches more (16 of 25 flagged, 13 for the right reason). But it is the same F1 that in v3 raised a **false
  alarm on 43% of benign migrations**. There are no benign migrations here, so the false-alarm rate is not measured.

## Cases (the best ones, and the errors that teach)

### 1. cal.com, `adds_user_password`: "fix: hotfix failed migration" (caught)
* **Upstream.** [#13628](https://github.com/calcom/cal.com/pull/13628) moves passwords to the `UserPassword` table
  (`hash TEXT NOT NULL`) with `INSERT ... SELECT u."password" FROM users u`. Users without a password (OAuth/SAML)
  have a NULL `password`.
* **Fix.** In [hotfix f7782b2](https://github.com/calcom/cal.com/commit/f7782b2080a702a12b2ed712f41cff78f6d32004),
  which adds `WHERE u."password" IS NOT NULL`. The whole feature was reverted the next day
  ([#13680](https://github.com/calcom/cal.com/pull/13680)).
* **Guard.** **risky**: "may fail on existing data (97%); nothing in the file would be applied". Without the replica,
  92%. The F1 regex also flags it, but only because there is a `CREATE UNIQUE INDEX` in the file.

### 2. lemmy, `local_image_person`: failed on lemmy.ml's data (caught)
* **Upstream.** `ADD COLUMN person_id int NOT NULL DEFAULT 0 REFERENCES person`. There is no person 0, and
  [#5799](https://github.com/LemmyNet/lemmy/pull/5799) quotes the production error: `violates foreign key constraint
  "local_image_person_id_fkey"`.
* **Guard.** With the replica, **risky**: "may fail on existing data (89%) ... if it ran, it would also lose data
  (94%)". The half about loss is noise.
* **Without the replica,** it flagged only for loss (caught_wrong_why).
* **The regex does not catch it:** the NOT NULL has a DEFAULT, and F1 does not look at an FK on a new column.

### 3. vaultwarden, `add_2fa_incomplete`: `DATETIME` on PostgreSQL (caught in code, no model)
* **Upstream.** The PostgreSQL file used `DATETIME`. Fixed in [#2080](https://github.com/dani-garcia/vaultwarden/pull/2080),
  which closes issue [#2079](https://github.com/dani-garcia/vaultwarden/issues/2079).
* **Guard.** The probe on the base schema fails (`type "datetime" does not exist`), which becomes **risky** as "an
  error of the PR itself". The regex does not catch it.
* **Other cases of the same class:**
  * formbricks' `20230407135127_add_thank_you_card`, which adds a column another migration already created;
  * vaultwarden's `use_device_type_for_mails` ([#4971](https://github.com/dani-garcia/vaultwarden/pull/4971)), which
    had backticks that PostgreSQL rejects, even before the NOT NULL without DEFAULT problem described in the PR.

### 4. cal.com, backfill of `EventType.userId`: failed in QA and production (missed)
* **Upstream.** [#20598](https://github.com/calcom/cal.com/pull/20598) says: "Reverting due to failed migrations in
  both QA and Prod". The error was `duplicate key value violates unique constraint "EventType_userId_slug_key"`.
* **Guard.** **ok**, with P(fail) of 16% (with replica) and 9% (without). The regex does not catch it either.
* **Why it missed.** Predicting the collision requires knowing that the same slug exists for the owner through the
  join table. No aggregate statistic says that.

### 5. lemmy, the modlog CHECK: "This failed on lemmy.ml prod data" (missed)
* **Upstream.** [#6462](https://github.com/LemmyNet/lemmy/pull/6462) redoes a CHECK constraint that old rows violated.
  In general, new CHECK/UNIQUE/FK constraints that depend on the shape of historical rows were the main source of the
  guard's errors:
  * lemmy-warn-check;
  * lemmy-person-content-unique ([#5324](https://github.com/LemmyNet/lemmy/pull/5324));
  * formbricks-display-fk ([#3015](https://github.com/formbricks/formbricks/pull/3015));
  * calcom-backfill-userid.
* **The synthetic label contradicts the guard's "ok".** On the seeded replica, four of these files **do fail**:
  lemmy-warn-check, lemmy-person-content-unique, formbricks-display-fk and rallly. The guard still said ok.

### 6. lemmy, `username-instance-unique`: the synthetic statistics got in the way (missed with replica, caught without)
* **Upstream.** The `DELETE` of duplicates skipped local users, and the `ADD UNIQUE(name, instance_id)` failed on
  production data ([#5867](https://github.com/LemmyNet/lemmy/pull/5867); the fix deleted 77 rows).
* **Guard.**
  * With the synthetic replica, **ok** (P(fail) of 5%).
  * Without the replica, **risky** (fail 80%, loss 86%).
* **Why.** The seeded replica says "all values distinct", which is true of the synthetic data and false in production.
  The study replica's statistics can hide exactly the uniqueness risk.

### 7. hatchet, `v1_0_8`: flagged for the wrong reason (spurious)
* **Upstream.** `"limitValue" * 1000` overflows `integer` and `ON CONFLICT` is missing.
  [#1395](https://github.com/hatchet-dev/hatchet/pull/1395) changes it to `least(... ::bigint * 1000, 2147483647)` and
  adds `ON CONFLICT DO NOTHING`.
* **Guard.** Said "risky" because the probe ran the file in a transaction and got `unsafe use of new value`.
* **Why it is spurious.** The file starts with `-- +goose NO TRANSACTION`, so that error would not occur in
  production. Also, the guard executed the `-- +goose Down` section too, because comments are stripped. goose files are
  not really supported.

### 8. coder, agent statistics: "This broke dogfood!" (wrong reason)
* **Upstream.** `(payload ->> 'rx_bytes')::integer` overflows with real counters
  ([#6380](https://github.com/coder/coder/pull/6380)).
* **Guard.** **risky** for *loss* (97%), not for failure. The alarm would reach the reviewer, but the explanation
  points elsewhere. The same pattern appears in coder-deadline-check and calcom-bookingref-fk: the real failure was the
  new constraint or FK, and the guard pointed at the UPDATE before it.

## Full table

The whole table, with every field, is in `table.jsonl`: 34 candidates plus 29 screened out with a reason. The summary
of each candidate is in `table_summary.txt`.

| id | upstream problem | evidence | guard (with replica) | P(loss)/P(fail) | outcome | without replica | regex |
|---|---|---|---|---|---|---|---|
| calcom-user-password | data failure | explicit | fails | 0.04 / 0.97 | caught | caught | caught |
| calcom-bookingref-fk | data failure | explicit | loses | 0.95 / 0.06 | wrong why | wrong why | caught |
| calcom-routing-updatedat | data failure | explicit | fails | 0.00 / 0.99 | caught | caught | caught |
| calcom-backfill-userid | data failure | explicit | ok | 0.01 / 0.16 | **missed** | missed | missed |
| calcom-org-metadata | unknown | inferred | fails | 0.01 / 0.80 | n/a | n/a | n/a |
| calcom-avatars-move | unknown | inferred | ok | 0.01 / 0.04 | n/a | n/a | n/a |
| calcom-dwd-rename | unknown | inferred | fails | 0.98 / 0.68 | n/a | n/a | n/a |
| calcom-booker-email-notnull | unknown | inferred | ok | 0.00 / 0.01 | n/a | n/a | n/a |
| coder-stats-int-overflow | data failure | explicit | loses | 0.97 / 0.16 | wrong why | wrong why | missed |
| coder-created-by-notnull | data failure | inferred | fails | 0.87 / 0.98 | caught | caught | caught |
| coder-created-by-zero-uuid | data failure | inferred | (edit note only) | — | **missed** | missed | caught* |
| coder-deadline-check | data failure | inferred | loses | 0.85 / 0.01 | wrong why | wrong why | caught |
| coder-chat-search-update | duration | explicit | ok | 0.00 / 0.01 | out of scope | out of scope | out of scope |
| lemmy-username-unique | data failure | explicit | ok | 0.02 / 0.05 | **missed** | caught | caught |
| lemmy-local-image-person | data failure | explicit | fails | 0.94 / 0.89 | caught | wrong why | missed |
| lemmy-warn-check | data failure | explicit | ok | 0.00 / 0.04 | **missed** | missed | caught |
| lemmy-person-content-unique | data failure | explicit | ok | 0.00 / 0.11 | **missed** | missed | missed |
| lemmy-aggregates-deferred | data failure | explicit | ok | 0.35 / 0.07 | **missed** | missed | missed |
| lemmy-merge-modlog | unknown | inferred | fails | 0.89 / 0.94 | n/a | n/a | n/a |
| formbricks-display-fk | data failure | explicit | ok | 0.00 / 0.05 | **missed** | missed | caught |
| formbricks-thankyou-dup | schema failure | inferred | schema | — | caught | caught | missed |
| documenso-template-token | unknown | inferred | schema | — | n/a† | n/a | n/a |
| documenso-rework-sessions | unknown | inferred | fails | 0.98 / 0.95 | n/a | n/a | n/a |
| langfuse-public-schema | environment | explicit | loses | 0.95 / 0.01 | wrong why | wrong why | wrong why |
| langfuse-dashboard-resize | data failure | inferred | loses | 0.97 / 0.16 | wrong why | wrong why | wrong why |
| langfuse-historic-model-update | loss | inferred | loses | 0.93 / 0.00 | caught | caught | caught |
| vaultwarden-device-type | data failure | explicit | schema (backticks) | — | caught | caught | caught |
| vaultwarden-datetime | schema failure | explicit | schema | — | caught | caught | missed |
| auth-unique-token-idx | data failure | explicit | cannot foresee | — | cannot foresee | cannot foresee | caught |
| auth-alter-role | environment (privilege) | explicit | cannot foresee | — | cannot foresee | cannot foresee | missed |
| rallly-enum-same-tx | data failure‡ | inferred | ok | 0.01 / 0.08 | **missed** | missed | caught |
| mattermost-attribute-view | data failure | explicit | fails | 0.01 / 0.93 | caught | caught | missed |
| mattermost-posts-lock | duration/lock | explicit | ok | 0.00 / 0.01 | out of scope | out of scope | out of scope |
| hatchet-limits-overflow | data failure | inferred | schema | — | spurious | spurious | wrong why |

Table notes:

* \* In coder-created-by-zero-uuid the PR **edits** an existing migration. The guard only emits the edit note and does
  not judge the content. The regex was applied to the file, which the Action would not do.
* † In documenso-template-token the probe shows the column did not exist at the base: `column "templateToken" ... does
  not exist`. That plausibly explains the "remove invalid migration", but upstream stated no reason, so the case stays
  out of the count.
* ‡ rallly was first classified as "schema failure". The class was corrected **after** the run: the error "unsafe use
  of new value" only appears when a row gets the new value. The outcome is "missed" under both classes.

## Product findings, in passing

1. **`NO_TX` fires on a `BEGIN` inside a `$$` body.** The regex uses `^\s*BEGIN` with `re.M` and matches the `BEGIN`
   of `DO $$`/`PROCEDURE` blocks.
   * Files that run in one transaction were evaluated with autocommit rules in mattermost-attribute-view and
     mattermost-posts-lock. In coder-created-by-notnull the `BEGIN` is real, and there the autocommit mode is right.
   * In those cases the reason says "the statements that do not fail stay applied", which is wrong for golang-migrate.
2. **goose is not supported.** The guard ignores `-- +goose NO TRANSACTION` and runs the Down section together with
   the Up.
3. **Schemas created outside the migrations become cannot foresee on every PR.** That is the case of supabase/auth,
   which needs the `auth` schema and the `supabase_auth_admin` role. The guard fails closed, which is correct, but it is
   useless without a setup script.
4. **Editing an existing migration only produces a note.** Two incidents (coder 000068 and cal.com user_password) were
   fixed by editing the file.
5. **lemmy has migrations that fail without a superuser or without Diesel's table** (`forbid_diesel_cli`). Because of
   that, the guard warns that the schema "may be incomplete" on almost every lemmy PR.

## Caveats

* **Sample.** n = 25 in-scope incidents, not randomly sampled: they are the ones that left a trace in commits and PRs.
  Incidents never written into Git do not show up.
* **Selection bias.** The selection favours loud failures, which produce hotfixes. Silent losses rarely become a
  commit, so there is only 1 case of pure loss.
* **Evidence.** In 8 of the 25 the evidence is inferred from the fix's diff, with no text describing the failure.
* **Synthetic replica.** The synthetic replica does not represent production: all values distinct, no sentinel values
  (0, zero date) and no orphan rows. A user with a real replica would give a different state. The arm without a
  replica is the Action's default.
* **Model answers.** One answer per case and per arm, no repetition; run-to-run variation was not measured.
* **Regex.** The regex "catches" more, but there are no benign migrations here to measure its cost, and in v3 it
  flagged 43% of benign ones. This comparison does not decide between the two.
* **Exclusions.** The duration or lock cases (2) are outside what the guard promises and count neither as hits nor as
  errors.

## Files

| File | What it is |
|---|---|
| `table.jsonl` | one line per candidate (34): repo, upstream path, PR base/head commits, fix commit, upstream class, evidence, public links, a one-line description, the guard's verdict kind, reason and P(loss)/P(fail) with and without the replica, the regex flags, the synthetic label (error messages only) and the outcome; then the 29 screened-out commits with the reason |
| `table_summary.txt` | the summary printed by `scripts/table.py` when the table was built |
| `recompute.py` | re-derives every outcome in `table.jsonl` from the upstream class and the verdicts, and prints the summary (standard library, under a second) |
| `recompute_output.txt` | its output. **It matches `table_summary.txt` line for line, and every re-derived outcome equals the stored one** |
| `mined.json` | the 1,045 mined commits (repo, sha, parent, date, subject, migration paths added/modified/deleted, signals); metadata only |
| `scripts/` | the scripts as they ran: `mine.py`, `find_dirs.py` (layout check), `candidates.py`, `screened.py`, `run_cases.py`, `table.py` |

Not released:

* `results/*.json`, the full per-candidate records of `run_cases.py`. They include the state sent to the model, which
  holds the upstream projects' schema and statements (third-party code). Every field the analysis uses from them is in
  `table.jsonl`.
* The clones, the local PostgreSQL data directory, the virtualenv and the run log.

Rerunning `scripts/run_cases.py` needs the clones (re-created by cloning the 16 repositories), a local PostgreSQL 16,
the frozen study helpers `pgexec.py` and `rules.py` from [`../migrations/frozen/`](../migrations/frozen/) on the import
path, `pip install ekbasis==0.1.12`, and `EKBASIS_API_KEY` in the environment. `scripts/table.py` expects `results/`
next to it. **Sanitized for publication:** in `scripts/run_cases.py` the API key is read from `EKBASIS_API_KEY` (the run
read it from a local key file) and `psql` from `EKBASIS_PSQL` (the run used a local absolute path); nothing else
changed. No script in this study was pre-registered, so no sealed hash is affected.
