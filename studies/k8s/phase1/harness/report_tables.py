"""WS-K8S Phase 1: print the result tables (pt-BR number format) from ../results/summary.json, for RESULTS_agents.md."""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
d = json.load(open(os.path.join(HERE, "..", "results", "summary.json")))


def pct(x):
    return "—" if x is None else f"{100 * x:.1f}%".replace(".", ",")


def num(x, k=2):
    return "—" if x is None else f"{x:.{k}f}".replace(".", ",")


def pts(x):
    return "—" if x is None else f"{100 * x:+.1f}".replace(".", ",")


print("| Agente / condição | Rodadas | Dano | Sucesso | Não feito | Controles feitos | Perguntas/rodada | Desnecessárias/rodada | "
      "Checagens (silêncio / caminho seguro / pergunta) | Latência mediana da guarda (s) | US$/rodada (agente) | US$ previsor Sonnet |")
print("|---|---|---|---|---|---|---|---|---|---|---|---|")
for k, t in d["conds"].items():
    print(f"| {k} | {t['runs']} | {pct(t['harm'])} | {pct(t['success'])} | {pct(t['not_done'])} | {pct(t['controls_done'])} | "
          f"{num(t['questions_per_run'])} | {num(t['needless_per_run'])} | {t['checks']} ({t['silent']} / {t['suggest']} / {t['ask_user']}) | "
          f"{num((t['guard_ms_median'] or 0) / 1000, 1) if t['guard_ms_median'] else '—'} | {num(t['agent_cost_per_run'], 3)} | "
          f"{num(t['sonnet_forecaster_cost'], 2)} |")
print()
for h in ("K-H1", "K-H2", "K-H3"):
    if h in d:
        print(h, json.dumps(d[h], ensure_ascii=False))
print()
print("| Contraste | A | B | A − B (pts) | IC 95% |")
print("|---|---|---|---|---|")
for name, r in d.get("secondary", {}).items():
    print(f"| {name} | {pct(r['a'])} | {pct(r['b'])} | {pts(r['diff'])} | [{pts(r['ci'][0])}; {pts(r['ci'][1])}] |")
print()
for k, fam in d.get("harm_by_family", {}).items():
    print(k, fam)
for k, c in d.get("harm_by_conflict", {}).items():
    print(k, c)
for k, t in d["conds"].items():
    print(k, "safer ways", t.get("safer_ways"), "code checks", t.get("code_checks"))
