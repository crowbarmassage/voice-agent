# STT Integration & Swappable Component Design

Status: design doc, nothing implemented yet. Captures the motivation for adding
a real in-process STT (replacing external Aqua Voice), the features it unlocks,
candidate backends, and a plugin architecture so STT, brain, and TTS can each
be swapped as better models land.

## 1. Why replace Aqua?

Aqua Voice is a system-level dictation tool. It types text into the focused
window, which is fine as a keyboard stand-in but leaves a lot on the table:

- **No barge-in.** Aqua only fires when you trigger it; it's not running while
  the assistant is speaking. There's no way to interrupt a reply mid-sentence.
- **No streaming partials.** We only see the final transcript once Aqua
  decides you're done. The brain can't start thinking until then.
- **No endpointing control.** Aqua decides when you've stopped talking. We
  can't tune that per-use-case (quick commands vs. long dictations).
- **No language signal.** Aqua gives us a string, not a language tag. For the
  Urdu mode work this means we'd have to guess whether to run the brain/TTS
  in English or Urdu, or make the user toggle it manually.
- **No raw audio.** Features like speaker ID, emotion/tone detection, or
  replaying "what did I say?" all require the PCM, not just the text.
- **External dependency.** Aqua is a separate app with its own lifecycle,
  licensing, hotkey, and UI. The pipeline isn't fully self-contained.

A real STT backend running inside the chat process removes all of these.

## 2. Features an in-process STT unlocks

Rough priority order, roughly easiest → hardest.

### 2.1 Tier 1 — table stakes

- **Push-to-talk and open-mic modes.** Hold space to talk (PTT) or run VAD
  continuously (open-mic). Both are trivial once we own the mic stream.
- **VAD-based endpointing.** Silero VAD (tiny, fast, MIT) to decide when the
  user has stopped. Tunable silence window — 300ms for quick commands, 1–2s
  for natural dictation.
- **Streaming partials → earlier brain start.** Most STT backends emit partial
  transcripts every few hundred ms. We can start the brain generation as soon
  as the partial stabilizes (or even speculatively on each partial), shaving
  1–2s of user-perceived latency. Requires the brain to support cancellation
  if the partial changes, which `mlx-lm`'s generator loop can do with a flag.
- **Multilingual input with language auto-detect.** Whisper and SenseVoice
  both emit a language tag. Feed that into brain+TTS selection — solves the
  manual `--language ur` toggle for the Urdu work.
- **No more terminal focus required.** Aqua needs the REPL window focused;
  a background mic thread does not.

### 2.2 Tier 2 — the big unlocks

- **Barge-in (interruption).** While TTS is playing, run VAD on the mic. When
  the user starts speaking, kill the playback stream and drain the audio
  queue. This is the single biggest UX win vs. the current pipeline — you
  can correct the assistant mid-reply instead of waiting for it to finish.
  Requires **acoustic echo cancellation (AEC)** so the TTS coming out of the
  speakers doesn't trip the VAD. Options:
    - Headphones only (trivial; no AEC needed).
    - WebRTC AEC via `webrtc-audio-processing` Python bindings.
    - Speex AEC (older, simpler).
    - Apple's Voice Processing I/O unit (AVAudioEngine `.voiceChat` mode) —
      native AEC+noise suppression on macOS, hardest to wire from Python.
  Recommended first cut: headphones-only mode, flagged `--barge-in`, with a
  note in the README. Add AEC later.
- **Wake word ("hey auntie").** openWakeWord (Apache 2.0) is the obvious
  pick — trainable, runs on CPU in ~1% of a core, no cloud. Lets the chat
  run in the background and wake on phrase.
- **Hot words / custom vocabulary.** Whisper's `initial_prompt` is a crude
  but effective way to bias the decoder toward domain terms, proper nouns,
  model names, etc. Good for "Gemma" not becoming "Jenna".
- **Speaker identification.** Pyannote or SpeechBrain x-vectors to recognize
  who's talking. Useful for multi-user setups or for refusing to respond to
  TV audio / other voices.

### 2.3 Tier 3 — the "why not"

- **Timestamps and subtitle export.** Every Whisper variant gives word-level
  timestamps. Trivially become session subtitles / searchable transcripts.
- **Emotion / paralinguistics.** SenseVoice emits emotion tags
  (happy/sad/angry/neutral). Could feed that into the brain's system prompt
  as a mood signal.
- **Replay last utterance.** Since we keep the PCM, `/replay` is one line.
- **On-device command grammar.** A tiny fast-path STT (Moonshine / Vosk) can
  handle known commands ("stop", "louder", "quit", "reset") in <100ms
  without waking the big model. Run two STTs in parallel: small one for
  commands, big one for dictation.

## 3. STT backend candidates

All are local, Apple Silicon-friendly, and have permissive licenses unless
noted. Real-world latency numbers would need benchmarking on an M-series Mac.

