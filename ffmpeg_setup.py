#!/usr/bin/env python3
"""
確保執行環境有可用的 ffmpeg。

策略：優先使用系統已安裝的 ffmpeg；若系統沒有，改用 pip 套件
imageio-ffmpeg 自帶的二進位，並在 PATH 上補一個名為 "ffmpeg" 的
連結，讓 mlx_whisper 內部與 phone_mic 的 subprocess 都能直接呼叫。

如此一來，全新的 Mac（未安裝 Homebrew / 系統 ffmpeg）也能正常
轉錄匯入的音訊／影片檔與手機麥克風串流。
"""
import os
import shutil


def ensure_ffmpeg_on_path() -> str | None:
    """
    保證 PATH 上存在可呼叫的 ffmpeg。

    Returns:
        可用的 ffmpeg 執行檔路徑；若連 imageio-ffmpeg 都沒有則回傳 None。
    """
    existing = shutil.which("ffmpeg")
    if existing:
        return existing

    try:
        import imageio_ffmpeg
    except ImportError:
        return None

    try:
        exe = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as error:
        print(f"[ffmpeg_setup] 無法取得 imageio-ffmpeg 執行檔：{error}")
        return None

    bin_dir = os.path.join(os.path.dirname(exe), "_ultrascoop_ffmpeg")
    link = os.path.join(bin_dir, "ffmpeg")

    if not os.path.exists(link):
        try:
            os.makedirs(bin_dir, exist_ok=True)
            try:
                os.symlink(exe, link)
            except OSError:
                # 不支援 symlink（極少見）時退而求其次：複製
                shutil.copy(exe, link)
                os.chmod(link, 0o755)
        except Exception as error:
            print(f"[ffmpeg_setup] 建立 ffmpeg 連結失敗：{error}")
            return exe  # 退回完整路徑，至少讓主動指定路徑的呼叫端能用

    os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")
    return link
