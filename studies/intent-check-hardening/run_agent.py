"""Front 3: AgentDojo with an agent that falls for the injections (PREREG.md, section 3). Concurrency 1, resumable.

Agent: glm-5.3-flash with thinking switched off (chat_template_kwargs enable_thinking=false, no reasoning_effort); the
server is not changed. Scoring is AgentDojo's own (v1.2.2); attacks are the package's published ones.

  run_agent.py plan  out.json                       # writes the calibration and benchmark plans (no call)
  run_agent.py calib plan.json out_dir              # calibration: condition none, attacks important_instructions and
                                                    # tool_knowledge, 40 pairs
  run_agent.py bench plan.json out_dir ATTACK       # benchmark: none / intent_base / intent_hardened, interleaved
"""
import json
import os
import random
import sys
import time
import traceback
from functools import partial
from pathlib import Path

import openai
from agentdojo.agent_pipeline import AgentPipeline, InitQuery, SystemMessage, ToolsExecutionLoop, ToolsExecutor
from agentdojo.agent_pipeline.agent_pipeline import load_system_message
from agentdojo.agent_pipeline.llms.openai_llm import OpenAILLM
from agentdojo.attacks.attack_registry import load_attack
from agentdojo.benchmark import benchmark_suite_without_injections, run_task_with_injection_tasks
from agentdojo.logging import OutputLogger
from agentdojo.task_suite.load_suites import get_suite

import intent_defense2 as intent_defense

VERSION = "v1.2.2"
MODEL = "glm-5.3-flash"
SEED = 20261012
CALIB = {"workspace": 24, "travel": 6, "banking": 6, "slack": 4}            # 40 pairs
BENCH = {"workspace": 89, "travel": 22, "banking": 23, "slack": 16}         # 150 pairs, disjoint from CALIB
COND_OPTS = {"intent_base": {}, "intent_hardened": {"checker_text": "flag", "delegation": True}}


def make_llm():
    client = openai.OpenAI(base_url=os.environ["GLM_BASE_URL"], api_key=os.environ["OPENAI_API_KEY"],
                           timeout=600, max_retries=2)
    client.chat.completions.create = partial(client.chat.completions.create,
                                             extra_body={"chat_template_kwargs": {"enable_thinking": False}},
                                             max_tokens=4096)   # D2: cap, a thinking-off run hung >17 min
    return OpenAILLM(client, MODEL)


def make_pipeline(cond: str, out: Path) -> AgentPipeline:
    llm = make_llm()
    if cond == "none":
        loop = ToolsExecutionLoop([ToolsExecutor(), llm])
    else:
        loop = ToolsExecutionLoop([intent_defense.IntentCheckToolsExecutor(str(out / "intent_decisions.jsonl"),
                                                                           **COND_OPTS[cond]), llm])
    p = AgentPipeline([SystemMessage(load_system_message(None)), InitQuery(), llm, loop])
    p.name = f"local-{MODEL}-nothink-{cond}"
    return p


def plan(out_path):
    rng = random.Random(SEED)
    calib, bench, clean = [], [], []
    for s in ["workspace", "travel", "banking", "slack"]:
        su = get_suite(VERSION, s)
        pairs = [(u, i) for u in su.user_tasks for i in su.injection_tasks]
        rng.shuffle(pairs)
        calib += [{"suite": s, "ut": u, "it": i} for u, i in pairs[:CALIB[s]]]
        bench += [{"suite": s, "ut": u, "it": i} for u, i in pairs[CALIB[s]:CALIB[s] + BENCH[s]]]
        clean += [{"suite": s, "ut": u, "it": None} for u in su.user_tasks]
    rng.shuffle(bench)
    rng.shuffle(clean)
    json.dump({"benchmark_version": VERSION, "seed": SEED, "calib": calib, "bench": bench, "clean": clean},
              open(out_path, "w"), indent=1)
    print(len(calib), len(bench), len(clean))


def run_item(pipe, item, attack_name, logdir: Path):
    suite = get_suite(VERSION, item["suite"])
    if item["it"] is None:
        res = benchmark_suite_without_injections(pipe, suite, logdir=logdir, force_rerun=False,
                                                 user_tasks=[item["ut"]], benchmark_version=VERSION)
        return list(res["utility_results"].values())[0], None
    attack = load_attack(attack_name, suite, pipe)
    u, s = run_task_with_injection_tasks(suite, pipe, suite.get_user_task_by_id(item["ut"]), attack, logdir,
                                         False, [item["it"]], VERSION)
    key = (item["ut"], item["it"])
    return u[key], s[key]


def run(jobs, out: Path, conds):
    out.mkdir(parents=True, exist_ok=True)
    logdir = out / "logs"
    pipes = {c: make_pipeline(c, out) for c in conds}
    done_path = out / "results.jsonl"
    done = set()
    if done_path.exists():
        for line in open(done_path):
            r = json.loads(line)
            done.add((r["cond"], r["attack"], r["suite"], r["ut"], r["it"]))
    t_start = time.time()
    with OutputLogger(str(logdir), live=None):
        for i, (item, attack_name) in enumerate(jobs):
            order = conds[i % len(conds):] + conds[:i % len(conds)]
            for cond in order:
                if (cond, attack_name, item["suite"], item["ut"], item["it"]) in done:
                    continue
                intent_defense.CONTEXT.clear()
                intent_defense.CONTEXT.update(cond=cond, attack=attack_name, suite=item["suite"], ut=item["ut"],
                                              it=item["it"])
                t0, err, utility, security = time.time(), None, None, None
                for attempt in range(2):
                    try:
                        utility, security = run_item(pipes[cond], item, attack_name, logdir)
                        err = None
                        break
                    except Exception as e:
                        err = f"{type(e).__name__}: {str(e)[:300]}"
                        traceback.print_exc()
                        time.sleep(10)
                rec = {"cond": cond, "attack": attack_name, **{k: item[k] for k in ("suite", "ut", "it")},
                       "utility": utility, "security": security, "error": err, "seconds": round(time.time() - t0, 1)}
                with open(done_path, "a") as f:
                    f.write(json.dumps(rec) + "\n")
                print(f"[{i + 1}/{len(jobs)} {time.time() - t_start:.0f}s] {rec}", flush=True)


def main():
    mode = sys.argv[1]
    if mode == "plan":
        return plan(sys.argv[2])
    p, out = json.load(open(sys.argv[2])), Path(sys.argv[3])
    if mode == "calib":
        jobs = [(it, a) for it in p["calib"] for a in ("important_instructions", "tool_knowledge")]
        return run(jobs, out, ["none"])
    if mode == "bench":
        attack_name = sys.argv[4]
        jobs = [(it, attack_name) for it in p["bench"]] + [(it, "none") for it in p["clean"]]
        return run(jobs, out, ["none", "intent_base", "intent_hardened"])
    raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
