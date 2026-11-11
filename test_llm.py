# -*- coding: utf-8 -*-
"""LLM APIの診断スクリプト — python test_llm.py で実行"""
import os

import httpx
from dotenv import load_dotenv

load_dotenv()
base = os.environ.get("LLM_BASE_URL", "").rstrip("/")
key = os.environ.get("LLM_API_KEY", "")
print("MODEL設定:", os.environ.get("LLM_MODEL", "(なし)"))
print("キーの長さ:", len(key), "文字(中身は表示しません)")

r = httpx.get(base + "/models", headers={"Authorization": f"Bearer {key}"}, timeout=30)
print("STATUS:", r.status_code)
print(r.text[:2000])
