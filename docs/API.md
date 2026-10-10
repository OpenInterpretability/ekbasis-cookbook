# The Ekbasis API (typed decisions, one forward pass)

The server exposes `POST /v1/systemone` (and `/health`). Text only unless the build says otherwise. One question ≈ one decision; the model answers in **one forward pass** — no generation, no chain-of-thought, ~0.5 s on a GPU.

## Question types

### `choice` — pick among outcomes

```bash
curl $URL/v1/systemone -H "Content-Type: application/json" -d '{
  "state": "Checking account available balance: $180.20. About to: transfer $250.00 to a friend.",
  "questions": {"q": {"type": "choice", "instructions": "What happens with the transfer?",
                      "options": ["transfer succeeds", "transfer fails: insufficient funds"]}}}'
```

```json
{"answers": {"q": {"type": "choice", "choice": "transfer fails: insufficient funds",
                   "probabilities": {"transfer succeeds": 0.03, "transfer fails: insufficient funds": 0.97},
                   "confidence": 0.97}}}
```

### `noul` / `boolean` — will work be lost? (yes/no with probability)

```json
{"questions": {"q": {"type": "noul", "instructions": "Will uncommitted work be lost?",
                     "criteria": {"true": "uncommitted changes are gone", "false": "nothing is lost"}}}}
```
→ `{"type": "noul", "noul": 0.98, "probability": 0.98, "value": true, "confidence": 0.98}`

### `score` — how many / how much

```json
{"questions": {"q": {"type": "score", "instructions": "How many of the 3 modified files keep their changes?",
                     "criteria": {"0": "none", "1": "one", "2": "two", "3": "all three"}}}}
```
→ `{"type": "score", "score": 0, "expected": 0.01, "probabilities": {"0": 0.99, ...}, "confidence": 0.99}`

## Batching: several questions, one state, one request

```json
{"state": "...", "questions": {"lost": {...}, "untracked": {...}, "recoverable": {...}}}
```
The state is read once (prefix cache) and the questions run together — **3 questions in 0.62 s** measured. Every answer equals what its own prompt would give.

## Sessions: agent state that evolves

```bash
POST /v1/sessions        {"state": "Working tree: 2 modified files, 1 untracked"}  → {"session_id": "..."}
POST /v1/sessions/<id>/append   {"text": "The agent then ran: git stash"}
POST /v1/sessions/<id>/systemone {"questions": {...}}    # asks against the evolved state
DELETE /v1/sessions/<id>
```
Measured: after `append "git stash"`, asking "how many of the 2 modified files remain modified" → **0 of 2 (98.8%)** — the model tracks the state transition.

## Options beyond one pass

Up to 588 options are read in one forward pass (labels A..Z, AA, AB… — single tokens). More options go through a tournament automatically.

## Reading confidence

`confidence` is the max option probability. Measured behavior: 0.95–0.99 when the state fully determines the answer; **0.59–0.84 on ambiguous states** (it degrades instead of bluffing). Treat < 0.9 on a destructive action as "collect the missing fact and ask again".

## Limits

- State over ~32k tokens → clean `422` with the reason (the git client's world stays at ~2k by design)
- The API has no authentication — put it behind a network boundary or an auth proxy before exposing it
- One server per user/agent for consistent latency

## Client & SDK

```python
from ekbasis import Ekbasis, choice
c = Ekbasis("http://127.0.0.1:8010")
ans = c.ask(state, {"q": choice("O que acontece?", ["a", "b"])})
print(ans["q"].probability, ans["q"].confidence)
```
