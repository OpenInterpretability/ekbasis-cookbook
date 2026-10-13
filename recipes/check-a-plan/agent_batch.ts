// Check a batch of agent actions before running it, with look when unsure (npm ekbasis >= 0.2.0).
//
//   npm install ekbasis
//   export EKBASIS_API_KEY=ekb_...        # the hosted API is the default URL
//   npx tsx agent_batch.ts
//
// In your agent, replace observe (how things stand now, as text) and execute (run some actions) with the real ones,
// and call guardBatch with the tool calls the model proposed, before running any of them.
import { Ekbasis, harms, runPlan } from "ekbasis";

const RULES =
  "A Linux server running a web shop. rm -rf deletes files permanently; there is no trash and no backup unless one is " +
  "made. systemctl stop takes a service offline until it is started again.";

const server: Record<string, string> = {
  uploads: "40 GB of customer photos",
  cache: "2 GB of thumbnails the shop rebuilds on demand",
  "shop.service": "serving customers",
};

const observe = () =>
  Object.entries(server)
    .map(([k, v]) => (k === "shop.service" ? `shop.service is ${v}.` : `/srv/shop/${k} holds ${v}.`))
    .join(" ");

function execute(actions: string[]) {
  for (const a of actions) {
    console.log("  ran:", a);
    for (const k of ["uploads", "cache"]) if (a.includes(`rm -rf /srv/shop/${k}`)) server[k] = "nothing (emptied)";
  }
}

export async function guardBatch(request: string, actions: string[]) {
  const run = await runPlan(new Ekbasis(), RULES, actions, harms(), observe, execute, { request });
  if (run.stopped) {
    const pc = run.stopped;
    const what = pc.reason === "flagged" ? `flags ${pc.flags.join(", ")}` : "is unsure about";
    console.log(`stopped before step ${run.done + 1}: Ekbasis ${what} it -> ask the user or take a safer way`);
  } else console.log(`all ${run.done} actions ran`);
  return run;
}

guardBatch("Free some disk space on the server.", [
  "du -sh /srv/shop/*",
  "rm -rf /srv/shop/cache/*",
  "rm -rf /srv/shop/uploads/*",
  "df -h",
]).catch((e) => {
  console.error(e);
  process.exit(1);
});
