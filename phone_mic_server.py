#!/usr/bin/env python3
from __future__ import annotations
"""
記者會殺手 — 手機麥克風模組
手機當遠端麥克風，音訊透過本機 WiFi 串流至筆電 Whisper 引擎。
"""

import os, sys, socket, threading, queue, tempfile, time, json, wave, datetime, ipaddress
import numpy as np

# ── ffmpeg：系統沒裝就改用 pip 自帶版本，確保手機麥克風轉錄可用 ────────────────
try:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from ffmpeg_setup import ensure_ffmpeg_on_path
    ensure_ffmpeg_on_path()
except Exception:
    pass

# ── 常數 ───────────────────────────────────────────────────────────────────────
DEFAULT_PORT = 8765

# ── SSL 憑證（持久自簽，含 IP SAN，讓 iOS Safari 顯示「繼續前往」選項）──────────

_CERT_DIR = os.path.dirname(os.path.abspath(__file__))
_CERT_PATH = os.path.join(_CERT_DIR, "ssl_cert.pem")
_KEY_PATH  = os.path.join(_CERT_DIR, "ssl_key.pem")


def _ssl_cert_valid_for(ip: str) -> bool:
    """回傳現有憑證是否仍適用於此 IP 且距到期超過 30 天。"""
    if not (os.path.exists(_CERT_PATH) and os.path.exists(_KEY_PATH)):
        return False
    try:
        from cryptography import x509
        with open(_CERT_PATH, "rb") as f:
            cert = x509.load_pem_x509_certificate(f.read())
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
        ips = [str(i) for i in san.value.get_values_for_type(x509.IPAddress)]
        if ip not in ips:
            return False
        try:
            expiry = cert.not_valid_after_utc
            now    = datetime.datetime.now(datetime.timezone.utc)
        except AttributeError:
            expiry = cert.not_valid_after
            now    = datetime.datetime.utcnow()
        return (expiry - now).days > 30
    except Exception:
        return False


def _generate_ssl_cert(ip: str):
    """生成含 IP SAN 的自簽憑證，存為 ssl_cert.pem / ssl_key.pem。"""
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.backends import default_backend

    key = rsa.generate_private_key(
        public_exponent=65537, key_size=2048, backend=default_backend()
    )
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "UltraScoop")])
    try:
        now = datetime.datetime.now(datetime.timezone.utc)
    except Exception:
        now = datetime.datetime.utcnow()

    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=825))
        .add_extension(
            x509.SubjectAlternativeName([
                x509.IPAddress(ipaddress.IPv4Address(ip)),
                x509.DNSName("localhost"),
            ]),
            critical=False,
        )
        .sign(key, hashes.SHA256(), default_backend())
    )
    with open(_CERT_PATH, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
    with open(_KEY_PATH, "wb") as f:
        f.write(key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption()
        ))


def _ensure_ssl_cert(ip: str) -> tuple:
    """確保 ssl_cert.pem / ssl_key.pem 存在且適用於此 IP，回傳 (cert, key) 路徑。"""
    if not _ssl_cert_valid_for(ip):
        _generate_ssl_cert(ip)
    return _CERT_PATH, _KEY_PATH


# ── 工具函式 ───────────────────────────────────────────────────────────────────

