# -*- coding: utf-8 -*-
"""ゴママヨ検出(ユーザー提供の libs/goma_util.py を使用)

スコアリング(加点・累計ランキング・ランダム再生)は廃止。
検出して指摘(Embed)するだけ。
"""
try:
    from libs import goma_util
except Exception:  # 辞書ファイルや依存が無くてもボット本体は動く
    goma_util = None


def available() -> bool:
    return goma_util is not None


def detect(text: str):
    """ゴママヨを検出する。ヒット時は DataFrame、無ければ None

    検出ロジックは goma_util.gomamayo() そのもの。
    読みの取れない文字種(絵文字等)での例外だけ潰して None にする。
    """
    if goma_util is None or not text:
        return None
    try:
        return goma_util.gomamayo(text)
    except Exception:
        return None


def parts(text: str):
    """ゴママヨの内訳を返す: [(次数, 区間, 前単語, 後単語), ...] or None

    判定は goma_util の内部関数(goma1v1/gomajoin)をそのまま借りる。
    「(「ゴマ」＋「マヨ」)」みたいな旧形式の指摘文を作るのに使う。
    """
    if goma_util is None or not text:
        return None
    try:
        import re as _re
        t = _re.sub(r'\[|\]|\(|\)|「|」', '。', text)
        wl = [(tk.reading or tk.surface, tk.surface,
               tk.part_of_speech.split(',')[0])
              for tk in goma_util.gtoken.tokenize(t)]
        joined = goma_util.gomajoin(goma_util.goma1v1(wl))
        if not joined:
            return None
        out = []
        for g in joined:
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
