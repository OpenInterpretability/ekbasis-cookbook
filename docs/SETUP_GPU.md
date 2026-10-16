# Serving Ekbasis on GPUs (including next to a production LLM)

Requirements: **vLLM ≥ 0.30.0** (older builds return wrong answers when several long requests batch together on this hybrid Gated DeltaNet architecture). One GPU for INT4 (18.6 GB, or 24 GB with a 4k context); tensor parallel for bigger memory.

## Simple case: one dedicated GPU

```bash
hf download caiovicentino1/Ekbasis-Skopos-27B-INT4 --local-dir Ekbasis-Skopos-27B-INT4
bash Ekbasis-Skopos-27B-INT4/serve_vllm.sh Ekbasis-Skopos-27B-INT4 8001          # vLLM on 127.0.0.1:8001
python Ekbasis-Skopos-27B-INT4/serve.py --model Ekbasis-Skopos-27B-INT4 --vllm-url http://127.0.0.1:8001 --port 8010
EKBASIS_URL=http://127.0.0.1:8010 ekbasis health
```

The previous version, `caiovicentino1/Ekbasis-27B-INT4`, has the same size and is served the same way.

## Co-tenant case: sharing the GPUs with a production LLM

Measured on a 4× B200 (183 GB each) sharing all 4 GPUs with a production SGLang TP4 deployment that holds ~171 GB/GPU. The free margin was 10.4–11.6 GB per GPU, and Ekbasis-27B-INT4 fits in it at TP4 with these settings (measured with
Ekbasis-27B-INT4; Ekbasis-Skopos-27B-INT4 has the same architecture and size, not measured in this setting):

```bash
# isolated venv — never pip-install into the system env of the production process
python3 -m venv /root/ekbvenv && source /root/ekbvenv/bin/activate
pip install "vllm>=0.30.0" "huggingface_hub[cli]"
hf download caiovicentino1/Ekbasis-27B-INT4 --local-dir /root/Ekbasis-27B-INT4

export NCCL_NVLS_ENABLE=0                    # (1)
export VLLM_ALLREDUCE_USE_FLASHINFER=0       # (2)
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

vllm serve /root/Ekbasis-27B-INT4 --served-model-name decider --host 127.0.0.1 --port 8001 \
  --tensor-parallel-size 4 --dtype bfloat16 \
  --gpu-memory-utilization 0.036 \
  --max-model-len 32768 --max-num-batched-tokens 1024 --max-num-seqs 2 --enforce-eager \
  --limit-mm-per-prompt '{"image": 0, "video": 0}' \
  --enable-prefix-caching --mamba-cache-mode align \
  --logprobs-mode processed_logprobs --max-logprobs 600

python /root/Ekbasis-27B-INT4/serve.py --model /root/Ekbasis-27B-INT4 \
  --vllm-url http://127.0.0.1:8001 --port 8010 --host 0.0.0.0
```

### The 3 things that make co-tenancy work

1. **`NCCL_NVLS_ENABLE=0`** — the production group's NCCL already registered the NVLink SHARP multicast objects on the fabric; a second group fails to bind with `CUDA error 401`. The model's own warning names the fix. Allreduces fall back to NVLink P2P — irrelevant for the tiny per-layer allreduces of a single-pass readout.
2. **`VLLM_ALLREDUCE_USE_FLASHINFER=0`** — vLLM 0.30 selects FLASHINFER allreduce by default; its comm module wants ~2.7 GB of *non-PyTorch* memory per GPU (and a minutes-long JIT on first use). The guard's allreduces are tiny; vLLM's CUSTOM allreduce kernel is faster for them anyway.
3. **`--gpu-memory-utilization` validates against FREE memory in vLLM 0.30** — with 8–9 GB free after context+NCCL, 0.036 is the ceiling. Note it only caps what **PyTorch** allocates: weights + activations + KV. The non-PyTorch overhead (CUDA context ~0.5 GB + NCCL ~1.5 GB) is on top.

### Budget as measured

| item | per GPU |
|---|---|
| INT4 weights (TP4) | 4.65 GB |
| CUDA context + NCCL | ~2 GB |
| KV pool (32k ctx) | ~2.3 GB → **102,400 tokens** |
| **total** | **~9.1 GB** (margin ≥ 1.5 GB left for the production tenant) |

### Operation notes (learned the hard way)

- Kill and relaunch **in the same detached script** (`kill → wait for the port to free → launch`); overlapping launches collide on the port and leak worker processes.
- Monitor the tenant before/after: `nvidia-smi` per GPU and the production engine's own metrics. A static-pool tenant is unaffected by the neighbor dying — and vice versa.
- The guard's states are 0.7–1.6k tokens (the client caps its git world at 8 files / 12 branches); bigger raw states fit up to the 32k context, and >32k returns a clean 422.

## Other builds

| build | needs | note |
|---|---|---|
| [Ekbasis-27B](https://huggingface.co/caiovicentino1/Ekbasis-27B) (bf16, 55 GB) | 80 GB GPU | the reference |
| [Ekbasis-27B-FP8](https://huggingface.co/caiovicentino1/Ekbasis-27B-FP8) (30.4 GB) | 48 GB GPU | 1.6× bf16 throughput |
| [Ekbasis-27B-INT4](https://huggingface.co/caiovicentino1/Ekbasis-27B-INT4) (18.6 GB) | 24–32 GB GPU | what this cookbook measures |
| [Ekbasis-27B-MLX-4bit](https://huggingface.co/caiovicentino1/Ekbasis-27B-MLX-4bit) (15 GB) | Apple Silicon 32 GB+ | [SETUP_MAC_MLX.md](SETUP_MAC_MLX.md) |
