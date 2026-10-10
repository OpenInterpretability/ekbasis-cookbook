# Pricing — avaliação completa (rascunho LOCAL, não publicar)

> Premissa do Caio (09/10): custo de máquina = 0 (a empresa já paga a B200 e já tem clientes pagando por ela). Tudo abaixo é margem pura, menos tempo humano.

## 1. O regime de custo real

O custo não é zero *para sempre* — é zero **até a capacidade encher**:

| regime | capacidade de decisões/dia | custo/1M input tokens |
|---|---|---|
| **Co-tenant** (atual, no GLM de produção) | ~50–100k/dia sem impacto no GLM | **US$ 0** |
| **1 GPU dedicada** (quando a demanda passar) | ~700k/dia (8–10 req/s medidos no card) | US$ 167/mês ÷ uso: **US$ 0,005/1M a 100% util · US$ 0,05 a 10% · US$ 0,26 a 2%** |
| 4 GPUs dedicadas (TP4 inteira) | ~2,8M/dia | US$ 667/mês |

Tradução: **os primeiros ~150M–300M tokens/mês (100k–200k decisões/dia) custam zero.** Só depois disso entra custo real — e mesmo o pior caso (2% de utilização) é US$ 0,26/1M.

## 2. Segmentos e precificação

### S1 — CB = infra, não cliente (decisão do Caio, 09/10)
**A CB não paga por uso.** O guard roda em co-tenância na B200 como arranjo interno entre as empresas:
- CB hospeda (a GPU já está paga e faturada pros clientes do GLM)
- Os agentes da CB (e do Caio) usam o guard **de graça, pra sempre** (o dogfooding continua)
- **Quem paga: os clientes da OpenInterp** — nada de add-on na fatura do GLM

### S2 — Self-serve (hosted; 30 dias)

| plano | preço | inclui |
|---|---|---|
| Free | 5k decisões/mês + **self-host grátis pra sempre** | o funil inteiro |
| Dev | **US$ 15/mês** | 50k decisões, 1 chave |
| Team | **US$ 79/mês** | 500k decisões, 5 chaves, dashboard |
| Business | **US$ 0,002/decisão** além da cota | SLA 99%, suporte 48h |

Token-equivalent no rodapé: "≈ US$ 1,33/1M input" (comparável com LLMs sem assustar).

### S3 — Enterprise on-prem (60–90 dias)
Setup **US$ 5–15k** (co-tenância instalada + runbook + monitoramento) + retainer **US$ 1–3k/mês**. É o único segmento com custo real (horas humanas).

### S4 — Mundos customizados (a margem mais alta)
Fábrica de consequências no domínio do cliente (o k8s DELE, o billing DELE): setup **US$ 10–50k**. Vira consultoria de dados; o modelo é a prova de conceito.

## 3. Projeção (parametrizada — preencher com os números reais da CB)

| horizonte | self-serve (OpenInterp) | enterprise (OpenInterp) | total |
|---|---|---|---|
| M1 | ~US$ 300 (early adopters do Reddit/cookbook) | — | **~US$ 300/mês** |
| M3 | ~US$ 1.500 (50 Dev/5 Team) | 1 setup US$ 10k one-time | **~US$ 1.500/mês + 10k** |
| M6 | ~US$ 4.000 (200 Dev/15 Team) | 2 × (US$ 10k + 2k/mês) | **~US$ 8.000/mês + 20k** |

Canal de aquisição dos clientes OpenInterp: o cookbook + Reddit (8,9K views) + o estudo de agentes (48%→6%) como prova → trial self-host → hosted. O funil do sócio (testando agora) é o primeiro.
(Nota: se algum cliente CB/parceiro QUER o guard, ele compra como cliente OpenInterp — mesmo preço de tabela.)

## 4. Riscos e contrapesos

1. **Capacidade compartilhada**: o guard compete com o GLM pelas GPUs (max-num-seqs 2 hoje). Gate: monitorar `sglang` + latência do GLM; se o guard passar de ~100k decisões/dia, dedicar 1 GPU (US$ 167/mês — absorvido pela receita do S1).
2. **Âncora do comprador**: "$1/1M" ao lado de mini-LLMs a "$0,30/1M" parece caro; "$0,0015 por decisão que impede o incidente" não. Liderar por decisão.
3. **Self-host grátis é o moat**: nunca cobrar pelos pesos; a receita é conveniência + confiança + contexto.
4. **Open-source goodwill**: o free tier generoso alimenta o Reddit/GitHub (o canal que já rendeu 8,9K views).

## 5. Decisões pendentes do Caio

1. ~~Liderar $/decisão ou $/1M~~ → **DECIDIDO: US$ 0,04/1M input, sem output** (Caio, 09/10)
2. Confirmação: CB nunca paga por uso (infra interna); a receita vem só dos clientes OpenInterp?
3. Free tier: 5k decisões/mês?
4. Quem fatura: CB (bundle) e OpenInterp (self-serve) — duas marcas, duas faturas?
5. Quando publicar a página (o endpoint público + auth já estão prontos e testados).