| Backend | Languages | Streaming | Multilingual quality | License | Notes |
|---|---|---|---|---|---|
| **mlx-whisper** (turbo / large-v3) | 99 inc. Urdu | chunked | Strong | MIT | Native MLX, matches brain's stack. `mlx-community/whisper-large-v3-turbo`. Best default candidate. |
| **faster-whisper** (CTranslate2) | 99 inc. Urdu | Good (built-in) | Strong | MIT | CPU or Metal via CT2. Mature streaming API. Heavier dep. |
| **whisper.cpp** | 99 inc. Urdu | Chunked | Strong | MIT | Pure C++, Core ML accel. Python bindings exist but less ergonomic. |
| **SenseVoice** (FunAudioLLM) | 50+ inc. Urdu | Non-streaming (fast) | Strong | Apache 2.0 | Emits language + emotion + event tags. Very fast. Single-shot, so streaming is fake (chunked). |
| **Parakeet** (NVIDIA, MLX ports exist) | English only | Excellent | — | CC BY 4.0 | Best-in-class English latency + accuracy. English-only kills Urdu mode. |
| **Moonshine** (Useful Sensors) | English only | Excellent | — | MIT | Tiny, fast, designed for edge streaming. English-only. |
| **Voxtral** (Mistral) | Multilingual | ? | Strong | Apache 2.0 | Mistral's audio model actually does STT too. Would collapse audio-in and audio-out onto the same vendor. Worth a look since the project is literally named after it. |
| **Canary-1B** (NVIDIA) | 4 (en/de/fr/es) | Good | Strong where supported | CC BY 4.0 | No Urdu. |

**Recommended starting point:**

- **Primary: `mlx-whisper` with `whisper-large-v3-turbo`.** Multilingual
  (Urdu included), MLX-native so it shares the brain's runtime, turbo
  variant is ~4× faster than large-v3 at similar quality, MIT license. The
  "just works with this codebase" pick.
- **Fast command path (optional, later): Moonshine or a distil-whisper
  tiny.** Only if we need sub-200ms command recognition in parallel with
  the big decoder. Probably premature — prove value with one STT first.
- **Watch list:** SenseVoice (for the emotion/language tags) and Voxtral-STT
  (for vendor consolidation).

VAD: **Silero VAD** (`silero-vad` on PyPI). ~2MB, runs on CPU in microseconds,
de facto standard. Nothing to debate here.

Wake word (Tier 2): **openWakeWord**. Custom phrases can be trained from
~100 samples.

## 4. Swappable component architecture

The project already half-does this for TTS (OmniVoice + Voxtral selected by
`--tts-backend`). We should formalize all three axes — **STT, brain, TTS** —
as protocols so a new model is a file, not a refactor.

### 4.1 Core idea

Each component is a *protocol* (a duck-typed interface via `typing.Protocol`)
plus a *registry* mapping a string name to a factory. `chat.py` resolves
`--stt-backend`, `--brain-backend`, `--tts-backend` to factories, instantiates
them, and wires them together. No inheritance, no plugin loader magic — just
a dict per component and small factory modules per backend.

```
chat.py                     # orchestrator, knows nothing model-specific
├── backends/
│   ├── stt/
│   │   ├── __init__.py     # STTBackend protocol + REGISTRY
│   │   ├── mlx_whisper.py
│   │   ├── faster_whisper.py
│   │   └── aqua.py         # legacy shim; reads stdin, no mic
│   ├── brain/
│   │   ├── __init__.py     # BrainBackend protocol + REGISTRY
│   │   ├── gemma_mlx.py    # current brain.py, moved
│   │   └── (future: llama, qwen, claude-api, etc.)
│   └── tts/
│       ├── __init__.py     # TTSBackend protocol + REGISTRY
│       ├── omnivoice.py    # current omnivoice_generate.py, thinned
│       └── voxtral.py      # current generate.py, thinned
```

### 4.2 Proposed protocols

These are sketches — they're the public surface each backend must satisfy.
Actual names and signatures to be pinned during implementation.

```python
# backends/stt/__init__.py
class STTBackend(Protocol):
    """Real-time speech recognizer with VAD-driven endpointing."""

    def start(self) -> None:
        """Open the mic stream and start listening."""

    def stop(self) -> None:
        """Close the mic stream."""

    def utterances(self) -> Iterator[Utterance]:
        """Yield finalized utterances as the user speaks.

        Blocks until the next utterance is available. Returns (text, lang,
        audio_pcm, t_start, t_end). May yield partials first if the backend
        supports them — partials have is_final=False.
        """

    def interrupt_signal(self) -> threading.Event:
        """Event that fires when VAD detects speech onset.

        Used by the playback layer to implement barge-in: the play_worker
        wait()s on this alongside its audio queue.
        """
```

```python
# backends/brain/__init__.py
class BrainBackend(Protocol):
    """Chat model with streaming token output and mid-generation cancel."""

    def reset(self) -> None: ...
    def history(self) -> list[dict]: ...

    def stream(
        self,
        user_text: str,
        *,
        cancel: threading.Event | None = None,
        max_tokens: int = 1024,
    ) -> Iterator[str]:
        """Yield token pieces. Stops early if `cancel` is set."""
```

