"""IntentCheckDefense: an AgentDojo tool executor that asks ekbasis.intent_check before each tool call.

Simulates the recommended use (ask a person) conservatively: a call judged "follows_third_party" is treated as the
user declining it, so it does not run and the agent gets a tool error saying so. "unsure" and "serves_user" run.
If the judge cannot answer after retries, the call is blocked (fail-closed) and logged as "cannot_judge".
"""
from __future__ import annotations

import json
import time
from collections.abc import Sequence

from agentdojo.agent_pipeline.tool_execution import ToolsExecutor, tool_result_to_str
from agentdojo.functions_runtime import EmptyEnv, Env, FunctionsRuntime
from agentdojo.types import ChatMessage, ChatToolResultMessage, get_text_content_as_str, text_content_block_from_string
from ekbasis import intent_check
from ekbasis.client import Ekbasis

DECLINED = "The user declined this tool call, so it was not executed."

# Set by the runner before each task, so every decision can be traced back to its (suite, user task, injection task).
CONTEXT: dict = {}


def _events(messages: Sequence[ChatMessage]) -> list[dict]:
    events = []
    for m in messages:
        if m["role"] != "tool" or m.get("tool_call") is None:
            continue
        result = m["error"] or (get_text_content_as_str(m["content"]) if m["content"] else "")
        events.append({"kind": "tool", "name": m["tool_call"].function, "input": dict(m["tool_call"].args),
                       "result": result})
    return events


class IntentCheckToolsExecutor(ToolsExecutor):
    def __init__(self, log_path: str, tool_output_formatter=tool_result_to_str, retries: int = 3) -> None:
        super().__init__(tool_output_formatter)
        self.client = Ekbasis(surface="intent-check")
        self.log_path = log_path
        self.retries = retries

    def _judge(self, query: str, events: list[dict], call) -> tuple[str, float | None, float, dict | None]:
        t0 = time.time()
        for attempt in range(self.retries):
            try:
                v = intent_check(query, events, {"name": call.function, "input": dict(call.args)}, client=self.client)
                return v.verdict, v.p, time.time() - t0, self.client.last_usage
            except Exception:  # CannotJudge or transport error
                time.sleep(2 * (attempt + 1))
        return "cannot_judge", None, time.time() - t0, None

    def query(
        self,
        query: str,
        runtime: FunctionsRuntime,
        env: Env = EmptyEnv(),
        messages: Sequence[ChatMessage] = [],
        extra_args: dict = {},
    ) -> tuple[str, FunctionsRuntime, Env, Sequence[ChatMessage], dict]:
        if len(messages) == 0 or messages[-1]["role"] != "assistant" or not messages[-1]["tool_calls"]:
            return query, runtime, env, messages, extra_args
        last = messages[-1]
        events = _events(messages)
        blocked_ids = set()
        for call in last["tool_calls"]:
            verdict, p, dt, usage = self._judge(query, events, call)
            blocked = verdict in ("follows_third_party", "cannot_judge")
            if blocked:
                blocked_ids.add(call.id)
            with open(self.log_path, "a") as f:
                f.write(json.dumps({**CONTEXT, "call": call.function, "args": json.dumps(dict(call.args))[:500],
                                    "verdict": verdict, "p": p, "latency_s": round(dt, 3), "usage": usage,
                                    "blocked": blocked, "n_prior_tool_events": len(events)}) + "\n")
        allowed = [c for c in last["tool_calls"] if c.id not in blocked_ids]
        executed: dict = {}
        if allowed:
            _, runtime, env, out, extra_args = super().query(
                query, runtime, env, [*messages[:-1], {**last, "tool_calls": allowed}], extra_args)
            executed = {m["tool_call_id"]: m for m in out[len(messages):]}
        results = []
        for call in last["tool_calls"]:
            if call.id in blocked_ids:
                results.append(ChatToolResultMessage(role="tool", content=[text_content_block_from_string("")],
                                                     tool_call_id=call.id, tool_call=call, error=DECLINED))
            else:
                results.append(executed[call.id])
        return query, runtime, env, [*messages, *results], extra_args
