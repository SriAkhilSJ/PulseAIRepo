---
name: speech-architect
description: Architect-level speech system design — streaming versus batch transcription, latency budgets for voice UX, diarisation and timestamps, text-to-speech quality and voice choice, telephony constraints, and the privacy handling that audio demands. Use when a product listens or speaks.
license: MIT
compatibility: Whisper, Deepgram, AssemblyAI, Azure Speech, ElevenLabs, Pipecat
metadata:
  crusor-domain: ai-ml-architect
  crusor-path: ai-ml-architect/serving-architect/speech-architect
  crusor-origin: original
  crusor-sources: "platform.openai.com/docs/guides/speech-to-text; developers.deepgram.com; cloud.google.com/speech-to-text/docs"
  crusor-triggers: "speech to text, whisper, text to speech, voice agent, diarization, realtime audio, telephony, asr, tts, transcribe, transcription, voice notes"
  crusor-verified-on: "2026-10-30"
---

# Speech Architect

Speech is **a latency problem with a privacy surface**. Users forgive a wrong word;
they do not forgive a three-second pause.

## When to use

- Voice interfaces, meeting transcription, call analytics, accessibility.
- Text-to-speech for products, IVR, or narration.
- Any pipeline where audio is an input or an output.

## When NOT to use

- The product can be typed — voice adds cost, latency, and privacy burden.
- Pre-recorded, scripted audio that a human should record.

## Decision 1 — Mode

| Mode | Latency | Use |
|---|---|---|
| batch file transcription | minutes | archives, meetings, compliance |
| near-real-time (chunked) | seconds | captions, call analytics |
| streaming (bidirectional) | sub-second | voice agents, live captions |

- Voice agents need end-to-end budgets: VAD + ASR + LLM + TTS. Typical targets:
  ASR partial < 300 ms, full turn < 1.2 s.
- Batch is dramatically cheaper; do not stream what can wait.

## Decision 2 — ASR

- Choose on word error rate **for your audio**: accents, telephony 8 kHz, noise,
  domain vocabulary.
- Custom vocabulary/keyterms for product names, codes, and jargon — cheap accuracy
  win.
- Timestamps and speaker labels (diarisation) if the output is searchable or
  auditable.
- Punctuation and casing matter for downstream LLM quality; enable them.
- Handle code-switching and non-English locales explicitly.

## Decision 3 — TTS

- Voice choice is product identity; audition on real sentences, not marketing copy.
- Streaming synthesis for responsiveness; buffer the first sentence.
- Prosody and SSML support decide whether numbers, dates, and abbreviations sound
  right.
- Latency per character matters; long texts should stream in chunks.

## Decision 4 — Pipeline and turn-taking

- VAD for endpointing; barge-in support so users can interrupt.
- Echo cancellation on the client; without it, the agent hears itself.
- Fallback: if ASR confidence is low, ask a clarifying question rather than guessing.
- Transcript is the source of truth for downstream LLM calls; store it with
  timestamps.

## Decision 5 — Privacy and storage

- Audio is highly identifiable: consent, retention, and deletion rules are stricter
  than text.
- Encrypt at rest, restrict access by role, and prefer short retention with derived
  transcripts only.
- Redact PII in stored transcripts where feasible.
- Note jurisdictional rules for call recording (two-party consent).

## Decision 6 — Cost

- Billed per minute of audio, not per word — silence and hold music are billed time.
- Trim silence, chunk long files, and avoid re-transcribing unchanged audio.
- TTS bills per character; cache repeated phrases (prompts, menus).
- Compare providers on cost per minute at your actual error rate.

## Failure modes at scale

- Streaming ASR used for a nightly batch job; 10× the cost, no benefit.
- No keyword boosting; product names transcribed as gibberish and LLM answers
  wrongly.
- Echo cancellation missing; the agent responds to its own speech.
- Audio retained indefinitely "for quality"; a privacy review fails.
- Hold music transcribed and sent to the LLM as user input.

## Verification receipts

1. Mode choice with the latency budget per stage.
2. WER measured on a sample of your real audio, per accent/locale.
3. Voice-agent turn latency measured end to end (p50/p95).
4. Retention and consent policy applied, with deletion verified.
5. Cost per audio minute and per TTS character at current volume.
