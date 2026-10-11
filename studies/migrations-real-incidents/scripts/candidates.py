"""Every candidate examined in detail (step 1 output after reading the diffs and the upstream text).

upstream: what went wrong upstream, as the evidence states it (not what the guard says):
  fails_data   - the migration failed on existing (prod/QA/dogfood) data, not on an empty schema
  fails_schema - the migration fails on the schema itself, with or without rows
  fails_env    - it fails only in some deployments (non-default schema, privileges, PG version)
  loss         - it lost or overwrote data, and that was the reason for the fix/revert
  duration     - it ran too long / held locks on a large table (outside what the guard claims to foresee)
  unknown      - edited or reverted with no stated reason; no incident can be confirmed
evidence: "explicit" (upstream text says what broke) or "inferred" (from the fix diff only).
path: the bad migration as first added; add: the commit that added it (head of the reconstructed PR); fix: the follow-up.
"""

C = [
    # ---------------- cal.com (Prisma)
    dict(id="calcom-user-password", repo="cal.com", gh="calcom/cal.com",
         path="packages/prisma/migrations/20240209223121_adds_user_password/migration.sql", add="7b0d5959cb", fix="f7782b208",
         upstream="fails_data", evidence="explicit",
         links=["https://github.com/calcom/cal.com/pull/13628", "https://github.com/calcom/cal.com/commit/f7782b2080a702a12b2ed712f41cff78f6d32004",
                "https://github.com/calcom/cal.com/pull/13680"],
         note="INSERT INTO \"UserPassword\"(hash NOT NULL) SELECT password FROM users without filtering NULL passwords; fixed by "
              "'fix: hotfix failed migration' (adds WHERE password IS NOT NULL), then the whole feature was reverted (#13680)."),
    dict(id="calcom-bookingref-fk", repo="cal.com", gh="calcom/cal.com",
         path="packages/prisma/migrations/20240924112248_booking_reference_null_credential_on_delete/migration.sql", add="04a0e4642e",
         fix="77af36e2a", upstream="fails_data", evidence="explicit",
         links=["https://github.com/calcom/cal.com/pull/16784", "https://github.com/calcom/cal.com/pull/16798"],
         note="The cleanup UPDATE skipped credentialId = 0 rows, so ADD FOREIGN KEY failed: 'Failed foreign key constraint "
              "check due to daily_video 0' (#16798)."),
    dict(id="calcom-routing-updatedat", repo="cal.com", gh="calcom/cal.com",
         path="packages/prisma/migrations/20250409135411_updated_at_routing_form_response/migration.sql", add="3ee8032538",
         fix="2ab34004a", upstream="fails_data", evidence="explicit",
         links=["https://github.com/calcom/cal.com/pull/20580", "https://github.com/calcom/cal.com/pull/20660"],
         note="ADD COLUMN \"updatedAt\" TIMESTAMP(3) NOT NULL without default on a populated table; #20660: 'Fix migration failing'."),
    dict(id="calcom-backfill-userid", repo="cal.com", gh="calcom/cal.com",
         path="packages/prisma/migrations/20250404225129_backfill_userid_from_user_eventtype/migration.sql", add=None,
         fix="e4c46e338", upstream="fails_data", evidence="explicit",
         links=["https://github.com/calcom/cal.com/pull/20562", "https://github.com/calcom/cal.com/pull/20598"],
         note="Backfill UPDATE of EventType.userId; #20598: 'Reverting due to failed migrations in both QA and Prod': duplicate "
              "key value violates unique constraint \"EventType_userId_slug_key\"."),
    dict(id="calcom-org-metadata", repo="cal.com", gh="calcom/cal.com",
         path="packages/prisma/migrations/20231215054122_organization_metadata/migration.sql", add=None, fix="2408338ed",
         upstream="unknown", evidence="inferred",
         links=["https://github.com/calcom/cal.com/pull/12828", "https://github.com/calcom/cal.com/pull/13700"],
         note="Reverted without a stated reason; the re-land (#13700) 'fixes the migration by removing the unique constraint "
              "[slug, isOrganization] which was unnecessary'. A failure on duplicate slugs is plausible but not stated."),
    dict(id="calcom-avatars-move", repo="cal.com", gh="calcom/cal.com",
         path="packages/prisma/migrations/20240321143215_move_avatars_cols_to_avatar_table/migration.sql", add="4bfbac6649", fix="622160ea1",
         upstream="unknown", evidence="inferred",
         links=["https://github.com/calcom/cal.com/pull/14170", "https://github.com/calcom/cal.com/commit/622160ea17c9311eecb45d0b44564b88f79a356b"],
         note="Reverted with no stated reason (PR #14170 notes 'Requires PostgreSQL 13')."),
    dict(id="calcom-dwd-rename", repo="cal.com", gh="calcom/cal.com",
         path="packages/prisma/migrations/20250304093009_rename_dwd_to_delegation_credentials/migration.sql", add="7a9ddf2194",
         fix="340b5ab06", upstream="unknown", evidence="inferred",
         links=["https://github.com/calcom/cal.com/pull/19703", "https://github.com/calcom/cal.com/pull/19734"],
         note="A rename done by Prisma as DROP TABLE/DROP COLUMN + CREATE; reverted next day with no stated reason."),
    dict(id="calcom-booker-email-notnull", repo="cal.com", gh="calcom/cal.com",
         path="packages/prisma/migrations/20251006111422_add_requires_booker_email_verification/migration.sql", add="64297f027c",
         fix="1aac14056", upstream="unknown", evidence="inferred",
         links=["https://github.com/calcom/cal.com/pull/24298", "https://github.com/calcom/cal.com/commit/1aac14056e2ffe2ffee1089fefd33860a4fe66c6"],
         note="Hotfix turned 'BOOLEAN NOT NULL DEFAULT false' into nullable; no failure is stated (that ADD COLUMN cannot fail on rows)."),
    # ---------------- coder (golang-migrate)
    dict(id="coder-stats-int-overflow", repo="coder", gh="coder/coder",
         path="coderd/database/migrations/000101_workspace_agent_stats_tableify.up.sql", add="05e449943", fix="8850ce0d9",
         upstream="fails_data", evidence="explicit",
         links=["https://github.com/coder/coder/pull/6374", "https://github.com/coder/coder/pull/6380"],
         note="(payload->>'rx_bytes')::integer overflows on real byte counters; #6380: 'This broke dogfood!' (switched to bigint)."),
    dict(id="coder-created-by-notnull", repo="coder", gh="coder/coder",
         path="coderd/database/migrations/000068_update_template_version_created_by.up.sql", add="46e095387", fix="a930cf42b",
         upstream="fails_data", evidence="inferred",
         links=["https://github.com/coder/coder/pull/4800", "https://github.com/coder/coder/pull/4838"],
         note="SET NOT NULL ran before the UPDATE that fills the NULLs (the fix swaps the two statements)."),
    dict(id="coder-created-by-zero-uuid", repo="coder", gh="coder/coder",
         path="coderd/database/migrations/000068_update_template_version_created_by.up.sql", add="a930cf42b", fix="e26bc2072",
         upstream="fails_data", evidence="inferred", version_of="a930cf42b",
         links=["https://github.com/coder/coder/pull/4838", "https://github.com/coder/coder/pull/4850"],
         note="The first fix filled NULLs with the zero UUID; 'actually fix' (#4850) assigns a real user instead. Treated as a "
              "PR that edits an existing migration (the guard sees edits only as a note)."),
    dict(id="coder-deadline-check", repo="coder", gh="coder/coder",
         path="coderd/database/migrations/000356_enforce_deadline_below_max_deadline.up.sql", add="dc598856e", fix="9edca92c7",
         upstream="fails_data", evidence="inferred",
         links=["https://github.com/coder/coder/pull/19203", "https://github.com/coder/coder/pull/19212"],
         note="The pre-constraint UPDATE missed rows with a zero deadline, which the new CHECK rejects; fixed the same day."),
    dict(id="coder-chat-search-update", repo="coder", gh="coder/coder",
         path="coderd/database/migrations/000585_chat_search_english_config.up.sql", add="378ac91b4", fix="7fc9a6e44",
         upstream="duration", evidence="explicit",
         links=["https://github.com/coder/coder/pull/28319", "https://github.com/coder/coder/pull/28552"],
         note="#28552: 'the previously merged migration taking too long on large tables' (a full-table UPDATE)."),
    # ---------------- lemmy (Diesel)
    dict(id="lemmy-username-unique", repo="lemmy", gh="LemmyNet/lemmy",
         path="migrations/2025-07-10-105316_username-instance-unique/up.sql", add="cf0e0211", fix="31dd9719b",
         upstream="fails_data", evidence="explicit",
         links=["https://github.com/LemmyNet/lemmy/pull/5858", "https://github.com/LemmyNet/lemmy/pull/5867"],
         note="DELETE of duplicates skipped local users, then ADD UNIQUE(name, instance_id) failed: 'failed with lemmy.ml prod "
              "data' (#5867). The fixed migration deletes 77 rows (deliberate loss)."),
    dict(id="lemmy-local-image-person", repo="lemmy", gh="LemmyNet/lemmy",
         path="migrations/2025-05-06-145536_local_image_person/up.sql", add="68008a0e", fix="9a84180b5",
         upstream="fails_data", evidence="explicit",
         links=["https://github.com/LemmyNet/lemmy/pull/5664", "https://github.com/LemmyNet/lemmy/pull/5799"],
         note="ADD COLUMN person_id int NOT NULL DEFAULT 0 REFERENCES person: 'fails with lemmy.ml database ... violates foreign "
              "key constraint local_image_person_id_fkey' (#5799)."),
    dict(id="lemmy-warn-check", repo="lemmy", gh="LemmyNet/lemmy",
         path="migrations/2026-02-03-235249-0000_add_moderator_warn_constraint_check/up.sql", add="9f39a4bb", fix="90fc5cca",
         upstream="fails_data", evidence="explicit",
         links=["https://github.com/LemmyNet/lemmy/pull/6315", "https://github.com/LemmyNet/lemmy/pull/6462"],
         note="A new modlog CHECK constraint: 'This failed on lemmy.ml prod data' (#6462)."),
    dict(id="lemmy-person-content-unique", repo="lemmy", gh="LemmyNet/lemmy",
         path="migrations/2024-12-05-233704_add_person_content_combined_table/up.sql", add="0bfbd74e", fix="b901714d7",
         upstream="fails_data", evidence="explicit",
         links=["https://github.com/LemmyNet/lemmy/pull/5251", "https://github.com/LemmyNet/lemmy/pull/5324"],
         note="UNIQUE(post_id) on person_saved_combined while back-filling saves of many people: 'duplicate key value violates "
              "unique constraint person_saved_combined_post_id_key' with production data (#5324)."),
    dict(id="lemmy-aggregates-deferred", repo="lemmy", gh="LemmyNet/lemmy",
         path="migrations/2025-03-04-105516_remove-aggregate-tables/up.sql", add="9a64902a", fix="3664f987d",
         upstream="fails_data", evidence="explicit",
         links=["https://github.com/LemmyNet/lemmy/pull/5533"],
         note="CREATE INDEX / ALTER COLUMN after updates on tables with DEFERRABLE INITIALLY DEFERRED FKs 'otherwise fail because "
              "of pending trigger events' (#5533); only happens when rows were updated."),
    dict(id="lemmy-merge-modlog", repo="lemmy", gh="LemmyNet/lemmy",
         path="migrations/2025-10-15-114811-0000_merge-modlog-tables/up.sql", add="6566caab", fix="c6ec85ea7",
         upstream="unknown", evidence="inferred",
         links=["https://github.com/LemmyNet/lemmy/pull/6054", "https://github.com/LemmyNet/lemmy/pull/6146"],
         note="'Fixes for merge modlog migration': wrong column mappings in the copy into the merged table; no failure stated."),
    # ---------------- formbricks (Prisma)
    dict(id="formbricks-display-fk", repo="formbricks", gh="formbricks/formbricks",
         path="packages/database/migrations/20240815084351_adds_relation_between_display_and_response/migration.sql",
         add="2c453bd49", fix="89a2e26f2", upstream="fails_data", evidence="explicit",
         links=["https://github.com/formbricks/formbricks/pull/2986", "https://github.com/formbricks/formbricks/pull/3015"],
         note="ADD FOREIGN KEY Display.responseId -> Response.id; removed as 'failing prisma migration' (#3015) the same day."),
    dict(id="formbricks-thankyou-dup", repo="formbricks", gh="formbricks/formbricks",
         path="packages/database/prisma/migrations/20230407135127_add_thank_you_card/migration.sql", add="48bac2128",
         fix="fbc1c7404", upstream="fails_schema", evidence="inferred",
         links=["https://github.com/formbricks/formbricks/pull/243", "https://github.com/formbricks/formbricks/commit/fbc1c7404"],
         note="Adds Survey.thankYouCard, which an earlier migration (#222) had already added; 'fix migrations' removed the line."),
    # ---------------- documenso (Prisma)
    dict(id="documenso-template-token", repo="documenso", gh="documenso/documenso",
         path="packages/prisma/migrations/20231214081915_remove_template_token_column/migration.sql", add="32633f96",
         fix="eb84d7ff", upstream="unknown", evidence="inferred",
         links=["https://github.com/documenso/documenso/pull/506", "https://github.com/documenso/documenso/commit/eb84d7ff"],
         note="DROP COLUMN Recipient.templateToken removed as 'invalid migration' the next day; no reason given."),
    dict(id="documenso-rework-sessions", repo="documenso", gh="documenso/documenso",
         path="packages/prisma/migrations/20250212125902_rework_sessions/migration.sql", add="383b5f78", fix="79e26a9a4",
         upstream="unknown", evidence="inferred",
         links=["https://github.com/documenso/documenso/commit/79e26a9a4"],
         note="Drops Session.expires and adds NOT NULL columns without default; removed ('fix: remove session migration') "
              "before a release; no failure stated."),
    # ---------------- langfuse (Prisma)
    dict(id="langfuse-public-schema", repo="langfuse", gh="langfuse/langfuse",
         path="packages/shared/prisma/migrations/20240530212419_model_price_anthropic_via_google_vertex/migration.sql",
         add="196dc1bf0", fix="46b19279c", upstream="fails_env", evidence="explicit",
         links=["https://github.com/langfuse/langfuse/issues/2266", "https://github.com/langfuse/langfuse/pull/2329"],
         note="Hard-coded \"public\".\"models\": fails for self-hosters on another schema (relation \"public.models\" does not exist)."),
    dict(id="langfuse-dashboard-resize", repo="langfuse", gh="langfuse/langfuse",
         path="packages/shared/prisma/migrations/20250519145128_resize_dashboard_y_axis_components/migration.sql",
         add="5ab8e4219", fix="09f3343db", upstream="fails_data", evidence="inferred",
         links=["https://github.com/langfuse/langfuse/pull/6891", "https://github.com/langfuse/langfuse/pull/6918"],
         note="jsonb rewrite of dashboards.definition mishandled an empty widgets array (#6918 'handle empty widget list "
              "correctly'); failure mode not stated."),
    dict(id="langfuse-historic-model-update", repo="langfuse", gh="langfuse/langfuse",
         path="packages/shared/prisma/migrations/20240423174014_update_internal_models/migration.sql", add="7c72aa16c",
         fix="dec0c5133", upstream="loss", evidence="inferred",
         links=["https://github.com/langfuse/langfuse/pull/1808", "https://github.com/langfuse/langfuse/pull/1817"],
         note="UPDATE observations SET internal_model = ... overwrote historic values; reverted as 'bug: revert historic "
              "model update' (#1817) hours later."),
    # ---------------- vaultwarden (Diesel, PostgreSQL folder)
    dict(id="vaultwarden-device-type", repo="vaultwarden", gh="dani-garcia/vaultwarden",
         path="migrations/postgresql/2024-09-04-091351_use_device_type_for_mails/up.sql", add="21efc08", fix="de0111108",
         upstream="fails_data", evidence="explicit",
         links=["https://github.com/dani-garcia/vaultwarden/pull/4916", "https://github.com/dani-garcia/vaultwarden/pull/4971"],
         note="ADD COLUMN device_type INTEGER NOT NULL without default: 'If the table contains values it will fail' (#4971)."),
    dict(id="vaultwarden-datetime", repo="vaultwarden", gh="dani-garcia/vaultwarden",
         path="migrations/postgresql/2021-10-24-164321_add_2fa_incomplete/up.sql", add="c476e19", fix="6ae48aa8c",
         upstream="fails_schema", evidence="explicit",
         links=["https://github.com/dani-garcia/vaultwarden/pull/2080", "https://github.com/dani-garcia/vaultwarden/issues/2079"],
         note="Used DATETIME (not a PostgreSQL type); #2080 'should have used TIMESTAMP', fixes issue #2079."),
    # ---------------- supabase/auth (golang-migrate-style .up.sql)
    dict(id="auth-unique-token-idx", repo="auth", gh="supabase/auth",
         path="migrations/20220412150300_add_unique_idx.up.sql", add="c64f331", fix="60a7a6fab",
         upstream="fails_data", evidence="explicit",
         links=["https://github.com/supabase/auth/pull/446", "https://github.com/supabase/auth/pull/460"],
         note="Partial UNIQUE indexes on token columns; #460: 'unique partial index created fails' for phone OTPs, which may repeat."),
    dict(id="auth-alter-role", repo="auth", gh="supabase/auth",
         path="migrations/20220320143831_set_idle_transaction_timeout.up.sql", add="9489d7e", fix="17587e534",
         upstream="fails_env", evidence="explicit",
         links=["https://github.com/supabase/auth/pull/418", "https://github.com/supabase/auth/pull/428"],
         note="ALTER ROLE current_user SET ...: 'remove migration that requires elevated privileges' (#428)."),
    # ---------------- rallly (Prisma)
    dict(id="rallly-enum-same-tx", repo="rallly", gh="lukevella/rallly",
         path="packages/database/prisma/migrations/20250221160003_set_subscription_status_enum/migration.sql", add="ba613e3f",
         fix="460e88086", upstream="fails_data", evidence="inferred",
         links=["https://github.com/lukevella/rallly/pull/1572", "https://github.com/lukevella/rallly/pull/1574"],
         note="ALTER TYPE ... ADD VALUE and use of the new values in the same transaction (unsafe use of new enum value, raised "
              "only when a row actually takes a new value: class corrected from fails_schema to fails_data after reading the "
              "PostgreSQL rule; corrected AFTER the run, and the outcome is 'missed' under either class); "
              "'Fix migration' commits the ADD VALUEs first."),
    # ---------------- mattermost (golang-migrate)
    dict(id="mattermost-attribute-view", repo="mattermost", gh="mattermost/mattermost",
         path="server/channels/db/migrations/postgres/000136_create_attribute_view.up.sql", add="a344b3225b", fix="1cf2f0810",
         upstream="fails_data", evidence="explicit",
         links=["https://github.com/mattermost/mattermost/pull/30785", "https://github.com/mattermost/mattermost/pull/31225"],
         note="Materialized view over property values assumed multiselect values are arrays; failed while 'trying to update "
              "a QA test server' (#31225)."),
    dict(id="mattermost-posts-lock", repo="mattermost", gh="mattermost/mattermost",
         path="server/channels/db/migrations/postgres/000217_resize_message_columns.up.sql", add="b3c66c7d17", fix="e49664194",
         upstream="duration", evidence="explicit",
         links=["https://github.com/mattermost/mattermost/pull/37300", "https://github.com/mattermost/mattermost/pull/38815"],
         note="Widening posts.message rebuilt a GIN expression index under ACCESS EXCLUSIVE: ~10 min on 12M rows (#38815)."),
    # ---------------- hatchet (goose files: Up and Down in one file)
    dict(id="hatchet-limits-overflow", repo="hatchet", gh="hatchet-dev/hatchet",
         path="cmd/hatchet-migrate/migrate/migrations/20250323220955_v1_0_8.sql", add="c54bf9266", fix="bc790dbdb",
         upstream="fails_data", evidence="inferred",
         links=["https://github.com/hatchet-dev/hatchet/pull/1388", "https://github.com/hatchet-dev/hatchet/pull/1395"],
         note="limitValue * 1000 overflows integer and the INSERT had no ON CONFLICT on (tenantId, resource); 'fix: migration' "
              "(#1395) adds least(..., 2147483647) and ON CONFLICT DO NOTHING."),
]
