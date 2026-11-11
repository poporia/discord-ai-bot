# -*- coding: utf-8 -*-
"""
TRPGダイスロールモジュール
「1d100」「2d6+1」「3d10-2」みたいな表記を検出してロールする。
判定は正規表現のみなのでLLM不要・即座に反応。
"""
import random
import re

# 「数字d数字 (±定数)」を検出(大文字Dも可)
_DICE = re.compile(r"\b(\d{1,3})\s*d\s*(\d{1,4})(?:\s*([+\-])\s*(\d{1,4}))?\b",
                   re.IGNORECASE)

MAX_DICE = 100    # ダイスの個数上限
MAX_SIDES = 1000  # 面の数の上限


def roll(text: str) -> list[str]:
    """文中のダイス表記をすべてロールして、結果文字列のリストを返す"""
    results = []
    for m in _DICE.finditer(text):
        n = int(m.group(1))
        sides = int(m.group(2))
        if n == 0 or n > MAX_DICE or sides < 2 or sides > MAX_SIDES:
            continue  # 異常な表記は無視(「0d0」や巨大数の荒らし対策)

        rolls = [random.randint(1, sides) for _ in range(n)]
        total = sum(rolls)
        expr = f"{n}d{sides}"

        detail_parts = [str(r) for r in rolls] if (n > 1 or m.group(3)) else []
        if m.group(3):
            c = int(m.group(4))
            total = total + c if m.group(3) == "+" else total - c
            expr += f" {m.group(3)} {c}"
            detail_parts.append(f"{m.group(3)}{c}")

        detail = f"（{' '.join(detail_parts)}）" if detail_parts else ""
        results.append(f"🎲 {expr} = **{total}**{detail}")
    return results
