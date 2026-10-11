# Addendum: freeze before the test requests

Written 11 out 2026 18:14 UTC, after the dev requests and before any test request.

Dev phase: 36 requests (answers_dev.jsonl), then one change and 36 more (answers_dev_v2.jsonl):
- `common.facts_lines` gained one code fact: when a BEGIN is not ended by a later COMMIT/ROLLBACK, the state says the
  transaction stays open holding its locks (session mode) or is rolled back when psql disconnects (other modes). It
  applies to 3 scenarios (D07, D08, D14). It moved D14's lock answer from 0.095 to 0.182 (still a miss); dev metrics
  otherwise unchanged (Ekbasis F1 0.780 vs linter 0.296; AUROC 0.873 -> 0.879).
- Questions, threshold, labels, split and analysis unchanged. The test run uses this state layout.

Frozen hashes (sha256):
3a71d19b1ac8af19133c09d95951235e4bc5c3e83680e7601359a285c6195b6e  common.py
12e25f08b94394a79942a07b1288d3c026b22110c8837fbc96228d52d6d9f12c  calls.py
71cab0a720216abbf23ddebc51520579303a9e02492f9875476882fc5eff8f54  analyze.py
ea5a4d1a3fb7c5b7c59dd01d51954a473088d1b194cbef6fe13fa1355b4cb239  labels.jsonl
f9c8608401bffdd89dbcbe81ae2b379ef1e7a467eb0a368a50cba26e0678e34d  facts.jsonl
dde740928b7d8527f669a1399e71bf39fb4fe04274a4cc6ac83fb03115509ad7  split.json
58ccfd1caeac198f00779acac73f2b8efc9f1d798356722b46ec485a3dc36a1a  scenarios.py
