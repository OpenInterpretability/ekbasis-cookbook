# Serving Ekbasis locally on Apple Silicon (MLX)

The MLX 4-bit build ships its own server — no vLLM, no GPU box, no internet needed at inference time. Weights ~15 GB; 32 GB of memory recommended (16 GB is tight).

```bash
pip install "mlx>=0.32.2" "mlx-lm>=0.31.3"
hf download caiovicentino1/Ekbasis-27B-MLX-4bit --local-dir Ekbasis-27B-MLX-4bit
python Ekbasis-27B-MLX-4bit/mlx_serve.py Ekbasis-27B-MLX-4bit --host :: --port 8000
```

`--host ::` serves IPv4+IPv6, so other machines on your network reach it at `http://<your-mac>.local:8000` (Bonjour resolves the name). The API is the same as the GPU build's (`/v1/systemone`), answered with the same letter readout and calibration — client, git guard, hook and MCP all work unchanged.

## Pointing other machines at it

```bash
export EKBASIS_URL=http://MacBook-Pro.local:8000
ekbasis health
```

## What to expect

- Latency per check: **4.7–12.5 s** measured end-to-end from another Mac on the LAN (the GPU build does the same in 0.4–2.5 s)
- The server answers requests **one at a time**; a second concurrent client waits 1.3–3.7× longer — run one server per user or agent
- The API has **no authentication**: keep it on a network you trust, and keep the URL off public channels
- Text only (requests with images are refused; use a GPU build for those)

## Parity check

The same question answered by the MLX build and by the INT4 GPU build differs by **0.2 percentage points** in probability (98.0 vs 97.8 in the measured case). Answers are interchangeable for guard use.
