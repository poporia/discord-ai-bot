# -*- coding: utf-8 -*-
"""
音ゲー定数データのビルド/更新スクリプト
python build_songs.py で data/songs.json を作り直せる(再取得も自動)。
データ源:
- CHUNITHM / maimai: zvuc/otoge-db の music-ex.json (有志による定数収集データ)
- Arcaea: Arcaea Wiki (Fandom) の Songs by Level ページ
"""
import json
import re
import urllib.request
from pathlib import Path

BASE = Path(__file__).parent
OUT = BASE / "data" / "songs.json"
RAW = BASE / "data_raw"

UA = {"User-Agent": "Mozilla/5.0 (discord-ai-bot builder)"}
SOURCES = {
    "chunithm.json": "https://raw.githubusercontent.com/zvuc/otoge-db/main/chunithm/data/music-ex.json",
    "maimai.json": "https://raw.githubusercontent.com/zvuc/otoge-db/main/maimai/data/music-ex.json",
    "arcaea_wikitext.json": "https://arcaea.fandom.com/api.php?action=parse&page=Songs_by_Level&format=json&prop=wikitext",
}


def fetch_all(force: bool = False) -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    for fname, url in SOURCES.items():
        path = RAW / fname
        if force or not path.exists() or path.stat().st_size < 1000:
            print("取得中:", url)
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=60) as r, open(path, "wb") as f:
                f.write(r.read())


def clean_wikitext(s: str) -> str:
    s = re.sub(r"<[^>]+>", "", s)
    s = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]+)\]\]", r"\1", s)  # [[a|b]] -> b
    s = re.sub(r"\{\{[^}]*\}\}", "", s)                       # テンプレ除去
    return s.strip()


def _parse_arcaea_csv() -> list:
    """フォールバック: gist の charts.csv(Arcaea wiki由来のCSV)"""
    import csv
    path = RAW / "arcaea_charts.csv"
    if not path.exists() or path.stat().st_size < 1000:
        url = ("https://gist.githubusercontent.com/12beesinatrenchcoat/"
               "1bb2081eb2d6857254f06d3cf228e0c9/raw/charts.csv")
        print("取得中:", url)
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=60) as r, open(path, "wb") as f:
            f.write(r.read())
    dmap = {"past": "PST", "present": "PRS", "future": "FTR",
            "beyond": "BYD", "eternal": "ETR"}
    out = []
    with open(path, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            try:
                out.append({"t": row["title"].strip(),
                            "d": dmap[row["difficulty"].strip().lower()],
                            "lv": row["level"].strip(),
                            "c": float(row["constant"])})
            except (KeyError, ValueError):
                continue
    return out


def _parse_arcaea_wikitext() -> list:
    w = json.load(open(RAW / "arcaea_wikitext.json", encoding="utf-8"))
    text = w["parse"]["wikitext"]["*"]
    diffs = [("past", "PST"), ("present", "PRS"), ("future", "FTR"),
             ("beyond", "BYD"), ("eternal", "ETR")]
    out = []
    for table in re.split(r"\{\|", text)[1:]:
        table = table.split("|}")[0]
        header_cells: list[str] = []
        raw_rows: list[list[str]] = []
        for ln in table.splitlines():
            s = ln.strip()
            if s.startswith("!!") or (s.startswith("!") and "||" not in s):
                header_cells += [c.strip().lower() for c in re.split(r"!!", s.lstrip("!")) if c.strip()]
            elif s.startswith("|") and "||" in s:
                raw_rows.append([c.strip() for c in s[1:].split("||")])
            elif s.startswith("|"):
                raw_rows.append([s[1:].strip()])
            elif s == "|-":
                raw_rows.append(["ROWSEP"])
        merged: list[list[str]] = []
        cur: list[str] = []
        for r in raw_rows:
            if r == ["ROWSEP"]:
                if cur:
                    merged.append(cur)
                cur = []
            else:
                cur += r
        if cur:
            merged.append(cur)

        col_map = []
        for i, low in enumerate(header_cells):
            for key, label in diffs:
                if key in low:
                    col_map.append((i, label))
                    break
        if not col_map:
            continue

        seen: set[str] = set()
        for row in merged:
            if not row:
                continue
            title = clean_wikitext(row[0])
            if not title or len(title) > 80:
                continue
            for idx, label in col_map:
                if idx >= len(row):
                    continue
                nums = re.findall(r"\d+(?:\.\d+)?", clean_wikitext(row[idx]))
                if len(nums) >= 2:
                    const = nums[1]
                    if "." in const and 1.0 <= float(const) <= 13.0:
                        key = (title, label)
                        if key not in seen:
                            seen.add(key)
                            out.append({"t": title, "d": label, "lv": nums[0],
                                        "c": float(const)})
    return out


def parse_arcaea() -> list:
    rows = _parse_arcaea_wikitext()
    if len(rows) >= 500:
        print("  Arcaea: wikitext解析で取得")
        return rows
    print(f"  Arcaea: wikitext解析で{len(rows)}件しか取れず → gist CSVにフォールバック")
    return _parse_arcaea_csv()


def parse_otoge(fname: str, game: str, diff_keys) -> list:
    data = json.load(open(RAW / fname, encoding="utf-8"))
    out = []
    for song in data:
        title = (song.get("title") or "").strip()
        if not title:
            continue
        for key, label in diff_keys:
            lv = (song.get(f"lev_{key}") or "").strip()
            const = (song.get(f"lev_{key}_i") or "").strip()
            if lv and const:
                try:
                    c = float(const)
                except ValueError:
                    continue
                out.append({"t": title, "d": label, "lv": lv, "c": c})
    return out


def main():
    fetch_all(force="--fresh" in __import__("sys").argv)
    games = {
        "CHUNITHM": parse_otoge("chunithm.json", "CHUNITHM", [
            ("bas", "BASIC"), ("adv", "ADVANCED"), ("exp", "EXPERT"),
            ("mas", "MASTER"), ("ult", "ULTIMA")]),
        "maimai": parse_otoge("maimai.json", "maimai", [
            ("bas", "BASIC"), ("adv", "ADVANCED"), ("exp", "EXPERT"),
            ("mas", "MASTER"), ("remas", "Re:MASTER")]),
        "Arcaea": parse_arcaea(),
    }
    payload = {"updated": __import__("time").strftime("%Y-%m-%d"), "games": games}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=0)
    for game, rows in games.items():
        print(f"{game}: {len(rows)} 譜面")


if __name__ == "__main__":
    main()
