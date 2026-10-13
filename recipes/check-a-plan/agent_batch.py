"""Check a batch of agent actions before running it, with look when unsure (ekbasis >= 0.1.28).

Runs in a minute against the hosted API on a tiny simulated server, so you can see the loop before wiring it to your
agent:

    pip install -U ekbasis
    export EKBASIS_URL=https://openinterp.org/api/v1 EKBASIS_API_KEY=ekb_...
    python agent_batch.py

In your agent, replace `observe` (how things stand now, as text) and `execute` (run some actions) with the real ones,
and call `guard_batch` with the tool calls the model proposed, before running any of them.
"""
from ekbasis import Ekbasis, harms, run_plan

RULES = ("A Linux server running a web shop. rm -rf deletes files permanently; there is no trash and no backup unless "
         "one is made. systemctl stop takes a service offline until it is started again.")

# The simulated system: what exists, and what each action does to it.
server = {"uploads": "40 GB of customer photos", "cache": "2 GB of thumbnails the shop rebuilds on demand",
          "shop.service": "serving customers"}


def observe() -> str:
    return " ".join(f"/srv/shop/{k} holds {v}." if k != "shop.service" else f"shop.service is {v}."
                    for k, v in server.items())


def execute(actions):
    for a in actions:
        print("  ran:", a)
        for k in ("uploads", "cache"):
            if f"rm -rf /srv/shop/{k}" in a:
                server[k] = "nothing (emptied)"


def guard_batch(request: str, actions):
    """Run the safe part of `actions`; stop before a step that is still flagged on the real state."""
    run = run_plan(Ekbasis(), RULES, actions, harms(), observe=observe, execute=execute, request=request)
    if run.stopped:
        pc = run.stopped
        what = "flags " + ", ".join(pc.flags) if pc.reason == "flagged" else "is unsure about"
        print(f"stopped before step {run.done + 1}: Ekbasis {what} it -> ask the user or take a safer way")
    else:
        print(f"all {run.done} actions ran")
    return run


if __name__ == "__main__":
    plan = ["du -sh /srv/shop/*", "rm -rf /srv/shop/cache/*", "rm -rf /srv/shop/uploads/*", "df -h"]
    guard_batch("Free some disk space on the server.", plan)
