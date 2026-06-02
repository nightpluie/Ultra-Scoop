#!/bin/bash
cd "$(dirname "$0")"

# ── 執行權限自我修復（解壓後 chmod 可能遺失）──────────────────────────────────
chmod +x ./*.command 2>/dev/null

# ── 解除 Gatekeeper 隔離（從壓縮檔／AirDrop 來的檔案會被標記，雙擊會被擋）──────
# 一次清除整包，之後「啟動」「更新」等 .command 就不會再跳「無法打開」。
xattr -dr com.apple.quarantine "$(pwd)" 2>/dev/null

echo "======================================"
echo "  Ultra Scoop — 安裝程式"
echo "======================================"
echo ""

# ── 1. 找到一個有可用 Tk 的 Python 3 ──────────────────────────────────────────
# 測試某個 python 是否能正常啟動 Tk（在子 process 測，避免 SIGABRT 污染主程序）
_tk_ok() {
    "$1" -c "import tkinter; r=tkinter.Tk(); r.destroy()" &>/dev/null 2>&1
    return $?
}

PYTHON=""

# 候選清單：優先 Homebrew 新版（Tk 相容性最佳），次選系統內建
CANDIDATES=()
if command -v brew &>/dev/null; then
    BREW_PREFIX=$(brew --prefix)
    # 列出 brew 裝的所有 python3.x，版本由新到舊
    for p in $(ls "$BREW_PREFIX/bin/python3."* 2>/dev/null | sort -t. -k2 -rn); do
        CANDIDATES+=("$p")
    done
fi
CANDIDATES+=("/usr/bin/python3")

for candidate in "${CANDIDATES[@]}"; do
    if "$candidate" --version &>/dev/null 2>&1; then
        if _tk_ok "$candidate"; then
            PYTHON="$candidate"
            break
        fi
    fi
done

# 若所有候選都沒有可用 Tk，嘗試讓 Homebrew 安裝 python-tk
if [ -z "$PYTHON" ]; then
    echo "⚠️   找不到有效的 Tkinter，嘗試透過 Homebrew 安裝 python-tk..."
    if command -v brew &>/dev/null; then
        # 找 brew 已裝的 python 版本
        BREW_PY_VER=$(ls "$(brew --prefix)/bin/python3."* 2>/dev/null \
                      | grep -oE '[0-9]+\.[0-9]+' | sort -t. -k2 -rn | head -1)
        if [ -n "$BREW_PY_VER" ]; then
            echo "⚙️   brew install python-tk@${BREW_PY_VER}..."
            brew install "python-tk@${BREW_PY_VER}" -q
            BREW_PY="$(brew --prefix)/bin/python${BREW_PY_VER}"
            if _tk_ok "$BREW_PY"; then
                PYTHON="$BREW_PY"
                echo "✅  python-tk 安裝成功"
            fi
        fi
    fi
fi

if [ -z "$PYTHON" ]; then
    echo ""
    echo "❌  找不到支援 Tk 視窗介面的 Python"
    echo ""
    echo "請從 python.org 下載安裝 Python（內含 Tk，免費）："
    echo "    https://www.python.org/downloads/macos/"
    echo ""
    echo "安裝完成後，請重新執行此安裝程式。"
    echo ""
    read -p "按 Enter 結束..."
    exit 1
fi

PY_VER=$("$PYTHON" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_MINOR=$("$PYTHON" -c "import sys; print(sys.version_info.minor)")
PY_MAJOR=$("$PYTHON" -c "import sys; print(sys.version_info.major)")
echo "✅  Python $PY_VER（$PYTHON）"
echo "✅  Tkinter 正常"

if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 9 ]; }; then
    echo ""
    echo "❌  Python 版本太舊（需要 3.9 以上，目前是 $PY_VER）"
    echo "    請從 python.org 下載最新版：https://www.python.org/downloads/macos/"
    echo ""
    read -p "按 Enter 結束..."
    exit 1
fi

# ── 2. 建立本地虛擬環境 ────────────────────────────────────────────────────────
NEED_VENV=true
if [ -d ".venv" ] && .venv/bin/python3 --version &>/dev/null; then
    # 額外測試 Tk 是否能在現有 venv 中正常運作
    if _tk_ok ".venv/bin/python3"; then
        echo "✅  虛擬環境已存在且有效，跳過建立"
        NEED_VENV=false
    else
        echo "⚠️   現有虛擬環境的 Tk 無法運作，重新建立..."
        rm -rf .venv
    fi
elif [ -d ".venv" ]; then
    echo "⚠️   偵測到無效的虛擬環境（路徑不符此電腦），重新建立..."
    rm -rf .venv
fi

if [ "$NEED_VENV" = true ]; then
    echo "⚙️   建立虛擬環境..."
    "$PYTHON" -m venv .venv
    echo "✅  虛擬環境建立完成"
fi

# ── 3. 安裝套件 ───────────────────────────────────────────────────────────────
echo ""
echo "⚙️   安裝套件（需要網路，約 3–5 分鐘，請稍候）..."
echo ""
.venv/bin/pip install --upgrade pip -q
.venv/bin/pip install -r requirements.txt

if [ $? -ne 0 ]; then
    echo ""
    echo "❌  安裝失敗，請確認網路連線後重新執行此安裝程式"
    read -p "按 Enter 結束..."
    exit 1
fi

# ── 3.5 建立個人設定檔（含 API key，每台電腦各自保留，更新時不覆蓋）──────────
if [ ! -f config.json ] && [ -f config.example.json ]; then
    cp config.example.json config.json
    echo "✅  已建立個人設定檔 config.json"
fi

# ── 3.6 預先下載 ffmpeg（imageio-ffmpeg 自帶版，免裝 Homebrew）──────────────
echo ""
echo "⚙️   準備 ffmpeg（音訊／影片解碼用，約 30MB，需要網路）..."
.venv/bin/python3 -c "import imageio_ffmpeg; print('✅  ffmpeg 就緒：', imageio_ffmpeg.get_ffmpeg_exe())"
if [ $? -ne 0 ]; then
    echo ""
    echo "❌  ffmpeg 準備失敗，請確認網路連線後重新執行此安裝程式"
    read -p "按 Enter 結束..."
    exit 1
fi

# ── 4. 預先下載 Whisper turbo 模型（mlx-whisper）────────────────────────────
echo ""
echo "⚙️   下載 Whisper turbo 模型（約 1.5GB，需要網路，請耐心等候）..."
echo ""
.venv/bin/python3 -c "
import mlx_whisper
print('開始下載 whisper-large-v3-turbo 模型...')
mlx_whisper.transcribe(
    __import__('numpy').zeros(16000, dtype='float32'),
    path_or_hf_repo='mlx-community/whisper-large-v3-turbo',
    verbose=False,
)
print('模型下載完成')
"

if [ $? -ne 0 ]; then
    echo ""
    echo "❌  模型下載失敗，請確認網路連線後重新執行此安裝程式"
    read -p "按 Enter 結束..."
    exit 1
fi

echo ""
echo "======================================"
echo "  ✅ 安裝完成！"
echo ""
echo "  之後請雙擊「啟動 Ultra Scoop.command」啟動程式"
echo "======================================"
echo ""
read -p "按 Enter 結束..."