```python
# backends/tts/__init__.py
class TTSBackend(Protocol):
    """Text-to-speech with a pinned voice persona for the session."""

    sample_rate: int

    def synth(self, text: str, *, language: str | None = None) -> np.ndarray:
        """Return 1-D float32 PCM at self.sample_rate."""

    def close(self) -> None: ...
```

### 4.3 Registry pattern

```python
# backends/stt/__init__.py
REGISTRY: dict[str, Callable[[argparse.Namespace], STTBackend]] = {}

def register(name: str):
    def deco(fn):
        REGISTRY[name] = fn
        return fn
    return deco

# backends/stt/mlx_whisper.py
@register("mlx-whisper")
def build(args) -> STTBackend:
    return MLXWhisperSTT(model=args.stt_model, language=args.language)
```

`chat.py` just does:

```python
stt = stt_backends.REGISTRY[args.stt_backend](args)
brain = brain_backends.REGISTRY[args.brain_backend](args)
tts = tts_backends.REGISTRY[args.tts_backend](args)
```

### 4.4 Migration path (non-breaking)

1. **Move, don't rewrite.** `brain.py` → `backends/brain/gemma_mlx.py`,
   `omnivoice_generate.py` → `backends/tts/omnivoice.py`,
   `generate.py` → `backends/tts/voxtral.py`. Keep top-level shims that
   re-export for the standalone CLIs to keep working.
2. **Add the STT protocol + an `aqua` backend first.** The `aqua` backend
   just reads from stdin — it's a no-op stub that matches today's behavior
   and validates the interface before a real STT is wired in.
3. **Add `mlx-whisper` as the second STT backend.** Mic via sounddevice,
   Silero VAD for endpointing, utterances pumped onto a queue that `chat.py`
   reads instead of `input()`. Gate behind `--stt-backend mlx-whisper` so
   `aqua` stays default until the new path is solid.
4. **Rewire the brain loop to accept a cancel event.** Needed for barge-in
   and for speculative partials. `mlx_lm.generate` supports early stopping
   via its stream iterator — check the token budget + cancel flag every
   step.
5. **Barge-in in the playback layer.** `play_worker` already owns the
   `sd.OutputStream`. Give it an `interrupt` event from the STT backend;
   when fired, drain the audio queue and call `stream.abort()`.
6. **Flip the default.** Once `mlx-whisper` + barge-in are stable, make it
   the default and demote `aqua` to a fallback.

Each step is independently shippable and reversible.

## 5. Multilingual / Urdu specifics

Tying into the in-progress Urdu work:

- Whisper and SenseVoice both detect language per-utterance. The STT
  backend should emit the detected language tag on every utterance.
- `chat.py` can then: (a) pass that tag to the TTS `synth(language=...)`
  call, and (b) optionally append a short system-prompt nudge to the brain
  ("Reply in Urdu.") so Gemma stays in the user's language without the user
  setting a global flag. This is strictly better than the `--language ur`
  startup flag approach — it handles code-switching (user speaks English
  one turn, Urdu the next) for free.
- Caveats:
    - Whisper's Urdu detection is decent but not flawless; short English
      utterances in an Urdu session can be misflagged. A small hysteresis
      (stay in the previous language unless 2 consecutive utterances
      disagree) smooths this out.
    - OmniVoice cross-lingual cloning quality from an English reference is
      an open question — see the standalone Urdu test we just did. If the
      reference voice is always English but output is often Urdu, we may
      want per-language reference WAVs: `auntie_en.wav` + `auntie_ur.wav`
      generated once and selected by the detected tag.

## 6. Open questions

- **AEC:** is headphones-only barge-in acceptable for v1? Almost certainly
  yes for solo desk use, no for a room setup.
- **Wake word:** needed, or does PTT + open-mic-with-timeout cover it?
- **Command fast-path:** worth the complexity of running two STTs in
  parallel, or should one good STT handle everything?
- **Voxtral-as-STT:** does using Mistral's audio model for *both* STT and
  TTS simplify the stack (one model family, one weight set) or complicate
  it (weaker than best-in-class for each role)? Worth a benchmark spike.
- **Brain cancellation:** mlx-lm's generate loop supports it but the current
  `brain.py` wrapper doesn't expose a cancel handle. One-evening refactor.
- **Session transcripts:** now that we have audio + text aligned, is a
  persistent session log worth building? (Ties into the "history is
  in-memory only" known limitation in README.)

## 7. Recommended next steps

In order, smallest first:

1. **Benchmark mlx-whisper-large-v3-turbo on this machine.** Cold-load
   time, warm RTF on a 5s clip, VRAM footprint alongside Gemma-4. Decides
   whether it's viable to keep both hot simultaneously.
2. **Extract the backend protocols and do the move-don't-rewrite refactor.**
   No behavior change, just the new layout + an `aqua`/stdin STT stub.
3. **Wire mlx-whisper + Silero VAD as a second STT backend.** PTT mode
   first (spacebar hold), then open-mic with VAD endpointing.
4. **Add language tagging** from the STT all the way through to TTS.
   Deprecate the `--language` startup flag in favor of auto-detect.
5. **Barge-in with headphones-only caveat.** Mark as experimental.
6. **Then** evaluate wake word, AEC, speaker ID, emotion tags — each on
   its own merits.
