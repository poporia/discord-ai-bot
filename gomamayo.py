# -*- coding: utf-8 -*-
"""
ゴママヨ検出モジュール
AkaakuHub/gomamayo (https://github.com/AkaakuHub/gomamayo) の実装を参考に、
MeCab ではなく Janome(純Python)で動くようにしたもの。Windowsで追加セットアップ不要。
参考元: Awesome-Gomamayo (https://github.com/Hayao0819/Awesome-Gomamayo)
"""
import json
import random
import re
import time
from pathlib import Path

import jaconv
from janome.tokenizer import Tokenizer

_HIRA = re.compile(r"[ぁ-ん]+")
_ALPHA = re.compile(r"[a-zA-Z]+")
_tokenizer = Tokenizer()


def _pronounce_list(text: str) -> list[str]:
    """文を単語区切りにして、各単語の読み(ひらがな)のリストを返す"""
    out: list[str] = []
    for tok in _tokenizer.tokenize(text):
        surface = tok.surface
        if not surface.strip():
            continue
        pos = tok.part_of_speech.split(",")[0]
        hira_surface = jaconv.kata2hira(surface)

        # 「は」を含むひらがなだけの語(ましょう等)は誤検出の元なので捨てる
        if _HIRA.fullmatch(hira_surface):
            if "は" not in hira_surface:
                out.append(hira_surface)
            continue

        reading = tok.reading or ""      # 辞書の読み(カタカナ)
        phonetic = tok.phonetic or ""    # 発音(カタカナ)
        word = phonetic if pos in ("助詞", "動詞") else (reading or phonetic)

        # 英単語はアルファベット読みに変換できれば変える(alkanaがあれば)
        if _ALPHA.fullmatch(surface):
            try:
                import alkana
                kana = alkana.get_kana(surface.lower())
                if kana:
                    word = kana
            except Exception:
                pass

        pron = jaconv.kata2hira(word) if word else ""
        if pron and _HIRA.search(pron):
            out.append(pron)
    return out


def detect(text: str):
    """ゴママヨ検出。見つからなければ None、見つかったら (レベル名, 単語A, 単語B) を返す"""
    prons = _pronounce_list(text)
    if len(prons) < 2:
        return None

    boundaries: list[tuple[int, int]] = []  # (単語番号, 重なり文字数)
    for i in range(len(prons) - 1):
        a, b = prons[i], prons[i + 1]
        if not a or not b:
            continue
        overlap = 0
        for k in range(min(len(a), len(b)), 0, -1):
            if a[-k:] == b[:k]:
                overlap = k
                break
        if overlap > 0:
            boundaries.append((i, overlap))

    if not boundaries:
        return None

    # n項ゴママヨ(連続でゴママヨが続く)の判定
    streak, best = 1, 1
    for (i1, _), (i2, _) in zip(boundaries, boundaries[1:]):
        if i1 + 1 == i2:
            streak += 1
            best = max(best, streak)
        else:
            streak = 1

    idx, overlap = boundaries[0]
    if best > 1:
        level = f"{best}項ゴママヨ"
    elif overlap >= 2:
        level = "高次ゴママヨ"
    else:
        level = "ゴママヨ"

    return {"level": level, "a": prons[idx], "b": prons[idx + 1],
            "overlap": overlap, "streak": best, "text": text}


# ---------------- スコア集計(累計・リセットなし) ----------------
_SCORES_FILE = Path(__file__).parent / "gomamayo_scores.json"
_user_last: dict[tuple[int, int], float] = {}
USER_COOLDOWN = 30.0  # 同一ユーザーが連続で得点できない間隔(秒・怪文書対策)
MAX_LOG = 500         # 履歴の最大保持数(古いものから捨てる)


def _load_scores() -> dict:
    try:
        with open(_SCORES_FILE, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get("users"), dict):
            data.setdefault("log", [])
            return data
    except Exception:
        pass
    return {"users": {}, "log": []}


def _save_scores(data: dict) -> None:
    try:
        with open(_SCORES_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
    except OSError:
        pass


def award(guild_id: int, user_id: int, name: str, result: dict):
    """検出結果をスコアに反映。→ (得点, 合計) / クールダウン中は None"""
    now = time.time()
    key = (guild_id, user_id)
    if now - _user_last.get(key, 0) < USER_COOLDOWN:
        return None
    _user_last[key] = now

    if result["streak"] > 1:
        pts = result["streak"] * 2   # n項ゴママヨ
    elif result["overlap"] >= 2:
        pts = 3                      # 高次ゴママヨ
    else:
        pts = 1                      # 通常のゴママヨ

    data = _load_scores()
    rec = data["users"].setdefault(str(guild_id), {}).setdefault(
        str(user_id), {"name": name, "score": 0, "count": 0})
    rec["name"] = name
    rec["score"] += pts
    rec["count"] += 1
    data["log"].append({"guild": guild_id, "name": name,
                        "text": result.get("text", "")[:60],
                        "a": result["a"], "b": result["b"],
                        "level": result["level"]})
    data["log"] = data["log"][-MAX_LOG:]
    _save_scores(data)
    return pts, rec["score"]


def ranking(guild_id: int, user_id: int) -> str:
    """累計スコアのランキング。0点以外の全員を表示(上限40人)"""
    data = _load_scores()
    recs = data.get("users", {}).get(str(guild_id), {})
    ordered = sorted(((uid, r) for uid, r in recs.items() if r.get("score", 0) > 0),
                     key=lambda kv: kv[1]["score"], reverse=True)
    if not ordered:
        return "まだ誰もゴママヨを記録していません。"
    medals = ["🥇", "🥈", "🥉"]
    lines = ["ゴママヨ殿堂(累計)"]
    my_rank = None
    for i, (uid, rec) in enumerate(ordered):
        if uid == str(user_id):
            my_rank = i + 1
        if i < 40:  # Discordの文字数上限対策
            medal = medals[i] if i < 3 else f"{i + 1}."
            lines.append(f"{medal} {rec['name']} … {rec['score']}点({rec['count']}回)")
    if len(ordered) > 40:
        lines.append(f"ほか {len(ordered) - 40} 人(省略)")
        if my_rank:
            lines.append(f"あなた: {my_rank}位")
    return "\n".join(lines)


def random_one(guild_id: int):
    """このサーバーの過去のゴママヨをランダムに1つ返す(なければ None)"""
    data = _load_scores()
    log = [e for e in data.get("log", []) if e.get("guild") == guild_id]
    return random.choice(log) if log else None
