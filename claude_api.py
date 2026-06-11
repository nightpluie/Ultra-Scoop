"""ULTRA SCOOP — Claude API 呼叫層：生成報導、事實查核、逐字稿修正與翻譯。

所有函式皆在背景執行緒執行，透過 callback 回報結果；
呼叫端（UI）須自行以 root.after() 切回主執行緒更新畫面。
"""

import os
import re
import json
import threading


def _has(m):
    try:
        __import__(m)
        return True
    except ImportError:
        return False


HAS_ANTHROPIC = _has("anthropic")

SCRIPT_DIR         = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SKILL_PATH = os.path.join(SCRIPT_DIR, "skills", "report-tcy",
                                  "report-tcy.md")


def load_skill(path: str = None) -> str:
    target = os.path.expanduser(path or DEFAULT_SKILL_PATH)
    try:
        with open(target, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return (
            "你是一位專業新聞記者。請依倒金字塔結構撰寫報導："
            "數據先行、官員姓名職稱明確引述、歷史比較標示清楚。"
        )


def claude_generate(transcript, files_text, model, interviewee, main_angle,
                    sidebar_mode, side_angle, api_key, skill_path,
                    on_token_main, on_token_side, on_done, on_error):
    """Generate article(s) and stream tokens directly to output boxes.

    sidebar_mode=True: state-machine routes tokens to on_token_main / on_token_side
    sidebar_mode=False: all tokens go to on_token_main
    """
    if not HAS_ANTHROPIC:
        on_error("尚未安裝 anthropic SDK（pip install anthropic）")
        on_done(); return
    if not api_key:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        on_error("請在右上角「設定」填入 API Key")
        on_done(); return

    def _run():
        try:
            import anthropic
            skill = load_skill(skill_path)
            parts = []
            if interviewee.strip():
                parts.append(f"【受訪者 / 發言人】\n{interviewee}")
            if transcript.strip():
                parts.append(f"【記者會逐字稿】\n{transcript}")
            if files_text.strip():
                parts.append(f"【官方新聞稿 / 統計附件】\n{files_text}")
            if not parts:
                on_error("請先錄製逐字稿或上傳附件")
                on_done(); return

            fmt = (
                "【格式要求】以純文字撰寫，禁止使用任何 Markdown 符號"
                "（##、**、*、- 列表、數字列表、``` 等），段落間用空行分隔。"
                "結尾不加「（記者名／地點）」等署名行，稿件到最後一段自然收束即可。"
            )

            if sidebar_mode:
                main_hint = (f"【主稿角度】{main_angle}" if main_angle.strip()
                             else "【主稿角度】請自行從素材中判斷最適合的主稿報導角度")
                side_hint = (f"【配稿角度】{side_angle}" if side_angle.strip()
                             else "【配稿角度】請自行從素材中找出與主稿不同、可互補的配稿角度")
                parts.append(
                    f"{main_hint}\n"
                    f"{side_hint}\n\n"
                    "請同時產出主稿與配稿。配稿須在第一段以 1-2 句簡要引入主稿的核心事實"
                    "作為背景，其後聚焦主稿未涵蓋的面向與角度。\n\n"
                    "請嚴格依照以下固定格式輸出，勿更改分隔符號：\n\n"
                    "===主稿開始===\n"
                    "[建議標題]：（填入建議標題）\n"
                    "（主稿內文）\n"
                    "===主稿結束===\n\n"
                    "===配稿開始===\n"
                    "[建議標題]：（填入建議標題）\n"
                    "（配稿內文）\n"
                    "===配稿結束===\n\n"
                    + fmt
                )
            else:
                main_hint = (f"【主稿角度】{main_angle}" if main_angle.strip()
                             else "【主稿角度】請自行從素材中判斷最適合的報導角度")
                parts.append(
                    f"{main_hint}\n\n"
                    "請依以上素材撰寫一篇完整的新聞報導。\n"
                    "第一行請輸出：[建議標題]：（填入建議標題）\n"
                    "第二行起輸出內文。\n\n"
                    + fmt
                )

            client = anthropic.Anthropic(api_key=api_key)

            if sidebar_mode:
                # ── 即時路由狀態機 ────────────────────────────────────────
                DELIMS = [
                    ("===主稿開始===", "NONE",    "IN_MAIN"),
                    ("===主稿結束===", "IN_MAIN",  "BETWEEN"),
                    ("===配稿開始===", "BETWEEN",  "IN_SIDE"),
                    ("===配稿結束===", "IN_SIDE",  "DONE"),
                ]
                MAX_D = max(len(d) for d, _, _ in DELIMS)
                _st = {"mode": "NONE", "buf": ""}

                def _emit(text, mode):
                    if not text:
                        return
                    if mode == "IN_MAIN":
                        on_token_main(text)
                    elif mode == "IN_SIDE" and on_token_side:
                        on_token_side(text)

                def _route(chunk):
                    _st["buf"] += chunk
                    while True:
                        buf = _st["buf"]
                        found = False
                        for delim, _, to_s in DELIMS:
                            idx = buf.find(delim)
                            if idx >= 0:
                                _emit(buf[:idx], _st["mode"])
                                _st["mode"] = to_s
                                _st["buf"] = buf[idx + len(delim):]
                                found = True
                                break
                        if found:
                            continue
                        # No full delimiter found; hold back possible partial match
                        safe = len(_st["buf"]) - MAX_D
                        if safe > 0:
                            _emit(_st["buf"][:safe], _st["mode"])
                            _st["buf"] = _st["buf"][safe:]
                        break

                with client.messages.stream(
                    model=model, max_tokens=3000, system=skill,
                    messages=[{"role": "user", "content": "\n\n".join(parts)}],
                ) as stream:
                    for chunk in stream.text_stream:
                        _route(chunk)
                _emit(_st["buf"], _st["mode"])  # flush remainder

            else:
                with client.messages.stream(
                    model=model, max_tokens=2048, system=skill,
                    messages=[{"role": "user", "content": "\n\n".join(parts)}],
                ) as stream:
                    for chunk in stream.text_stream:
                        on_token_main(chunk)

        except Exception as e:
            on_error(str(e))
        finally:
            on_done()

    threading.Thread(target=_run, daemon=True).start()


def claude_check(article, source, api_key, on_result, on_done, on_error):
    if not HAS_ANTHROPIC:
        on_error("尚未安裝 anthropic SDK"); on_done(); return
    if not api_key:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        on_error("請設定 API Key"); on_done(); return

    def _run():
        try:
            import anthropic
            system = (
                "你是專業的新聞編輯兼事實查核員。\n"
                "請逐一檢查【新聞稿】，找出以下三類問題：\n"
                "1. typo — 錯別字、語音辨識錯字（人名、機構名、專有名詞拼寫錯誤）\n"
                "2. mismatch — 數字、百分比、日期、姓名職稱與【原始素材】不符\n"
                "3. unsourced — 稿件中的事實或數據在【原始素材】中完全找不到出處\n\n"
                "以 JSON 陣列回傳，每項格式：\n"
                "{\"type\":\"typo|mismatch|unsourced\","
                "\"value\":\"稿件中的原文片段\","
                "\"suggestion\":\"建議修正值（unsourced 留空字串）\","
                "\"issue\":\"問題說明\"}\n\n"
                "重要：value 必須是稿件中能精確搜尋到的原文片段。"
                "suggestion 只在有明確正確答案時才填寫，無法確定時留空字串。"
                "完全無問題則回傳 []。"
            )
            client = anthropic.Anthropic(api_key=api_key)
            resp = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=2048,
                system=system,
                messages=[{"role": "user", "content":
                    f"【新聞稿】\n{article}\n\n【原始素材】\n{source}"}],
            )
            raw = resp.content[0].text.strip()
            m   = re.search(r"\[.*\]", raw, re.DOTALL)
            on_result(json.loads(m.group(0)) if m else [])
        except Exception as e:
            on_error(str(e))
        finally:
            on_done()

    threading.Thread(target=_run, daemon=True).start()


