"""ULTRA SCOOP — 深色主題色票與字型常數（全 UI 共用）。"""

__all__ = [
    "BG", "BG_SURFACE", "BG_PANEL", "BG_INPUT", "BORDER", "BORDER_LT",
    "ACCENT_BLUE", "ACCENT_GREEN", "ACCENT_PURPLE", "ACCENT_AMBER", "ACCENT_RED",
    "TEXT_PRI", "TEXT_SEC", "TEXT_DIM",
    "OK_FG", "ERR_FG", "WARN_FG", "INFO_FG",
    "FT", "FT_BOLD", "FT_BIG", "FT_SM", "FT_MONO", "FT_ARTICLE",
    "COL_INPUT", "COL_PROCESS", "COL_OUTPUT",
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
COL_INPUT   = ACCENT_AMBER   # 暖色：採集原始素材
COL_PROCESS = ACCENT_BLUE    # 冷色：AI 分析處理
COL_OUTPUT  = "#4CAF50"      # 綠色：準備發布
