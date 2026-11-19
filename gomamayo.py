# -*- coding: utf-8 -*-
"""ゴママヨ検出(ユーザー提供の libs/goma_util.py を使用)

スコアリング(加点・累計ランキング・ランダム再生)は廃止。
検出して指摘(Embed)するだけ。
"""
import re as _re

try:
    from libs import goma_util
except Exception:  # 辞書ファイルや依存が無くてもボット本体は動く
    goma_util = None

# 判定に入れると誤検出になるノイズ: URL・絵文字コード(:korosuzo: 等)・
# スポイラー(||…||)やコードブロックの記号
_NOISE_RE = _re.compile(
    r'https?://\S+'          # URL
    r'|:[A-Za-z0-9_+-]+:'    # Discord絵文字コード
    r'|\|\||```|`'           # スポイラー・コードブロック等の記号
    r'|<[a@][^>]+>'          # メンション・チャンネルリンク
)

# この範囲に1文字でもあれば「日本語」とみなす(ひらがな・カタカナ・漢字など)
_JP_RE = _re.compile(r'[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uff66-\uff9f]')


def _clean(text: str) -> str:
    return _NOISE_RE.sub('', text)


def _has_japanese(*words) -> bool:
    """マッチした単語ペアのどちらかに日本語を含むときだけ本物とみなす。
    (「60kg」=「60」+「kg」みたいなアルファベット同士の誤検出を潰す)"""
    return any(_JP_RE.search(w or '') for w in words)


def available() -> bool:
    return goma_util is not None


def detect(text: str):
    """ゴママヨを検出する。ヒット時は DataFrame、無ければ None

    検出ロジックは goma_util.gomamayo() そのもの。
    読みの取れない文字種(絵文字等)での例外だけ潰して None にする。
    """
    if goma_util is None or not text:
        return None
    text = _clean(text)
    if not text.strip():
        return None
    try:
        df = goma_util.gomamayo(text)
    except Exception:
        return None
    if df is None:
        return None
    # ノイズ由来(日本語を含まないペア)だけの検出は本物とみなさない
    return df if parts(text) else None


def parts(text: str):
    """ゴママヨの内訳を返す: [(次数, 区間, 前単語, 後単語), ...] or None

    判定は goma_util の内部関数(goma1v1/gomajoin)をそのまま借りる。
    「(「ゴマ」＋「マヨ」)」みたいな旧形式の指摘文を作るのに使う。
    """
    if goma_util is None or not text:
        return None
    try:
        t = _re.sub(r'\[|\]|\(|\)|「|」', '。', _clean(text))
        wl = [(tk.reading or tk.surface, tk.surface,
               tk.part_of_speech.split(',')[0])
              for tk in goma_util.gtoken.tokenize(t)]
        joined = goma_util.gomajoin(goma_util.goma1v1(wl))
        if not joined:
            return None
        out = []
        for g in joined:
            if _has_japanese(g[3], g[4]):  # 日本語ペアのみ採用
                out.append((g[2], g[3] + g[4], g[3], g[4]))
        return out or None
    except Exception:
        return None


def embed(df):
    """検出結果を discord.Embed に(goma_util.goma_em への委譲)"""
    if goma_util is None or df is None:
        return None
    try:
        return goma_util.goma_em(df)
    except Exception:
        return None
