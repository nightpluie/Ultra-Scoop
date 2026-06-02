#!/usr/bin/env python3
from __future__ import annotations
"""
記者會殺手 專用 Whisper 引擎
（由 gui_whisper_live.py 精簡而來，僅保留 LiveTranscriber 所需部分）
"""

import threading
import queue
import wave
import numpy as np

# ── Dependency checks ──────────────────────────────────────────────────────────

def _has(module: str) -> bool:
    try:
        __import__(module)
        return True
    except ImportError:
        return False

HAS_SOUNDDEVICE = _has("sounddevice")
HAS_MLX_WHISPER = _has("mlx_whisper")
HAS_SILERO_VAD  = _has("silero_vad")
HAS_PYANNOTE    = _has("pyannote.audio")

# ── Constants ──────────────────────────────────────────────────────────────────

SAMPLE_RATE    = 16000
CHUNK_SECONDS  = 10
SILENCE_RMS    = 0.005

WHISPER_MODELS = ["tiny", "base", "small", "medium", "large-v2", "large-v3", "large-v3-turbo", "turbo"]
LANGUAGES      = ["auto", "zh", "en", "ja", "fr", "de", "es", "ko", "ru", "it"]

MLX_MODEL_MAP = {
    "tiny":           "mlx-community/whisper-tiny",
    "base":           "mlx-community/whisper-base-mlx",
    "small":          "mlx-community/whisper-small-mlx",
    "medium":         "mlx-community/whisper-medium",
    "large-v2":       "mlx-community/whisper-large-v2-mlx",
    "large-v3":       "mlx-community/whisper-large-v3-mlx",
    "large-v3-turbo": "mlx-community/whisper-large-v3-turbo",
    "turbo":          "mlx-community/whisper-turbo",
}

# ── Silero VAD (module-level, lazy-loaded) ─────────────────────────────────────

_vad_model_cache = None
_vad_model_lock  = threading.Lock()


def _get_vad_model():
    global _vad_model_cache
    if _vad_model_cache is None:
        with _vad_model_lock:
            if _vad_model_cache is None:
                from silero_vad import load_silero_vad
                _vad_model_cache = load_silero_vad()
    return _vad_model_cache


def vad_filter(audio_np: np.ndarray,
               sample_rate: int = SAMPLE_RATE
               ) -> tuple[np.ndarray | None, list[tuple[float, float]]]:
    """
    Silero VAD 過濾。
    回傳 (filtered_audio, offset_map)：
      filtered_audio  — 拼接後的語音段（float32），若全靜音則為 None
      offset_map      — [(concat_start_s, orig_start_s), ...] 供時間碼還原用
    """
    import torch
    from silero_vad import get_speech_timestamps

    wav = torch.from_numpy(audio_np)
    speeches = get_speech_timestamps(
        wav, _get_vad_model(),
        return_seconds=True,
        sampling_rate=sample_rate,
        min_silence_duration_ms=500,
        min_speech_duration_ms=250,
        speech_pad_ms=200,
    )

    if not speeches:
        return None, []

    chunks: list[np.ndarray] = []
    offset_map: list[tuple[float, float]] = []
    cursor = 0.0
    for seg in speeches:
        s, e = seg["start"], seg["end"]
        chunks.append(audio_np[int(s * sample_rate): int(e * sample_rate)])
        offset_map.append((cursor, s))
        cursor += e - s

    return np.concatenate(chunks), offset_map


def remap_timestamps(segs: list[tuple[float, float, str]],
                     offset_map: list[tuple[float, float]]
                     ) -> list[tuple[float, float, str]]:
    """把 concat 時間碼還原成原始音檔時間碼。"""
    if not offset_map:
        return segs

    def orig(t: float) -> float:
        for i, (cs, os) in enumerate(offset_map):
            next_cs = offset_map[i + 1][0] if i + 1 < len(offset_map) else float("inf")
            if cs <= t < next_cs:
                return os + (t - cs)
        return t

    return [(orig(s), orig(e), txt) for s, e, txt in segs]

SPEAKER_PALETTE = [
    "#1565C0",  # 藍
    "#B71C1C",  # 紅
    "#2E7D32",  # 綠
    "#E65100",  # 橘
    "#6A1B9A",  # 紫
    "#00695C",  # 青
    "#4E342E",  # 棕
    "#37474F",  # 灰
]

# ── Live transcription engine ──────────────────────────────────────────────────

