"""Granite 4.0 1b Speech STT backend.

IBM Granite speech-LLM via transformers (PyTorch). Best-in-class English WER,
native keyword biasing via prompt injection, Apache 2.0, ungated. 1B params.

Model: ibm-granite/granite-4.0-1b-speech
Weights: ~/Github/models/granite-4.0-1b-speech/ (local) or HuggingFace hub

Expects 16kHz mono PCM input. For telephony (8kHz G.711), the audio pipeline
resamples to 16kHz before feeding this backend.

Streaming approach: buffers incoming audio chunks, runs inference when VAD
detects end-of-utterance (or a time/size threshold is hit), and yields
Utterance objects. This is "chunked streaming" — not true frame-by-frame
streaming, but sufficient for telephony turn-taking where utterances are
naturally bounded by pauses.

Adapted from ~/Github/models/transcribe.py (batch transcriber).

See docs/TIER1_FEATURES.md §C1, §F5.
"""
from __future__ import annotations

import gc
import sys
import time
from collections.abc import AsyncIterator
from pathlib import Path

import numpy as np
import torch

from voice_agent.logging import get_logger
from voice_agent.metrics import metrics
from voice_agent.stt import Utterance

log = get_logger(__name__)

# Default model path — local weights preferred, falls back to HuggingFace
DEFAULT_MODEL_PATH = str(Path.home() / "Github/models/granite-4.0-1b-speech")
HF_MODEL_ID = "ibm-granite/granite-4.0-1b-speech"

DEFAULT_PROMPT = (
    "Transcribe this audio verbatim. This is a phone call about "
    "healthcare billing and insurance claims."
)

# Chunked streaming config
MAX_BUFFER_SECONDS = 10.0  # max audio to buffer before forcing inference
MIN_SILENCE_SECONDS = 1.5  # silence duration to trigger end-of-utterance


def _get_device() -> str:
    if torch.cuda.is_available():
        return "cuda"
    elif torch.backends.mps.is_available():
        return "mps"
    return "cpu"


