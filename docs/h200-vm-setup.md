# H200 GPT-OSS VM runbook

This is the setup used to generate the literal translations with
`openai/gpt-oss-120b` on one NVIDIA H200. The inference server stays bound to
the VM's loopback interface and is reached through an SSH tunnel; the project,
translation cache, and generated artifacts remain on the local machine.

The tested software combination was Ubuntu 22.04, Python 3.10, NVIDIA driver
580.173.02, and `vllm==0.24.0`.

## 1. Connect and inspect the VM

On the local machine:

```bash
VISCOUNT_VM=replace-with-vm-ip
VISCOUNT_SSH_KEY=/replace/with/private-key

ssh -i "$VISCOUNT_SSH_KEY" \
  -o IdentitiesOnly=yes \
  root@"$VISCOUNT_VM"
```

On the VM, verify the GPU and locate the large data volume before changing
anything:

```bash
nvidia-smi
lsblk -f
df -h
free -h
python3 --version
```

The actual VM had one H200 with about 144 GB VRAM and an already-formatted,
empty ext4 volume at `/dev/vdc1`. It was mounted without formatting it:

```bash
mkdir -p /mnt/viscount-nvme
mount /dev/vdc1 /mnt/viscount-nvme
df -h /mnt/viscount-nvme
```

Device names vary between VMs. Check `lsblk -f` and the volume contents first;
do not run `mkfs` on an existing volume.

## 2. Install the system prerequisites

The minimal VM image was missing three things needed during vLLM startup:
Python's venv support, `Python.h`, and the `ninja` executable used by FlashInfer
JIT compilation. Install all of them before launching the model:

```bash
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y python3.10-venv python3.10-dev ninja-build
```

Without `python3.10-dev`, startup fails with `Python.h: No such file or
directory`. Without `ninja-build`, it fails with `FileNotFoundError: ninja`.

## 3. Create the pinned vLLM environment

Keep the environment, package cache, model cache, and logs on the large data
volume:

```bash
VISCOUNT_NVME=/mnt/viscount-nvme

mkdir -p \
  "$VISCOUNT_NVME/pip-cache" \
  "$VISCOUNT_NVME/huggingface" \
  "$VISCOUNT_NVME/logs"

python3.10 -m venv "$VISCOUNT_NVME/vllm-venv"

PIP_CACHE_DIR="$VISCOUNT_NVME/pip-cache" \
  "$VISCOUNT_NVME/vllm-venv/bin/python" -m pip install --upgrade pip

PIP_CACHE_DIR="$VISCOUNT_NVME/pip-cache" \
  "$VISCOUNT_NVME/vllm-venv/bin/python" -m pip install vllm==0.24.0
```

## 4. Start the private GPT-OSS server

The following is the exact server configuration used for the completed run:

```bash
VISCOUNT_NVME=/mnt/viscount-nvme

nohup env \
  HF_HOME="$VISCOUNT_NVME/huggingface" \
  HF_XET_HIGH_PERFORMANCE=1 \
  VLLM_LOGGING_LEVEL=INFO \
  "$VISCOUNT_NVME/vllm-venv/bin/vllm" serve openai/gpt-oss-120b \
    --host 127.0.0.1 \
    --port 8000 \
    --max-model-len 4096 \
    --gpu-memory-utilization 0.92 \
    --enable-prefix-caching \
  > "$VISCOUNT_NVME/logs/vllm.log" 2>&1 < /dev/null &

echo $! > "$VISCOUNT_NVME/vllm.pid"
```

The first start downloads roughly 61 GiB of model weights and performs
one-time FlashInfer compilation and CUDA graph capture. Follow progress with:

```bash
tail -f /mnt/viscount-nvme/logs/vllm.log
```

Wait until the OpenAI-compatible endpoint responds and advertises the exact
requested model:

```bash
curl -fsS http://127.0.0.1:8000/v1/models | jq .
```

The server is deliberately not exposed on a public interface.

## 5. Open the local SSH tunnel

Run this in a separate local terminal. Local port `18000` was used because
port `8000` was already occupied locally:

```bash
VISCOUNT_VM=replace-with-vm-ip
VISCOUNT_SSH_KEY=/replace/with/private-key

ssh -N \
  -i "$VISCOUNT_SSH_KEY" \
  -o IdentitiesOnly=yes \
  -o ExitOnForwardFailure=yes \
  -L 18000:127.0.0.1:8000 \
  root@"$VISCOUNT_VM"
```

From another local terminal, confirm the tunneled endpoint:

```bash
curl -fsS http://127.0.0.1:18000/v1/models | jq .
```

## 6. Run the preflight

From the repository root on the local machine:

```bash
uv run python scripts/add_literal_translations.py preflight \
  --base-url http://127.0.0.1:18000/v1 \
  --model openai/gpt-oss-120b \
  --count 10
```

Inspect the ten printed context/target/translation records. The test is manual
by design: confirm that each response translates only its target, does not
import either context sentence, and leaves no target Italian untranslated.

During the actual run, the longest preflight case initially copied `ghiri`.
Prompt version 10 added the observed clarification `ghiri means dormice`, after
which the same ten-case preflight passed.

## 7. Translate the complete corpus

Only after the preflight passes:

```bash
uv run python scripts/add_literal_translations.py translate \
  --base-url http://127.0.0.1:18000/v1 \
  --model openai/gpt-oss-120b \
  --concurrency 50
```

Each successful response is checkpointed immediately in
`artifacts/work/literal-translations-cache`. Its key is the SHA-256 hash of the exact
serialized request, including the model, prompts, two-sentence context, target,
structured-output schema, and decoding settings. If the tunnel or VM fails,
restart them and run the identical command; completed requests are loaded from
diskcache instead of being submitted again.

The completed run translated 1,404 sentences and wrote:

- `artifacts/work/alignment.json`
- `artifacts/site/viscount-bilingual.html`

## 8. Verify the local outputs

Check counts and empty values:

```bash
jq '{
  metadata: .literal_translation,
  sentence_entries: ([.units[].literal_english_sentences[]] | length),
  empty_translations: ([
    .units[].literal_english_sentences[] |
    select((.english | length) == 0)
  ] | length),
  units_without_literal: ([
    .units[] | select(has("literal_english") | not)
  ] | length)
}' artifacts/work/alignment.json

uv run pytest -q
```

The observed result was 1,404 sentence entries, zero empty translations, zero
units without literal text, and 16 passing tests. Running the complete command
again printed `Loaded 1404 translations from diskcache` and produced
byte-identical JSON and HTML files.

## 9. Stop inference and end billing

After the local artifacts have been verified, stop only the PID recorded at
startup:

```bash
VISCOUNT_NVME=/mnt/viscount-nvme
VLLM_PID=$(cat "$VISCOUNT_NVME/vllm.pid")
kill "$VLLM_PID"

nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader
```

An empty final command confirms there are no GPU compute processes. End the SSH
tunnel with `Ctrl-C`.

Stopping vLLM or shutting down the guest OS does not necessarily release a
rented cloud GPU. Terminate the VM allocation in the provider dashboard or API
to guarantee that billing ends. The vLLM environment and downloaded model can
remain on persistent storage if the provider preserves that volume.