def _get_local_ip() -> str:
    """取得本機在目前網路上的 IP（連接到手機熱點後即為熱點分配的 IP）。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def ensure_server_running(port: int = DEFAULT_PORT):
    """勾選手機麥克風時立即啟動伺服器（background thread），讓手機掃 QR 後能看到頁面。"""
    threading.Thread(target=lambda: _get_server(port), daemon=True).start()


def make_qr_image_tk(url: str):
    """生成 QR Code 的 tkinter PhotoImage；若缺少套件則回傳 None。"""
    try:
        import qrcode
        from PIL import ImageTk
        qr = qrcode.QRCode(box_size=3, border=2)
        qr.add_data(url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="#0F1923", back_color="white")
        return ImageTk.PhotoImage(img)
    except ImportError:
        return None


# ── Flask 伺服器（module-level singleton，只啟動一次）─────────────────────────

_server_instance: _FlaskServer | None = None
_server_lock = threading.Lock()


class _FlaskServer:
    """輕量 HTTP 伺服器：接收手機音訊，推送 SSE 逐字稿與狀態事件。"""

    def __init__(self, port: int):
        self.port = port
        self.on_chunk         = None   # callable(path, scene)
        self.on_phone_stopped = None   # 手機按停止時呼叫
        self._sse_queues: list[queue.Queue] = []
        self._sse_lock = threading.Lock()
        self._start()

    def broadcast_state(self, state: str):
        """推送筆電狀態給所有在線手機（state: armed / recording / stopped）。"""
        msg = {"_type": "state", "state": state}
        with self._sse_lock:
            for q in list(self._sse_queues):
                try:
                    q.put_nowait(msg)
                except queue.Full:
                    pass

    def _start(self):
        from flask import Flask, request, Response, stream_with_context
        import logging
        logging.getLogger("werkzeug").setLevel(logging.ERROR)

        app = Flask(__name__)
        srv = self

        @app.route("/")
        def index():
            return _PHONE_HTML, 200, {"Content-Type": "text/html; charset=utf-8"}

        @app.route("/chunk", methods=["POST"])
        def chunk():
            if srv.on_chunk is None:
                return "not recording", 503
            audio_file = request.files.get("audio")
            scene = request.form.get("scene", "")
            if not audio_file:
                return "no audio", 400
            # 依副檔名存暫存檔，讓 mlx-whisper 正確解碼
            suffix = ".webm"
            if audio_file.filename:
                ext = os.path.splitext(audio_file.filename)[1]
                if ext:
                    suffix = ext
            tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
            audio_file.save(tmp.name)
            tmp.close()
            srv.on_chunk(tmp.name, scene)
            return "ok"

        @app.route("/phone_stop", methods=["POST"])
        def phone_stop():
            if srv.on_phone_stopped:
                srv.on_phone_stopped()
            return "ok"

        @app.route("/transcript")
        def transcript():
            q: queue.Queue = queue.Queue(maxsize=200)
            with srv._sse_lock:
                srv._sse_queues.append(q)

            def generate():
                try:
                    while True:
                        try:
                            msg = q.get(timeout=15)
                            if msg is None:
                                break
                            if isinstance(msg, dict) and msg.get("_type") == "state":
                                # 狀態事件（named event "state"）
                                yield (f"event: state\n"
                                       f"data: {json.dumps({'state': msg['state']}, ensure_ascii=False)}\n\n")
                            else:
                                # 逐字稿事件（named event "transcript"）
                                yield (f"event: transcript\n"
                                       f"data: {json.dumps({'text': msg}, ensure_ascii=False)}\n\n")
                        except queue.Empty:
                            yield ": keepalive\n\n"
                finally:
                    with srv._sse_lock:
                        if q in srv._sse_queues:
                            srv._sse_queues.remove(q)

            return Response(
                stream_with_context(generate()),
                mimetype="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )

        local_ip = _get_local_ip()
        cert_path, key_path = _ensure_ssl_cert(local_ip)
        threading.Thread(
            target=lambda: app.run(
                host="0.0.0.0", port=self.port,
                threaded=True, use_reloader=False,
                ssl_context=(cert_path, key_path)
            ),
            daemon=True,
        ).start()
        time.sleep(0.4)

    def broadcast(self, text: str):
        """將逐字稿文字推送給所有在線手機。"""
        with self._sse_lock:
            for q in list(self._sse_queues):
                try:
                    q.put_nowait(text)   # 字串 → transcript 事件
                except queue.Full:
                    pass


def _get_server(port: int = DEFAULT_PORT) -> _FlaskServer:
    global _server_instance
    with _server_lock:
        if _server_instance is None:
            _server_instance = _FlaskServer(port)
        return _server_instance


# ── PhoneMicTranscriber ────────────────────────────────────────────────────────

class PhoneMicTranscriber:
    """
    與 LiveTranscriber 相同介面的手機麥克風版本。
    啟動後手機瀏覽器連線即可錄音，音訊串流至本機 Whisper 轉錄。
    """

    def __init__(self, *, model_name, language,
                 on_segment, on_status, on_error, on_done,
                 on_phone_started=None, on_phone_stopped=None,
                 port: int = DEFAULT_PORT,
                 audio_save_path: str | None = None):
        self.model_name        = model_name
        self.language          = None if language == "auto" else language
        self.on_segment        = on_segment
        self.on_status         = on_status
        self.on_error          = on_error
        self.on_done           = on_done
        self.on_phone_started  = on_phone_started   # 手機第一個 chunk 到達
        self.on_phone_stopped  = on_phone_stopped   # 手機按停止
        self.port              = port
        self._audio_save_path  = audio_save_path

        self._stop    = threading.Event()
        self._chunk_q: queue.Queue = queue.Queue()
        self._whisper = None
        self._wav_file = None
        self.last_scene: str = ""   # 手機輸入的記者會名稱，供存檔用

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def stop(self):
        self._stop.set()
        srv = _get_server(self.port)
        srv.on_chunk         = None
        srv.on_phone_stopped = None
        srv.broadcast_state("stopped")   # 通知手機：筆電已停止

    def get_url(self) -> str:
        return f"https://{_get_local_ip()}:{self.port}"

    # ── 內部邏輯 ──────────────────────────────────────────────────────────────

    def _run(self):
        # 先取得伺服器
        try:
            srv = _get_server(self.port)
        except Exception as e:
            self.on_error(f"無法啟動伺服器：{e}")
            self.on_done()
            return

        # ── 先掛上 on_chunk，讓手機送來的音訊可以進隊列（即使模型還沒載好）──
        _first_notified = [False]

        def _on_chunk(path: str, scene: str):
            if scene.strip():
                self.last_scene = scene.strip()   # 持續更新，以最後收到的為準
            if not _first_notified[0]:
                _first_notified[0] = True
                srv.broadcast_state("recording")   # 告訴手機：筆電已開始轉錄
                if self.on_phone_started:
                    self.on_phone_started()
            self._chunk_q.put((path, scene))

        srv.on_chunk         = _on_chunk
        srv.on_phone_stopped = self.on_phone_stopped   # 手機 POST /phone_stop 時呼叫
        self.on_status("Whisper 模型載入中…")

        # ── 再載入模型（chunk 在這段期間只是等在隊列裡）──────────────────────
        try:
            self._load_model()
        except Exception as e:
            srv.on_chunk         = None
            srv.on_phone_stopped = None
            self.on_error(str(e))
            self.on_done()
            return

        self.on_status("備妥，等待手機錄音…")
        srv.broadcast_state("armed")   # 通知手機：筆電已備妥

        while not self._stop.is_set():
            try:
                audio_path, scene = self._chunk_q.get(timeout=0.5)
            except queue.Empty:
                continue
            self._transcribe_chunk(audio_path, scene)

        srv.on_chunk = None
        if self._wav_file:
            try:
                self._wav_file.close()
            except Exception:
                pass
            self._wav_file = None
        self.on_done()

    def _load_model(self):
        self.on_status("載入 Whisper 模型中…")
        from gui_whisper_live import MLX_MODEL_MAP
        self._whisper = MLX_MODEL_MAP.get(
            self.model_name,
            f"mlx-community/whisper-{self.model_name}"
        )

    def _transcribe_chunk(self, audio_path: str, scene: str):
        audio_raw: np.ndarray | None = None
        try:
            import subprocess, tempfile, mlx_whisper, soundfile as sf
            from gui_whisper_live import vad_filter, HAS_SILERO_VAD

            # 1. ffmpeg → 16kHz mono WAV → numpy
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
                wav_path = tf.name
            try:
                subprocess.run(
                    ["ffmpeg", "-y", "-i", audio_path,
                     "-ar", "16000", "-ac", "1", "-f", "wav", wav_path,
                     "-loglevel", "quiet"],
                    check=True,
                )
                audio_raw, _ = sf.read(wav_path, dtype="float32")
            finally:
                try:
                    os.unlink(wav_path)
                except Exception:
                    pass

            # 2. VAD 過濾
            if HAS_SILERO_VAD:
                filtered, _ = vad_filter(audio_raw)
                if filtered is None:
                    return  # 全靜音，略過
                transcribe_audio = filtered
            else:
                transcribe_audio = audio_raw

            # 3. 轉錄
            result = mlx_whisper.transcribe(
                transcribe_audio,
                path_or_hf_repo=self._whisper,
                language=self.language,
                verbose=False,
            )
            for seg in result.get("segments", []):
                text = seg["text"].strip()
                if text:
                    _get_server(self.port).broadcast(text)
                    self.on_segment(text, None)

        except Exception as e:
            self.on_error(f"轉錄錯誤：{e}")
        finally:
            # 錄音存檔（用 decode 好的原始 numpy，不重複解碼）
            if self._audio_save_path and audio_raw is not None:
                try:
                    if self._wav_file is None:
                        self._wav_file = wave.open(self._audio_save_path, "wb")
                        self._wav_file.setnchannels(1)
                        self._wav_file.setsampwidth(2)
                        self._wav_file.setframerate(16000)
                    pcm = (audio_raw * 32767).clip(-32768, 32767).astype(np.int16)
                    self._wav_file.writeframes(pcm.tobytes())
                except Exception:
                    pass
            try:
                os.unlink(audio_path)
            except Exception:
                pass


# ── 手機端 HTML ────────────────────────────────────────────────────────────────

_PHONE_HTML = r"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, user-scalable=no">
<meta name="apple-mobile-web-app-capable" content="yes">
<title>ULTRA SCOOP — 手機麥克風</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  background: #0F1923; color: #D0D6DE;
  font-family: -apple-system, 'PingFang TC', 'Helvetica Neue', sans-serif;
  min-height: 100vh; display: flex; flex-direction: column;
  align-items: center; padding: 24px 16px;
}
.topbar {
  width: 100%; max-width: 420px; display: flex; align-items: center;
  margin-bottom: 4px; gap: 8px;
}
.topbar .accent { width: 3px; height: 26px; background: #C0895A; border-radius: 2px; }
h1  { font-size: 22px; font-weight: 900; letter-spacing: -0.5px; }
h1 .w { color: #FFFFFF; }
h1 .a { color: #C0895A; }
.sub { font-size: 13px; color: #6B7F8E; margin-bottom: 20px; }

.scene-wrap { width: 100%; max-width: 420px; margin-bottom: 14px; }
.scene-wrap label { font-size: 12px; color: #6B7F8E; display: block; margin-bottom: 5px; letter-spacing: 0.3px; }
#scene {
  width: 100%; padding: 10px 12px; border-radius: 8px;
  border: 1px solid #2A3E52; background: #182636;
  color: #D0D6DE; font-size: 15px; outline: none;
  transition: border-color 0.2s;
}
#scene:focus { border-color: #C0895A; }

#btn {
  width: 88px; height: 88px; border-radius: 50%;
  border: 2.5px solid #C0895A; cursor: pointer;
  background: #182636; color: #C0895A; transition: all 0.2s;
  display: flex; flex-direction: column; align-items: center;
  justify-content: center; gap: 3px;
  margin: 0 auto 12px; -webkit-tap-highlight-color: transparent;
  user-select: none;
}
#btn-label { font-size: 10px; font-weight: bold; letter-spacing: 1.5px; }
#btn.recording {
  border-color: #D32F2F; background: #2A1515; color: #FF5252;
  animation: pulse 1.2s ease-in-out infinite;
}
@keyframes pulse {
  0%,100% { box-shadow: 0 0 0 0 rgba(211,47,47,0.3); }
  50%      { box-shadow: 0 0 0 14px rgba(211,47,47,0); }
}
#laptop-state {
  font-size: 11px; font-weight: 600; margin-bottom: 6px; text-align: center;
  min-height: 20px; padding: 3px 12px; border-radius: 20px;
  background: #182636; color: #6B7F8E; display: inline-block;
  letter-spacing: 0.3px;
}
#laptop-state.armed    { color: #4CAF50; background: #0D2018; }
#laptop-state.recording{ color: #FF5252; background: #2A1515; }
#laptop-state.stopped  { color: #6B7F8E; background: #182636; }
.state-row { width: 100%; max-width: 420px; text-align: center; margin-bottom: 4px; }
#status { font-size: 13px; color: #6B7F8E; margin-bottom: 14px; text-align: center; min-height: 18px; }
#status.active { color: #C0895A; }

.tx-wrap { width: 100%; max-width: 420px; flex: 1; }
.tx-wrap label { font-size: 12px; color: #6B7F8E; display: block; margin-bottom: 5px; letter-spacing: 0.3px; }
#transcript {
  width: 100%; background: #0D1820; border-radius: 8px;
  padding: 12px; font-size: 14px; line-height: 1.8;
  min-height: 180px; max-height: 44vh; overflow-y: auto;
  color: #D0D6DE; white-space: pre-wrap;
  border: 1px solid #2A3E52;
}
.tx-meta { font-size: 11px; color: #3D5060; text-align: right; margin-top: 6px; }
</style>
</head>
<body>
<div class="topbar">
  <div class="accent"></div>
  <h1><span class="w">ULTRA</span> <span class="a">SCOOP</span></h1>
</div>
<p class="sub">手機麥克風 &mdash; 放在發言人附近效果最佳</p>

<div class="scene-wrap">
  <label>本場記者會名稱（用於錄音存檔命名）</label>
  <input id="scene" type="text"
         placeholder="例：行政院長記者會 GDP 主計總處">
</div>

<button id="btn" onclick="toggleRec()">
  <svg id="btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor"
       stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"
       width="30" height="30">
    <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3z"/>
    <path d="M19 10v2a7 7 0 0 1-14 0v-2"/>
    <line x1="12" y1="19" x2="12" y2="22"/>
    <line x1="8" y1="22" x2="16" y2="22"/>
  </svg>
  <span id="btn-label">REC</span>
</button>
<div class="state-row"><span id="laptop-state">連線中...</span></div>
<div id="status">點按開始錄音</div>

<div class="tx-wrap">
  <label>即時字幕</label>
  <div id="transcript">等待錄音...</div>
  <div class="tx-meta" id="chunk-count"></div>
</div>

<script>
const MIC_SVG = `<path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3z"/>
<path d="M19 10v2a7 7 0 0 1-14 0v-2"/>
<line x1="12" y1="19" x2="12" y2="22"/>
<line x1="8" y1="22" x2="16" y2="22"/>`;
const STOP_SVG = `<rect x="7" y="7" width="10" height="10" rx="2" fill="currentColor" stroke="none"/>`;

let recording = false, stream = null, mediaRec = null;
let chunkCount = 0, wakeLock = null, sseSource = null;

const btn          = document.getElementById('btn');
const btnIcon      = document.getElementById('btn-icon');
const btnLabel     = document.getElementById('btn-label');
const statusEl     = document.getElementById('status');
const transcriptEl = document.getElementById('transcript');
const countEl      = document.getElementById('chunk-count');

async function toggleRec() {
  recording ? stopRec() : await startRec();
}

async function startRec() {
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: false, noiseSuppression: false }
    });
  } catch(e) {
    statusEl.textContent = '麥克風權限錯誤：' + e.message;
    return;
  }
  recording = true;
  btn.classList.add('recording');
  btnIcon.innerHTML = STOP_SVG;
  btnLabel.textContent = 'STOP';
  statusEl.textContent = '錄音中';
  statusEl.className = 'active';
  transcriptEl.textContent = '';
  chunkCount = 0;
  countEl.textContent = '';

  if ('wakeLock' in navigator) {
    try { wakeLock = await navigator.wakeLock.request('screen'); } catch(_) {}
  }
  recordChunk();
}

// SSE 在頁面載入後立即連線（不需等開始錄音），持續接收筆電狀態
connectSSE();

async function stopRec() {
  recording = false;
  if (mediaRec && mediaRec.state !== 'inactive') mediaRec.stop();
  if (stream) { stream.getTracks().forEach(t => t.stop()); stream = null; }
  if (wakeLock) { wakeLock.release(); wakeLock = null; }
  btn.classList.remove('recording');
  btnIcon.innerHTML = MIC_SVG;
  btnLabel.textContent = 'REC';
  statusEl.textContent = '已停止';
  statusEl.className = '';
  // 通知筆電：手機停止錄音
  try { await fetch('/phone_stop', { method: 'POST' }); } catch(_) {}
  // SSE 保持連線，繼續接收筆電狀態
}

async function reacquireMic() {
  // 重新取得麥克風（麥克風 track 被 Siri / 通話中斷後呼叫）
  try {
    if (stream) stream.getTracks().forEach(t => t.stop());
    stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: false, noiseSuppression: false }
    });
    statusEl.textContent = `錄音中 · 已送 ${chunkCount} 段`;
    statusEl.className = 'active';
    recordChunk();
  } catch(e) {
    statusEl.textContent = '麥克風無法恢復：' + e.message;
    statusEl.className = '';
    stopRec();
  }
}

function recordChunk() {
  if (!recording || !stream) return;

  // 若所有 audio track 已結束（例如被 Siri / 通話佔用），自動重新取得麥克風
  if (stream.getTracks().every(t => t.readyState === 'ended')) {
    statusEl.textContent = '麥克風中斷，重新取得…';
    reacquireMic();
    return;
  }

  const types = [
    'audio/webm;codecs=opus', 'audio/webm',
    'audio/ogg;codecs=opus', 'audio/mp4', ''
  ];
  const mimeType = types.find(t => !t || MediaRecorder.isTypeSupported(t));

  try {
    mediaRec = mimeType
      ? new MediaRecorder(stream, { mimeType })
      : new MediaRecorder(stream);
  } catch(_) {
    try { mediaRec = new MediaRecorder(stream); }
    catch(e2) {
      // stream 狀態不可用，重新取得麥克風
      if (recording) { statusEl.textContent = '麥克風中斷，重新取得…'; reacquireMic(); }
      return;
    }
  }

  const chunks = [];
  mediaRec.ondataavailable = e => { if (e.data && e.data.size > 0) chunks.push(e.data); };
  mediaRec.onerror = () => {
    // MediaRecorder 發生錯誤（stream 狀態改變），稍後重試
    if (recording) setTimeout(recordChunk, 300);
  };
  mediaRec.onstop = async () => {
    if (!chunks.length) { if (recording) recordChunk(); return; }

    const blob = new Blob(chunks, { type: mediaRec.mimeType });
    const ext  = mediaRec.mimeType.includes('mp4') ? '.mp4'
               : mediaRec.mimeType.includes('ogg') ? '.ogg' : '.webm';
    const fd   = new FormData();
    fd.append('audio', blob, 'chunk' + ext);
    fd.append('scene', document.getElementById('scene').value || '');

    try {
      const resp = await fetch('/chunk', { method: 'POST', body: fd });
      if (resp.ok) {
        chunkCount++;
        countEl.textContent = `已送出 ${chunkCount} 段`;
        if (recording) statusEl.textContent = `錄音中 · 已送 ${chunkCount} 段`;
      } else if (resp.status === 503) {
        statusEl.textContent = '等待筆電就緒...';
      } else {
        statusEl.textContent = '傳送失敗 ' + resp.status;
      }
    } catch(e) {
      statusEl.textContent = '網路錯誤';
    }
    if (recording) recordChunk();
  };

  mediaRec.start();
  setTimeout(() => {
    if (mediaRec && mediaRec.state === 'recording') mediaRec.stop();
  }, 5000);
}

const LAPTOP_STATE_LABELS = {
  armed:     '筆電就緒',
  recording: '筆電轉錄中',
  stopped:   '筆電已停止'
};
const laptopStateEl = document.getElementById('laptop-state');

function setLaptopState(state) {
  laptopStateEl.textContent = LAPTOP_STATE_LABELS[state] || state;
  laptopStateEl.className = state;
  // 筆電停止時，手機若還在錄就自動停下
  if (state === 'stopped' && recording) stopRec();
}

function connectSSE() {
  sseSource = new EventSource('/transcript');

  sseSource.addEventListener('transcript', e => {
    try {
      const d = JSON.parse(e.data);
      if (!d.text) return;
      if (transcriptEl.textContent === '等待錄音…') transcriptEl.textContent = '';
      const ts = new Date().toLocaleTimeString('zh-TW',
        { hour: '2-digit', minute: '2-digit', second: '2-digit' });
      transcriptEl.textContent += `[${ts}]  ${d.text}\n`;
      transcriptEl.scrollTop = transcriptEl.scrollHeight;
    } catch(_) {}
  });

  sseSource.addEventListener('state', e => {
    try { setLaptopState(JSON.parse(e.data).state); } catch(_) {}
  });

  sseSource.onerror = () => {
    sseSource.close();
    setTimeout(connectSSE, 2000);   // 自動重連，不論是否在錄音
  };
}
</script>
</body>
</html>
"""
