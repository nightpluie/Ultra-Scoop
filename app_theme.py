"""ULTRA SCOOP — 深色主題色票與字型常數（全 UI 共用）。"""

__all__ = [
    "BG", "BG_SURFACE", "BG_PANEL", "BG_INPUT", "BORDER", "BORDER_LT",
    "ACCENT_BLUE", "ACCENT_GREEN", "ACCENT_PURPLE", "ACCENT_AMBER", "ACCENT_RED",
    "TEXT_PRI", "TEXT_SEC", "TEXT_DIM",
    "OK_FG", "ERR_FG", "WARN_FG", "INFO_FG",
    "FT", "FT_BOLD", "FT_BIG", "FT_SM", "FT_MONO", "FT_ARTICLE",
    "COL_INPUT", "COL_PROCESS", "COL_OUTPUT",
    "COL_INPUT_HOVER", "COL_PROCESS_HOVER", "COL_OUTPUT_HOVER",
]

# ── dark theme palette ────────────────────────────────────────────────────────
BG          = "#0F1923"
BG_SURFACE  = "#182636"
BG_PANEL    = "#1E3044"
BG_INPUT    = "#0D1820"
BORDER      = "#2A3E52"
BORDER_LT   = "#345068"

ACCENT_BLUE   = "#5B8DB8"
ACCENT_GREEN  = "#5B9E72"
ACCENT_PURPLE = "#8E78C0"
ACCENT_AMBER  = "#C0895A"
ACCENT_RED    = "#D32F2F"

TEXT_PRI     = "#D0D6DE"
TEXT_SEC     = "#6B7F8E"
TEXT_DIM     = "#3D5060"

OK_FG    = "#6DBF88"
ERR_FG   = "#E07070"
WARN_FG  = "#D4A832"
INFO_FG  = "#5B8DB8"

# ── typography ────────────────────────────────────────────────────────────────
FT         = ("PingFang TC", 13)
FT_BOLD    = ("PingFang TC", 13, "bold")
FT_BIG     = ("PingFang TC", 15, "bold")
FT_SM      = ("PingFang TC", 11)
FT_MONO    = ("Menlo", 11)
FT_ARTICLE = ("PingFang TC", 14)

# ── column color assignments (semantic) ───────────────────────────────────────
# 色彩規則（v3.4）：
#   1. 欄位色只用於該欄的「主要行動」按鈕（全介面最多三顆實心彩鈕）
#   2. 其餘按鈕一律 ghost（描邊灰底）
#   3. ACCENT_PURPLE 專屬「AI 輔助小工具」（修正錯字／翻成中文）的文字色
#   4. ACCENT_RED 僅用於錄音狀態
COL_INPUT   = ACCENT_AMBER   # 暖色：採集原始素材
COL_PROCESS = ACCENT_BLUE    # 冷色：AI 分析處理
COL_OUTPUT  = ACCENT_GREEN   # 綠色：準備發布（與 ACCENT_GREEN 統一，全程式單一綠）

COL_INPUT_HOVER   = "#A87548"
COL_PROCESS_HOVER = "#4A7A9E"
COL_OUTPUT_HOVER  = "#4D8560"
