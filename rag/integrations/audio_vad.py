from __future__ import annotations

import io
import math
import os
import audioop
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class VadResult:
    has_speech: bool
    dbfs: Optional[float]
    analyzed_seconds: Optional[float]
    speech_ms: Optional[int]
    speech_ratio: Optional[float]
    reason: str


def _dbfs_from_pcm16(pcm: bytes) -> float:
    if not pcm:
        return float("-inf")
    rms = audioop.rms(pcm, 2)  # width=2 for int16
    if rms <= 0:
        return float("-inf")
    return 20.0 * math.log10(rms / 32768.0)


def detect_speech_energy(
    *,
    audio_bytes: bytes,
    filename: str,
    content_type: Optional[str] = None,
) -> VadResult:
    """Best-effort speech detection via energy on decoded PCM.

    Decodes common browser-recorded formats (webm/ogg/wav) using PyAV.

    Env vars:
    - BART_AI_VAD_DBFS_THRESHOLD (default: -45)
    - BART_AI_VAD_MAX_SECONDS (default: 3)
    - BART_AI_VAD_SAMPLE_RATE (default: 16000)
    """

    threshold_dbfs = float(os.environ.get("BART_AI_VAD_DBFS_THRESHOLD", "-45"))
    max_seconds = float(os.environ.get("BART_AI_VAD_MAX_SECONDS", "3"))
    target_rate = int(os.environ.get("BART_AI_VAD_SAMPLE_RATE", "16000"))

    try:
        import av  # type: ignore
    except Exception as exc:  # pragma: no cover
        return VadResult(
            has_speech=True,
            dbfs=None,
            analyzed_seconds=None,
            speech_ms=None,
            speech_ratio=None,
            reason=f"pyav_missing: {exc}",
        )

    try:
        container = av.open(io.BytesIO(audio_bytes), mode="r")
    except Exception as exc:
        # If we can't decode, avoid blocking transcription.
        return VadResult(
            has_speech=True,
            dbfs=None,
            analyzed_seconds=None,
            speech_ms=None,
            speech_ratio=None,
            reason=f"decode_open_failed: {exc}",
        )

    stream = None
    for s in container.streams:
        if s.type == "audio":
            stream = s
            break

    if stream is None:
        return VadResult(
            has_speech=False,
            dbfs=float("-inf"),
            analyzed_seconds=0.0,
            speech_ms=0,
            speech_ratio=0.0,
            reason="no_audio_stream",
        )

    try:
        resampler = av.audio.resampler.AudioResampler(
            format="s16", layout="mono", rate=target_rate
        )
    except Exception as exc:
        return VadResult(
            has_speech=True,
            dbfs=None,
            analyzed_seconds=None,
            speech_ms=None,
            speech_ratio=None,
            reason=f"resampler_failed: {exc}",
        )

    pcm = bytearray()
    max_bytes = int(target_rate * 2 * max_seconds)  # mono int16

    try:
        for frame in container.decode(stream):
            out = resampler.resample(frame)
            frames = out if isinstance(out, list) else [out]
            for f in frames:
                if f is None:
                    continue
                try:
                    pcm.extend(bytes(f.planes[0]))
                except Exception:
                    pass

                if len(pcm) >= max_bytes:
                    raise StopIteration
    except StopIteration:
        pass
    except Exception as exc:
        return VadResult(
            has_speech=True,
            dbfs=None,
            analyzed_seconds=None,
            speech_ms=None,
            speech_ratio=None,
            reason=f"decode_failed: {exc}",
        )
    finally:
        try:
            container.close()
        except Exception:
            pass

    analyzed_seconds = len(pcm) / float(target_rate * 2) if pcm else 0.0
    dbfs = _dbfs_from_pcm16(bytes(pcm))

    # Prefer WebRTC VAD when available; fallback to energy check.
    try:
        import webrtcvad  # type: ignore

        aggressiveness = int(os.environ.get("BART_AI_VAD_AGGRESSIVENESS", "2"))
        aggressiveness = max(0, min(3, aggressiveness))
        vad = webrtcvad.Vad(aggressiveness)

        frame_ms = int(os.environ.get("BART_AI_VAD_FRAME_MS", "30"))
        if frame_ms not in (10, 20, 30):
            frame_ms = 30
        frame_bytes = int(target_rate * (frame_ms / 1000.0) * 2)

        speech_frames = 0
        total_frames = 0
        pcm_bytes = bytes(pcm)
        for i in range(0, len(pcm_bytes) - frame_bytes + 1, frame_bytes):
            frame = pcm_bytes[i : i + frame_bytes]
            total_frames += 1
            try:
                if vad.is_speech(frame, target_rate):
                    speech_frames += 1
            except Exception:
                pass

        speech_ms = speech_frames * frame_ms
        speech_ratio = (speech_frames / total_frames) if total_frames else 0.0

        # Defaults are intentionally forgiving to avoid rejecting short phrases
        # (users often record a short utterance with a bit of silence).
        min_speech_ms = int(os.environ.get("BART_AI_VAD_MIN_SPEECH_MS", "120"))
        min_ratio = float(os.environ.get("BART_AI_VAD_MIN_RATIO", "0.02"))

        has_speech = (speech_ms >= min_speech_ms) and (speech_ratio >= min_ratio)
        return VadResult(
            has_speech=has_speech,
            dbfs=dbfs,
            analyzed_seconds=analyzed_seconds,
            speech_ms=speech_ms,
            speech_ratio=speech_ratio,
            reason=(
                "webrtc_ok"
                if has_speech
                else f"webrtc_no_speech(frames={speech_frames}/{total_frames}, frame_ms={frame_ms})"
            ),
        )
    except Exception:
        has_speech = dbfs >= threshold_dbfs
        return VadResult(
            has_speech=has_speech,
            dbfs=dbfs,
            analyzed_seconds=analyzed_seconds,
            speech_ms=None,
            speech_ratio=None,
            reason="energy_ok" if has_speech else "energy_too_low",
        )


def detect_speech(*, audio_bytes: bytes, filename: str, content_type: Optional[str] = None) -> VadResult:
    """Primary VAD entrypoint used by the API."""

    return detect_speech_energy(audio_bytes=audio_bytes, filename=filename, content_type=content_type)
