#!/bin/bash
cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
    echo "尚未安裝！請先雙擊「安裝（第一次執行）.command」進行安裝。"
    read -p "按 Enter 結束..."
    exit 1
fi

# v3.0: 自動補裝新版所需套件（舊用戶不必重跑安裝程式）
.venv/bin/python3 -c "import customtkinter" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "偵測到新版本，補裝必要套件..."
    .venv/bin/pip install -r requirements.txt -q
fi

.venv/bin/python3 pressconf_studio.py