def claude_correct(text, api_key, on_done, on_error, context=""):
    """Use Haiku to correct Whisper transcription errors (names, numbers, terms).

    Splits long transcripts into chunks to avoid max_tokens truncation.
    context: optional press conference background (scene name + interviewee).
    """
    if not HAS_ANTHROPIC:
        on_error("尚未安裝 anthropic SDK（pip install anthropic）")
        return
    if not api_key:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        on_error("請設定 API Key")
        return

    CHUNK_CHARS = 3000  # ~3000 Chinese chars ≈ 3000-6000 tokens, safe under 8096 output limit

    def _split_chunks(t: str) -> list:
        lines = t.split('\n')
        chunks, cur, cur_len = [], [], 0
        for line in lines:
            line_len = len(line) + 1
            if cur_len + line_len > CHUNK_CHARS and cur:
                chunks.append('\n'.join(cur))
                cur, cur_len = [line], line_len
            else:
                cur.append(line)
                cur_len += line_len
        if cur:
            chunks.append('\n'.join(cur))
        return chunks

    def _run():
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=api_key)

            system = (
                "你是專業的新聞編輯。"
                "以下是語音辨識產生的逐字稿，可能含有辨識錯誤（人名、機構名、專有名詞、數字）。"
                "請只修正明顯的辨識錯字，不要改動句子結構、語氣或增減任何內容。"
                "保留原有的時間戳記、說話者標記與段落格式。"
                "直接輸出修正後的全文，不加任何說明或備注。"
            )
            if context.strip():
                system += (
                    f"\n\n【本場記者會背景資訊】\n{context.strip()}\n"
                    "請優先以此資訊校正人名、機構名與專有名詞的辨識錯誤。"
                )

            chunks = _split_chunks(text)
            corrected_parts = []

            for chunk in chunks:
                resp = client.messages.create(
                    model="claude-haiku-4-5-20251001",
                    max_tokens=8096,
                    system=system,
                    messages=[{
                        "role": "user",
                        "content": f"請校正以下逐字稿的辨識錯字：\n\n{chunk}"
                    }]
                )
                if resp.stop_reason == "max_tokens":
                    # 單段仍超限（極端情況），保留原始內容
                    corrected_parts.append(chunk)
                else:
                    corrected_parts.append(resp.content[0].text.strip())

            on_done('\n'.join(corrected_parts))
        except Exception as e:
            on_error(str(e))

    threading.Thread(target=_run, daemon=True).start()


def claude_translate(text, api_key, on_done, on_error):
    """Translate transcript to Traditional Chinese using Haiku (cheapest model)."""
    if not HAS_ANTHROPIC:
        on_error("尚未安裝 anthropic SDK（pip install anthropic）")
        return
    if not api_key:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        on_error("請設定 API Key")
        return

    def _run():
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=api_key)
            resp = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=8096,
                system=(
                    "你是專業翻譯員，擅長將各國語言翻譯成繁體中文。"
                    "保留原文的段落結構與說話者標記（如「主席：」「記者：」「[時間戳]」等），"
                    "直接輸出翻譯結果，不加任何說明或備注。"
                ),
                messages=[{
                    "role": "user",
                    "content": f"請將以下逐字稿翻譯成繁體中文：\n\n{text}"
                }]
            )
            on_done(resp.content[0].text.strip())
        except Exception as e:
            on_error(str(e))

    threading.Thread(target=_run, daemon=True).start()
