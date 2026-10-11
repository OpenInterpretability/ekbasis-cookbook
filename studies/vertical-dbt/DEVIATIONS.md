# Deviations

1. **2026-10-11 ~13:05 UTC, dev only.** The first dev pass (54 jsd items, `dev/answers_v1_INVALID_question_field.jsonl`)
   sent the question text under the key `question`; the API reads `instructions`, so every question of a request got
   the same probability (a control question "Is the sky green?" scored like the others). The pass is void and is not
   analyzed. Fixed in `code/statebuild.py` (key renamed, wording unchanged).
2. **Dev, after the v2 pass on jsd (117 items).** Two dbt notes in the rules paragraph corrected to match dbt's
   documented behavior, which the dev labels also showed: `on_schema_change: ignore` errors when the query loses a
   column the table has (v2 wording implied it was harmless; Ekbasis gave p_fails 0.02–0.03 to 4 items that failed);
   an ephemeral model leaves the existing relation in place. No other change. Dev v3 = jsd + attr with this builder.
3. **Dev, after v3 (jsd + attr, 224 items).** (a) Bug: attribution-playbook sets `quoting: false`, so its compiled SQL
   names the throwaway compile database as `compile.main.x` unquoted and the normalization (quoted form only) missed
   it; the diff then showed a database change in every attr item. Fixed by a regex for both forms. (b) The v3
   `on_schema_change` note made Ekbasis predict errors for `append_new_columns` / `sync_all_columns` too (jsd fails F1
   0.667 → 0.579); the note now states each option's documented behavior for a missing column. v4 = jsd + attr again.
4. **Ekbasis restart window 12:47–12:52 UTC (notice from the lead).** No call of this study fell in it: the PREREG was
   hashed at 12:53 UTC and the first call came after it. Test pass: 192 requests, 0 errors, 0 retries; dev v4: 219
   answers for 219 items with a state. Nothing to redo.
