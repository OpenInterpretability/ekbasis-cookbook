# Deviations

1. **s58 (test) down label rests on one run, not a median of three.** Its first run's longest gap was 2.81 s (inside
   the [1.0, 4.0] s repeat band), but both repeats errored in v1 setup: the other labelling worker had a grafana
   release with the same cluster-scoped ClusterRole name installed at that moment. With one run the gap (2.81 s) is
   outside the grey zone, so the label is down = true. Both Ekbasis and R2 say no on s58, so the composite comparison
   does not change if s58 is excluded.
2. s53 and s55 (test) were re-run alone for the same collision, before the PREREG seal (logged in DEVLOG).
3. Question field: guard.QUESTIONS uses `ekbasis.prompts.yes_no` (`instructions`), as required.
