#!/bin/bash
# ──────────────────────────────────────────
#  Ultra Scoop — 一鍵更新腳本
# ──────────────────────────────────────────

DIR="$( cd "$( dirname "$0" )" && pwd )"
cd "$DIR"

echo ""
echo "======================================"
echo "  Ultra Scoop  —  更新程式"
echo "======================================"
echo ""
echo "正在從伺服器拉取最新版本..."
echo ""

REPO_URL="https://github.com/nightpluie/Ultra-Scoop.git"
CONFIG_BACKUP="$(mktemp)"

# 備份使用者設定（API key 等），避免更新覆蓋
[ -f config.json ] && cp config.json "$CONFIG_BACKUP" 2>/dev/null

if [ ! -d ".git" ]; then
    # 解壓的資料夾沒有 git 紀錄：首次自動掛上更新來源
    echo "首次設定更新來源..."
    git init -q
    git remote add origin "$REPO_URL" 2>/dev/null
    git fetch -q origin main && git reset --hard origin/main
    RET=$?
else
    git pull "$REPO_URL" main
    RET=$?
fi

# 還原使用者設定（config.json 不在版控內，但多一層保險）
[ -f "$CONFIG_BACKUP" ] && cp "$CONFIG_BACKUP" config.json 2>/dev/null && rm -f "$CONFIG_BACKUP"

if [ $RET -ne 0 ]; then
    echo ""
    echo "✗ 更新失敗，請確認網路連線後重試，或截圖此視窗聯絡技術支援。"
    echo ""
    read -n 1 -s -r -p "按任意鍵關閉..."
    exit 1
fi

echo ""
echo "正在更新套件（如有新增）..."
if [ -f "$DIR/.venv/bin/pip" ]; then
    "$DIR/.venv/bin/pip" install -r "$DIR/requirements.txt" -q
    echo "✓ 套件已更新"
else
    echo "（尚未安裝虛擬環境，請先執行「安裝（第一次執行）.command」）"
fi

echo ""
echo "======================================"
echo "  ✓ 更新完成！"
echo "======================================"
echo ""
read -n 1 -s -r -p "按任意鍵關閉..."