class GraniteSTT:
    """Granite Speech STT implementation of STTBackend protocol.

    Loads the model on start(), buffers audio chunks, and runs inference
    on utterance boundaries detected by silence thresholds.
    """

    def __init__(
        self,
        model_path: str | None = None,
        device: str | None = None,
        prompt: str = DEFAULT_PROMPT,
        max_new_tokens: int = 200,
        num_beams: int = 2,
        repetition_penalty: float = 3.5,
    ):
        self._model_path = model_path or DEFAULT_MODEL_PATH
        self._device = device or _get_device()
        self._prompt_text = prompt
        self._max_new_tokens = max_new_tokens
        self._num_beams = num_beams
        self._repetition_penalty = repetition_penalty

        self._model = None
        self._processor = None
        self._tokenizer = None
        self._prompt: str | None = None
        self._keywords: list[str] = []

    async def start(self) -> None:
        """Load the Granite Speech model. Call once before transcribing."""
        from transformers import AutoConfig, AutoModelForSpeechSeq2Seq, AutoProcessor

        model_path = self._model_path
        if not Path(model_path).exists():
            log.info("granite_model_not_local, using HuggingFace", model_id=HF_MODEL_ID)
            model_path = HF_MODEL_ID

        log.info("granite_loading", model_path=model_path, device=self._device)
        t0 = time.monotonic()

        # Patch config: embedding_multiplier must be float
        config = AutoConfig.from_pretrained(model_path)
        if hasattr(config, "text_config") and isinstance(config.text_config, dict):
            if "embedding_multiplier" in config.text_config:
                config.text_config["embedding_multiplier"] = float(
                    config.text_config["embedding_multiplier"]
                )

        self._processor = AutoProcessor.from_pretrained(model_path)
        self._tokenizer = self._processor.tokenizer

        self._model = AutoModelForSpeechSeq2Seq.from_pretrained(
            model_path,
            config=config,
            torch_dtype=torch.float32,
            low_cpu_mem_usage=True,
        ).to(self._device)
        self._model.eval()

        # Pre-build prompt
        self._prompt = self._build_prompt()

        elapsed = time.monotonic() - t0
        log.info("granite_loaded", elapsed_s=round(elapsed, 2))
        metrics.record_timer("stt_model_load_ms", elapsed * 1000)

    def set_keywords(self, keywords: list[str]) -> None:
        """Add keyword hints to the transcription prompt.

        Granite supports keyword biasing by injecting terms into the prompt.
        Useful for medical terms: "CARC", "RARC", "NPI", payor names, etc.
        """
        self._keywords = keywords
        if self._tokenizer is not None:
            self._prompt = self._build_prompt()

    async def transcribe_stream(
        self, audio_stream: AsyncIterator[bytes], sample_rate: int
    ) -> AsyncIterator[Utterance]:
        """Transcribe a continuous audio stream using chunked inference.

        Buffers PCM audio, detects utterance boundaries via silence, and
        runs Granite inference on each utterance. Yields Utterance objects.

        Args:
            audio_stream: Async iterator of PCM int16 audio chunks at sample_rate.
            sample_rate: Sample rate of incoming audio (should be 16000).
        """
        if self._model is None:
            raise RuntimeError("Call start() before transcribe_stream()")

        buffer = np.array([], dtype=np.float32)
        stream_start = time.monotonic()
        silence_frames = 0
        samples_per_frame = int(sample_rate * 0.03)  # 30ms frames
        silence_threshold = int(MIN_SILENCE_SECONDS / 0.03)
        energy_threshold = 0.01  # RMS threshold for silence detection

        async for chunk in audio_stream:
            # Convert bytes (int16 PCM) to float32
            audio_i16 = np.frombuffer(chunk, dtype=np.int16)
            audio_f32 = audio_i16.astype(np.float32) / 32768.0
            buffer = np.concatenate([buffer, audio_f32])

            # Simple energy-based silence detection (frame by frame)
            while len(audio_f32) >= samples_per_frame:
                frame = audio_f32[:samples_per_frame]
                audio_f32 = audio_f32[samples_per_frame:]
                rms = np.sqrt(np.mean(frame ** 2))
                if rms < energy_threshold:
                    silence_frames += 1
                else:
                    silence_frames = 0

            buffer_duration = len(buffer) / sample_rate

            # Trigger inference on silence or max buffer
            should_infer = (
                (silence_frames >= silence_threshold and buffer_duration > 0.5)
                or buffer_duration >= MAX_BUFFER_SECONDS
            )

            if should_infer and len(buffer) > 0:
                utterance_start = time.monotonic() - stream_start - buffer_duration
                utterance = await self._transcribe_buffer(
                    buffer, sample_rate, utterance_start
                )
                if utterance and utterance.text.strip():
                    yield utterance

                buffer = np.array([], dtype=np.float32)
                silence_frames = 0

        # Flush remaining buffer
        if len(buffer) > sample_rate * 0.3:  # at least 300ms
            utterance_start = time.monotonic() - stream_start - len(buffer) / sample_rate
            utterance = await self._transcribe_buffer(
                buffer, sample_rate, utterance_start
            )
            if utterance and utterance.text.strip():
                yield utterance

    async def _transcribe_buffer(
        self, audio: np.ndarray, sample_rate: int, start_time: float
    ) -> Utterance | None:
        """Run Granite inference on a buffered audio segment."""
        t0 = time.monotonic()
        duration = len(audio) / sample_rate

        # Granite expects (1, N) float32 tensor
        wav_tensor = torch.from_numpy(audio).unsqueeze(0)

        try:
            model_inputs = self._processor(
                self._prompt, wav_tensor, device=self._device, return_tensors="pt"
            ).to(self._device)

            with torch.no_grad():
                model_outputs = self._model.generate(
                    **model_inputs,
                    max_new_tokens=self._max_new_tokens,
                    num_beams=self._num_beams,
                    do_sample=False,
                    repetition_penalty=self._repetition_penalty,
                    length_penalty=1.0,
                    temperature=1.0,
                    bos_token_id=self._tokenizer.bos_token_id,
                    eos_token_id=self._tokenizer.eos_token_id,
                    pad_token_id=self._tokenizer.pad_token_id,
                )

            num_input_tokens = model_inputs["input_ids"].shape[-1]
            new_tokens = model_outputs[0, num_input_tokens:]
            text = self._tokenizer.batch_decode(
                new_tokens.unsqueeze(0),
                add_special_tokens=False,
                skip_special_tokens=True,
            )[0].strip()

            elapsed = time.monotonic() - t0
            rtf = elapsed / duration if duration > 0 else float("inf")

            log.debug(
                "granite_transcribed",
                text=text[:100],
                duration_s=round(duration, 2),
                elapsed_s=round(elapsed, 2),
                rtf=round(rtf, 3),
            )
            metrics.record_timer("stt_inference_ms", elapsed * 1000)
            metrics.inc("stt_utterances")

            return Utterance(
                text=text,
                confidence=0.85,  # Granite doesn't expose per-utterance confidence;
                # use a reasonable default, flag low-confidence via downstream checks
                is_final=True,
                start_time=max(0, start_time),
                end_time=start_time + duration,
            )

        except Exception as e:
            log.error("granite_transcribe_error", error=str(e))
            metrics.inc("stt_errors")
            return None
        finally:
            if self._device == "mps":
                torch.mps.empty_cache()
            gc.collect()

    async def stop(self) -> None:
        """Release model resources."""
        self._model = None
        self._processor = None
        self._tokenizer = None
        if torch.backends.mps.is_available():
            torch.mps.empty_cache()
        gc.collect()
        log.info("granite_stopped")

    def _build_prompt(self) -> str:
        """Build the chat-template prompt for Granite, with optional keyword hints."""
        prompt_text = self._prompt_text
        if self._keywords:
            kw_str = ", ".join(self._keywords)
            prompt_text += f" Key terms: {kw_str}."

        content = f"<|audio|>{prompt_text}"
        chat = [{"role": "user", "content": content}]
        return self._tokenizer.apply_chat_template(
            chat, tokenize=False, add_generation_prompt=True
        )
