"""Create a word-timestamped Whisper transcript for the Italian audiobook."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from viscount_aligner.paths import AUDIO_PATH, TRANSCRIPTION_PATH


DEFAULT_AUDIO = AUDIO_PATH
DEFAULT_OUTPUT = TRANSCRIPTION_PATH
DEFAULT_MODEL = "mlx-community/whisper-large-v3-turbo"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Transcribe the Italian audiobook with MLX Whisper word timestamps."
    )
    parser.add_argument("--audio", type=Path, default=DEFAULT_AUDIO)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    if args.output.exists() and not args.force:
        print(f"Reusing {args.output}; pass --force to transcribe again")
        return

    import mlx_whisper

    result = mlx_whisper.transcribe(
        str(args.audio),
        path_or_hf_repo=args.model,
        language="it",
        task="transcribe",
        word_timestamps=True,
        condition_on_previous_text=False,
        temperature=0.0,
        hallucination_silence_threshold=2.0,
        verbose=False,
    )
    result["_metadata"] = {
        "model": args.model,
        "language": "it",
        "word_timestamps": True,
        "condition_on_previous_text": False,
        "hallucination_silence_threshold": 2.0,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
