# -*- coding: utf-8 -*-
"""
音ゲー定数検索モジュール(data/songs.json を使う。LLM不要なので捏造ゼロ)
- 「〜の定数」みたいな発言に曲名が含まれていたら答える
- 「!定数 曲名」で明示検索(あいまい検索対応)
"""
import difflib
import json
import re
import unicodedata
from pathlib import Path

_DATA = Path(__file__).parent / "data" / "songs.json"
_cache: tuple[float, dict] | None = None

_CJK = re.compile(r"[ぁ-んァ-ヶ一-龠々〆ヶ]")


def _load() -> dict:
    global _cache
    mtime = _DATA.stat().st_mtime if _DATA.exists() else 0
    if _cache is None or _cache[0] != mtime:
        try:
            with open(_DATA, encoding="utf-8") as f:
                _cache = (mtime, json.load(f))
        except Exception:
            _cache = (0, {"games": {}})
    return _cache[1]


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).lower()
    return re.sub(r"[\s!？?＠@：:・〜~ー-]", "", s)


def _index() -> dict:
    """正規化タイトル -> [(game, entry), ...] を作る(タイトルごと)"""
    data = _load()
    idx: dict[str, list] = {}
    for game, rows in data.get("games", {}).items():
        for e in rows:
            idx.setdefault(_norm(e["t"]), []).append((game, e))
    return idx


def query(text: str, explicit: bool = False) -> str | None:
    """発言から定数を引く。見つからなければ None(明示時は代替案つき)"""
    idx = _index()
    norm_text = _norm(text)
    m = re.search(r"!定数\s*(.+)", text)   # 明示コマンド「!定数 曲名」
    explicit_q = m.group(1).strip() if m else None

    hits: dict[tuple[str, str], list] = {}
    if explicit_q:
        nq = _norm(explicit_q)
        direct = idx.get(nq)
        if direct:
            for game, e in direct:
                hits.setdefault((game, e["t"]), []).append(e)
        else:  # あいまい検索
            pool = list(idx)
            close = difflib.get_close_matches(nq, pool, n=3, cutoff=0.7)
            extra = []
            for c in close:
                for game, e in idx[c]:
                    extra.append((game, e))
            if not extra:
                return None
            for game, e in extra:
                hits.setdefault((game, e["t"]), []).append(e)
    else:
        # 発言中に曲名が含まれているか(ASCII曲名は単語境界を要求)
        for norm_t, lst in idx.items():
            if len(norm_t) < 2:
                continue
            if _CJK.search(norm_t):
                found = norm_t in norm_text
            else:
                found = re.search(rf"(?<![a-z0-9]){re.escape(norm_t)}(?![a-z0-9])",
                                  norm_text) is not None
            if found:
                for game, e in lst:
                    hits.setdefault((game, e["t"]), []).append(e)
            if len(hits) >= 3:
                break

    if not hits:
        return None

    lines = []
    for (game, title), entries in list(hits.items())[:3]:
        order = ["PST", "PRS", "FTR", "BYD", "ETR", "BASIC", "ADVANCED",
                 "EXPERT", "MASTER", "ULTIMA", "Re:MASTER"]
        entries.sort(key=lambda e: order.index(e["d"]) if e["d"] in order else 99)
        parts = [f"{e['d']} {e['c']:.1f}" for e in entries]
        lines.append(f"【{game}】{title} / {', '.join(parts)}")
    return "\n".join(lines)
