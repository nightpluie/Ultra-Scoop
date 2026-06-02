#!/bin/bash
# ──────────────────────────────────────────
#  Ultra Scoop — 第一次下載腳本
#  把此檔案放在桌面，雙擊執行即可
# ──────────────────────────────────────────

TARGET="$HOME/Desktop/Ultra Scoop"

echo ""
echo "======================================"
echo "  Ultra Scoop  —  下載程式"
echo "======================================"
echo ""

if [ -d "$TARGET/.git" ]; then
    echo "偵測到已有安裝，改執行更新..."
    echo ""
    cd "$TARGET"
    git pull https://github.com/nightpluie/Ultra-Scoop.git main
    echo ""
    echo "✓ 更新完成！"
    echo ""
    read -n 1 -s -r -p "按任意鍵關閉..."
    exit 0
fi

echo "正在下載 Ultra Scoop 到桌面..."
echo ""

git clone https://github.com/nightpluie/Ultra-Scoop.git "$TARGET"

if [ $? -ne 0 ]; then
    echo ""
    echo "✗ 下載失敗，請截圖此視窗並聯絡技術支援。"
    echo ""
    read -n 1 -s -r -p "按任意鍵關閉..."
    exit 1
fi

echo ""
echo "✓ 下載完成！正在開啟安裝程式..."
echo ""

open "$TARGET/安裝（第一次執行）.command"

echo "======================================"
echo "  下載完成，請依安裝視窗指示操作"
echo "======================================"
echo ""
read -n 1 -s -r -p "按任意鍵關閉..."