class LiveTranscriber:
    """在獨立 thread 中執行即時轉錄與說話者辨識。"""

    def __init__(self, *, device_index, model_name, language,
                 diarize, hf_token,
                 on_segment, on_status, on_error, on_done,
                 audio_save_path: str | None = None):
        self.device_index    = device_index
        self.model_name      = model_name
        self.language        = None if language == "auto" else language
        self.diarize         = diarize
        self.hf_token        = hf_token.strip()
        self.on_segment      = on_segment
        self.on_status       = on_status
        self.on_error        = on_error
        self.on_done         = on_done
        self._audio_save_path = audio_save_path

        self._stop         = threading.Event()
        self._audio_q      = queue.Queue()
        self._buffer       = np.array([], dtype=np.float32)
        self._whisper      = None
        self._diarize_pipe = None
        self._speaker_map  = {}
        self._speaker_idx  = 0
        self._wav_file     = None

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def stop(self):
        self._stop.set()

    def _load_models(self):
        self.on_status("載入 Whisper 模型中…")
        if not HAS_MLX_WHISPER:
            raise RuntimeError("找不到 mlx-whisper 套件\n請執行：pip install mlx-whisper")
        repo = MLX_MODEL_MAP.get(
            self.model_name,
            f"mlx-community/whisper-{self.model_name}"
        )
        self._whisper = ("mlx", repo)

        if self.diarize:
            if not HAS_PYANNOTE:
                raise RuntimeError("找不到 pyannote.audio\n請執行：pip install pyannote.audio torch")
            if not self.hf_token:
                raise RuntimeError("說話者辨識需要填入 HuggingFace Token")
            self.on_status("載入說話者辨識模型中（首次約需幾分鐘下載）…")
            from pyannote.audio import Pipeline
            self._diarize_pipe = Pipeline.from_pretrained(
                "pyannote/speaker-diarization-3.1",
                token=self.hf_token,
            )

    def _audio_cb(self, indata, frames, time_info, status):
        self._audio_q.put(indata[:, 0].copy())

    def _transcribe(self, audio: np.ndarray) -> list[tuple[float, float, str]]:
        kind, repo = self._whisper
        import mlx_whisper

        if HAS_SILERO_VAD:
            filtered, offset_map = vad_filter(audio)
            if filtered is None:
                return []
            transcribe_audio = filtered
        else:
            transcribe_audio = audio
            offset_map = []

        result = mlx_whisper.transcribe(
            transcribe_audio,
            path_or_hf_repo=repo,
            language=self.language,
            verbose=False,
        )
        raw = [
            (s["start"], s["end"], s["text"].strip())
            for s in result.get("segments", [])
            if s["text"].strip()
        ]
        return remap_timestamps(raw, offset_map)

    def _assign_speakers(self, audio: np.ndarray,
                         segs: list[tuple]) -> list[tuple[float, float, str, str]]:
        import torch
        waveform = torch.from_numpy(audio).unsqueeze(0)
        try:
            diarization = self._diarize_pipe({"waveform": waveform, "sample_rate": SAMPLE_RATE})
            timeline = []
            for turn, _, spk in diarization.itertracks(yield_label=True):
                if spk not in self._speaker_map:
                    self._speaker_idx += 1
                    self._speaker_map[spk] = f"說話者 {self._speaker_idx}"
                timeline.append((turn.start, turn.end, self._speaker_map[spk]))
        except Exception:
            timeline = []

        result = []
        for start, end, text in segs:
            mid = (start + end) / 2
            speaker = "說話者 1"
            for s, e, lbl in timeline:
                if s <= mid <= e:
                    speaker = lbl
                    break
            result.append((start, end, text, speaker))
        return result

    def _run(self):
        try:
            self._load_models()
        except Exception as exc:
            self.on_error(str(exc))
            self.on_done()
            return

        import sounddevice as sd
        self.on_status("即時轉錄中…")

        if self._audio_save_path:
            try:
                self._wav_file = wave.open(self._audio_save_path, "wb")
                self._wav_file.setnchannels(1)
                self._wav_file.setsampwidth(2)   # 16-bit PCM
                self._wav_file.setframerate(SAMPLE_RATE)
            except Exception:
                self._wav_file = None

        try:
            with sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="float32",
                device=self.device_index,
                callback=self._audio_cb,
                blocksize=int(SAMPLE_RATE * 0.1),
            ):
                while not self._stop.is_set():
                    try:
                        chunk = self._audio_q.get(timeout=0.1)
                        self._buffer = np.concatenate([self._buffer, chunk])
                    except queue.Empty:
                        continue

                    if len(self._buffer) < SAMPLE_RATE * CHUNK_SECONDS:
                        continue

                    audio = self._buffer.copy()
                    self._buffer = np.array([], dtype=np.float32)

                    if self._wav_file:
                        try:
                            pcm = (audio * 32767).clip(-32768, 32767).astype(np.int16)
                            self._wav_file.writeframes(pcm.tobytes())
                        except Exception:
                            pass

                    if np.sqrt(np.mean(audio ** 2)) < SILENCE_RMS:
                        continue

                    try:
                        segs = self._transcribe(audio)
                        if not segs:
                            continue
                        if self.diarize and self._diarize_pipe:
                            labeled = self._assign_speakers(audio, segs)
                            for _, _, text, spk in labeled:
                                if text:
                                    self.on_segment(text, spk)
                        else:
                            for _, _, text in segs:
                                if text:
                                    self.on_segment(text, None)
                    except Exception as exc:
                        self.on_error(f"處理錯誤：{exc}")

        except Exception as exc:
            self.on_error(f"音訊串流錯誤：{exc}")
        finally:
            if self._wav_file:
                try:
                    self._wav_file.close()
                except Exception:
                    pass
                self._wav_file = None
            self.on_done()
