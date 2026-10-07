# Audiobook-to-ebook alignment exploration

Research and local evaluation performed 20 July 2026 for the Italian audiobook
of *Il visconte dimezzato*.

## What needs aligning

The existing pipeline has already reduced the bilingual text to 1,298 ordered
alignment units. Each unit contains one to three Italian sentences and its
corresponding English translation group. The audio is a single 3:04:04 Opus
file. It begins with the novel's first sentence, so the task is to timestamp the
Italian side of each existing unit; the English text does not need a second
acoustic alignment.

## Current method families

| Method | Strengths | Limitations for this book | Decision |
|---|---|---|---|
| Multilingual Word Aligner (MWA, June 2026 preprint) | Learned DP over MMS and self-supervised phoneme-boundary representations; the paper reports better results than MFA, MMS, and WhisperX on its English tests and competitive unseen-language transfer | Italian was not evaluated, and the authors say code/checkpoints will be released only upon acceptance | Most promising emerging method, not yet reproducible for this artifact |
| Montreal Forced Aligner (Kaldi/HMM-GMM) | Mature phone- and word-level alignment, pronunciation dictionaries, pretrained language models | Current installation depends on Conda/Kaldi rather than a pure `uv` environment; long audio first needs segmentation and dictionary/OOV handling | Good independent verifier, not the primary Mac pipeline |
| MMS/CTC forced alignment | A multilingual model trained on 1,130 languages; efficient global CTC alignment is designed for long recordings | Reference implementation is oriented to CUDA/CPU, the public 300M checkpoint is CC-BY-NC, and TorchAudio's forced-alignment API is deprecated | Strong fallback/refinement option, especially on CUDA |
| WhisperX | VAD plus Whisper transcription plus CTC forced alignment; its paper reports state-of-the-art long-form transcription and word segmentation | Official acceleration targets CUDA. It adds a second acoustic model and its Italian alignment quality still depends on the selected wav2vec2 model | Best general CUDA baseline, but not the best native-Mac fit |
| CrisperWhisper | State-of-the-art cross-attention timing on its evaluated verbatim datasets | Published model guarantees only English and German, is 2B parameters, and is CC-BY-NC | Not appropriate for Italian |
| MLX Whisper plus reference-text reconciliation | Native Apple Silicon inference, multilingual large-v3-turbo recognition, official cross-attention/DTW word timing, simple `uv` installation | Whisper word boundaries are an inference-time estimate, not phonetic forced alignment; ebook variants must be reconciled afterward | Selected for group-level ranges |

Primary references:

- [WhisperX paper](https://arxiv.org/abs/2303.00747)
- [2026 Multilingual Word Aligner preprint](https://arxiv.org/abs/2606.10675)
- [OpenAI Whisper word-timestamp implementation](https://github.com/openai/whisper/blob/main/whisper/transcribe.py)
- [Apple MLX Whisper implementation](https://github.com/ml-explore/mlx-examples/tree/main/whisper)
- [MMS project and long-audio forced-alignment tooling](https://github.com/facebookresearch/fairseq/tree/main/examples/mms)
- [CTC forced aligner using the MMS model](https://github.com/MahmoudAshraf97/ctc-forced-aligner)
- [Montreal Forced Aligner documentation](https://montreal-forced-aligner.readthedocs.io/en/stable/)
- [CrisperWhisper model card and language limitation](https://huggingface.co/nyralabs/CrisperWhisper)
- [TorchAudio forced-alignment deprecation notice](https://docs.pytorch.org/audio/main/tutorials/ctc_forced_alignment_api_tutorial.html)

## Selected hybrid pipeline

1. Transcribe the complete audiobook in Italian with
   `mlx-community/whisper-large-v3-turbo`, requesting word timestamps. MLX runs
   this stage on Apple Silicon's GPU and unified memory.
2. Normalize both streams only for matching: case-fold, remove accents, and
   split apostrophe contractions. The published ebook text itself is unchanged.
3. Find exact monotonic token blocks between the ASR output and ebook.
4. Resolve the short gaps between exact blocks with local Needleman-Wunsch
   alignment, which captures variants such as `Bohemia` versus `Boemia`.
5. Set each bilingual unit's range to its first and last aligned acoustic word.
   Preserve natural silence between groups instead of assigning it arbitrarily.
6. Store exact-token coverage, approximate coverage, ASR probability, and a
   high/medium/low confidence label with every range so weak areas are reviewable.
   Start and end boundaries are independently marked `aligned`, `inferred`, or
   `interpolated`; a range cannot be high-confidence unless both edges have an
   acoustic token anchor.

This is deliberately a two-level alignment. Whisper determines *where speech
occurred*; the ebook-ASR sequence alignment determines *which exact published
sentence group it belongs to*. That prevents small transcription errors from
changing the output text or causing cumulative drift.

## Initial local evidence

On the first three minutes, large-v3-turbo produced 375 Whisper words with mean
probability 0.980 and no word below 0.5. Against the first 20 bilingual units,
the reconciliation aligned 344 of 345 reference tokens, including 336 exact
matches. All 20 units received a high-confidence, non-overlapping range and no
unit required interpolation.

These confidence values measure agreement between ASR and the exact ebook. They
do not constitute millisecond-level ground truth. For sentence/group playback,
word-DTW boundaries are sufficient; for phonetic research or audio cutting at a
specific consonant, manually label a sample and compare against CTC/MFA before
choosing the final boundary source.

## Full-book outcome and QA

- 23,376 of 23,773 normalized ebook tokens aligned (98.33%), including 22,684
  exact matches (95.42%). Mean similarity among paired tokens is 0.994.
- 1,202 group ranges are high confidence, 95 medium, and one low. There are 28
  inferred starts and 13 inferred ends; these are retained as medium confidence
  even when their internal text match is otherwise excellent.
- The only fully interpolated range is `c05-a0044`, the non-lexical
  `Zzt, zzt, zzt!`. Energy/silence inspection confirms speech-like audio in its
  neighbor-bounded interval, but Whisper emits no lexical tokens for it.
- The longest unmatched ebook run is 11 tokens and the longest unmatched ASR
  run inside the novel is four tokens. There is no chapter-scale gap or drift.
- All ten chapter transitions occur in 3.5–5.4 second word-free gaps. The first
  book word starts at 00:00:00.840 and the last ends at 03:03:50.700.
- The ASR detects `Grazie a tutti` at 03:04:00.120–03:04:03.400. Because those
  words have no ebook anchors, the final group is not stretched across this
  non-book outro.

Automated validation requires all 1,298 ranges to be present, positive,
strictly ordered, and non-overlapping. It also rechecks the original Italian and
English sentence coverage. The final timestamps still merit a listening review
before destructive audio cutting; no hand-labeled Italian boundary dataset was
available here to calculate absolute millisecond error.

## Reproduction

All Python packages are locked by `uv`:

```bash
uv sync
HF_HOME=$PWD/artifacts/work/huggingface uv run python scripts/transcribe_audio.py
uv run python scripts/build_audio_alignment.py
uv run pytest -q
```

The reusable deliverable is `artifacts/site/viscount-audio-alignment.json`. The large
raw ASR transcript is a regenerable intermediate under `artifacts/work/` and remains
git-ignored.
