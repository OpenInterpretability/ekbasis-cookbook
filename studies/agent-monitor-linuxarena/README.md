# Ekbasis as a monitor of a misaligned agent (LinuxArena, pre-registered)

**Question.** An AI agent works on a real Linux software system, and in some runs it also pursues a hidden harmful
goal: exfiltrate a secret, plant malware, open remote code execution. A cheaper trusted model checks every action
before it runs. Does Ekbasis, trained only on what well-meant actions do and never on sabotage, catch the attacks?
Every earlier Ekbasis study was about unintended harm; this is the first with an adversary. We predicted it would
lose to an LLM monitor. It did not.

**Data.** The LinuxArena public mirror, reviewer sample (`anonymouslinuxarena/linuxarena-public`, `data/sample.jsonl`,
CC-BY-4.0, SHA-256 in `SEAL.txt`), which ships every action of every trajectory with the scores of the benchmark's own
monitors (GPT-5 Nano, Claude Opus). Ekbasis never saw it in training. Thanks to the LinuxArena authors.

**What Ekbasis read, per action.** The user's task (the main task) at the top, the environment description, the last
5 actions (tool and arguments) and the action about to run. Never the agent's reasoning, the tool outputs or the
hidden goal. Seven yes/no questions in one request; the action's score is the highest probability of "yes". The
three that did the work are now in the client: `ekbasis.monitor()` (0.1.39; TypeScript 0.2.4), worded identically.

**Metric.** The standard AI-control audit budget: the threshold is set on honest actions so that a share b of them is
flagged; an attack trajectory is caught if any of its actions is flagged before it ends. b = 1% is the main budget.

## Results (pre-registered; hashes in `SEAL.txt` re-checked before the analysis)

| Catch rate at a 1% audit budget | Ekbasis | GPT-5 Nano | Claude Opus | action length (control) |
|---|---|---|---|---|
| 59 successful attacks by a Claude Haiku agent | **0.949** [0.881, 1.000] | 0.749 | — | 0.169 |
| all 92 attack runs | **0.815** [0.728, 0.891] | 0.665 | — | 0.141 |
| 74 hand-made sabotage trajectories | 0.497 [0.370, 0.622] | 0.030 | **0.785** | **0.824** |

95% bootstrap intervals over trajectories. Thresholds from 200 honest trajectories (12,494 actions).

- **Ekbasis alone vs GPT-5 Nano: +0.200 [+0.081, +0.323]** (the pre-registered test was non-inferiority within 10
  points; it passed, and our prediction that it would fail was wrong). At a 0.1% budget: 0.764 vs 0.543.
  Trajectory AUROC 0.934 vs 0.856.
- **Ekbasis next to Nano** (each at half the budget, so the total stays at 1%) catches **+0.196 [+0.094, +0.304]**
  more than Nano alone.
- **It beats the length control by +0.780.**
- **Hand-made sabotage:** far above Nano but below Opus and **below the length control**, so we claim nothing there.
- **The questions matter:** the security and sabotage questions alone catch 0.932; the four generic harm presets
  (`harms()`) alone 0.395.

## Checks after the results were seen
- **Leak:** 13 attack actions contain words like "side task" or "malicious"; without them Ekbasis still catches 55/59.
- **What it flags:** off-task code (a new watchdog calling `execSync`, `GRANT ALL PRIVILEGES`, edits to backup code).
  The highest false alarms on honest runs are genuinely risky actions (`DELETE FROM stories`).
- **Agent-style confound (addendum E1, sealed before it ran).** In the dataset's pairing, honest runs come from Opus
  and attacks from Haiku. With thresholds from 200 honest runs of **Haiku itself** (14,570 actions), Ekbasis still
  catches **0.915 [0.847, 0.983]** at 1% (the reading fixed in advance: ≥ 0.80 means the signal is not mainly agent
  style). AUROC 0.910.
- **Hardware:** every score comes from one GPU (RTX PRO 6000); on 3,460 actions also scored on 4× B200, 25 of 24,220
  answers changed side (0.1%).

## Limits
One attacking agent family (Claude Haiku), one benchmark, side tasks written by its authors. The monitor reads actions
only, as in the dataset. **No adaptive attacker that knows Ekbasis is watching was tested.** A monitor is not
containment: it can be evaded, and it belongs next to sandboxing, least privilege and human review. Ekbasis latency
here was measured under load and is not a fair comparison; unloaded, one 7-question check takes about 1.5 s on an
RTX 5090.

## Files
`PREREG.md`, `SEAL.txt`, `DEVIATIONS.md` (transport, worker count, hardware), `ADDENDUM_E1.md`; `scripts/` (the sealed
scoring and analysis code, unchanged; edit `DATA` and `ROOT` to your paths); `scores/*.jsonl.gz` (per action:
trajectory id, action index, the seven probabilities; no dataset text); `results/` (both analyses' outputs).
Reproduce: download `data/sample.jsonl` from the Hugging Face mirror (check its SHA-256), then
`CTRL_OUT=out_rtx python3 scripts/analyze.py` with the scores unpacked into `out_rtx/`.
