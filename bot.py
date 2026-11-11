# -*- coding: utf-8 -*-
"""
Discord AI チャットボット
- メンション(@ボット名)や「ボットの返信」には必ず返信
- 名前で呼ばれても返信
- トリガーワードに確率で自然に割り込み(クールダウン付き)
必要: Python 3.10+ / pip install -r requirements.txt
"""
import logging
import os
import random
import re
import time

import discord
from dotenv import load_dotenv
from openai import AsyncOpenAI

try:
    import gomamayo
except ImportError:
    gomamayo = None  # janome が無くてもボット本体は動く

try:
    import dice
except ImportError:
    dice = None

try:
    import songdb
except ImportError:
    songdb = None

load_dotenv()

# ---------------- 設定(.env で上書き可能) ----------------
DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]  # 必須
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1")
LLM_MODEL = os.environ.get("LLM_MODEL", "gpt-4o-mini")
BOT_NAME = os.environ.get("BOT_NAME", "エージェント")

PERSONA_FILE = os.environ.get("PERSONA_FILE", "persona.txt")
TRIGGER_WORDS = [w.strip() for w in os.environ.get(
    "TRIGGER_WORDS", "ごはん,疲れた,だるい,助けて").split(",") if w.strip()]
INTERJECT_PROB = float(os.environ.get("INTERJECT_PROB", "0.6"))    # トリガー時に反応する確率
INTERJECT_COOLDOWN = float(os.environ.get("INTERJECT_COOLDOWN", "90"))  # 同一チャンネルの最短割り込み間隔(秒)
GOMAMAYO_PROB = float(os.environ.get("GOMAMAYO_PROB", "0.5"))      # ゴママヨ検出時に返信する確率(絵文字は常に)
GOMAMAYO_COOLDOWN = float(os.environ.get("GOMAMAYO_COOLDOWN", "60"))    # 同一チャンネルの最短ゴママヨ返信間隔(秒)
GOMAMAYO_EMOJI = os.environ.get("GOMAMAYO_EMOJI", "⁉️")            # ゴママヨ検出時のリアクション
AUTO_REPLY = os.environ.get("AUTO_REPLY", "1") == "1"              # トリガー外でも、自分で「参加したい」と判断したら返す
AUTO_REPLY_COOLDOWN = float(os.environ.get("AUTO_REPLY_COOLDOWN", "90"))  # 自発返信の最短間隔(秒・チャンネルごと)
MAX_CONTEXT = int(os.environ.get("MAX_CONTEXT", "10"))             # 文脈として読む直近メッセージ数
MAX_REPLY_CHARS = int(os.environ.get("MAX_REPLY_CHARS", "300"))    # 返信の最大文字数

DEFAULT_PERSONA = (
    "あなたはDiscordのサーバーで雑談に参加するAIキャラクターです。\n"
    "ルール:\n"
    "- 必ず日本語で、カジュアルな口調で話す\n"
    "- 返信は短く(2〜3文まで)。長文・箇条書きは禁止\n"
    "- 相談されたら普通に助言するが、おせっかいはしない\n"
    "- 知らないことは知らないと言う。嘘をつかない\n"
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("ai-bot")

ai = AsyncOpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)

intents = discord.Intents.default()
intents.message_content = True  # Developer Portal での有効化が必要
client = discord.Client(intents=intents)

# チャンネルごとの状態
last_interject: dict[int, float] = {}
last_gomamayo: dict[int, float] = {}
last_auto: dict[int, float] = {}
interject_enabled: dict[int, bool] = {}


def load_persona() -> str:
    """persona.txt を毎回読むので、起動中でも編集がすぐ反映される"""
    try:
        with open(PERSONA_FILE, encoding="utf-8") as f:
            p = f.read().strip()
            return p or DEFAULT_PERSONA
    except FileNotFoundError:
        return DEFAULT_PERSONA


def clean(text: str) -> str:
    """メンション表記 (<@123...>) を読みやすい形に"""
    return re.sub(r"<@!?\d+>", "@ユーザー", text).strip()


def is_addressed_to_bot(message: discord.Message) -> bool:
    """メンション / ボットへの返信 / 名前で呼ばれた、のいずれか"""
    if client.user and client.user in message.mentions:
        return True
    if message.reference and isinstance(message.reference.resolved, discord.Message):
        return message.reference.resolved.author == client.user
    return BOT_NAME in message.content


def hit_trigger(text: str):
    for w in TRIGGER_WORDS:
        if w in text:
            return w
    return None


async def build_messages(channel, message: discord.Message) -> list:
    msgs = [{"role": "system",
             "content": load_persona()
             + f"\nあなたの表示名は「{BOT_NAME}」です。"
             + "\n返信には名前やプレフィックス(例: 「エージェント: 〜」)を付けず、"
               "発言の本文だけをそのまま出力すること。"}]
    history = [m async for m in channel.history(limit=MAX_CONTEXT, before=message)]
    history.reverse()
    for m in history:
        name = m.author.display_name
        content = f"{name}「{clean(m.content)}」" if m.content else f"{name}(画像など)"
        msgs.append({"role": "assistant" if m.author == client.user else "user",
                     "content": content})
    msgs.append({"role": "user",
                 "content": f"{message.author.display_name}「{clean(message.content)}」"})
    return msgs


async def generate_reply(channel, message: discord.Message):
    try:
        async with channel.typing():
            resp = await ai.chat.completions.create(
                model=LLM_MODEL,
                messages=await build_messages(channel, message),
                max_tokens=300,
                temperature=0.9,
            )
        text = (resp.choices[0].message.content or "").strip()
        # 念のため、冒頭の「キャラ名:」形式を除去
        text = re.sub(
            rf"^\s*(?:\*\*)?\s*(?:{re.escape(BOT_NAME)}|キャラ名|AI|アシスタント|ボット)\s*(?:\*\*)?\s*[:：]\s*",
            "", text)
        if len(text) > MAX_REPLY_CHARS:
            cut = text[:MAX_REPLY_CHARS]
            for i in range(len(cut) - 1, 0, -1):
                if cut[i] in "。！？!?\n":
                    text = cut[:i + 1]
                    break
            else:
                text = cut
        return text or None
    except Exception:
        log.exception("LLM呼び出しに失敗しました")
        return None


async def wants_to_reply(channel, message: discord.Message) -> bool:
    """AUTO_REPLY用: ミア自身に「この会話に参加したい?」と YES/NO で聞く"""
    try:
        msgs = await build_messages(channel, message)
        msgs[0] = {"role": "system", "content": (
            "あなたはDiscordサーバーの住人「ミア」です。"
            "直近の会話を読み、あなた自身が自然に参加したいかを判断してください。"
            "反応したい/一言ある/教えたい、なら YES。"
            "他人同士のやり取りで入る余地がない、特に言うことがない、なら NO。"
            "出力は YES か NO の一語のみ。")}
        resp = await ai.chat.completions.create(
            model=LLM_MODEL, messages=msgs,
            max_tokens=5, temperature=0.0)
        return "YES" in (resp.choices[0].message.content or "").upper()
    except Exception:
        log.exception("自発返信の判定に失敗しました")
        return False


@client.event
async def on_ready():
    log.info("ログインしました: %s (参加サーバー数: %d)", client.user, len(client.guilds))


@client.event
async def on_message(message: discord.Message):
    if message.author.bot or message.guild is None:
        return
    ch = message.channel

    # チャンネル内コマンド
    if message.content.strip().startswith("!ai"):
        arg = message.content.strip()[3:].strip()
        if arg == "off":
            interject_enabled[ch.id] = False
            await ch.send("このチャンネルでの自然な割り込みを止めます。メンションなら返事します。")
        elif arg == "on":
            interject_enabled[ch.id] = True
            await ch.send("割り込み、再開します。")
        else:
            state = "ON" if interject_enabled.get(ch.id, True) else "OFF"
            goma = "使える" if gomamayo else "無効(モジュール不足)"
            await ch.send(f"稼働中 / 割り込み: {state} / ゴママヨ検出: {goma} / トリガー: {', '.join(TRIGGER_WORDS)}")
        return

    # 1.2) ダイスロール(「1d100」などの表記。明示的な意図なので最優先に反応)
    if dice is not None:
        rolls = dice.roll(message.content)
        if rolls:
            await ch.send("\n".join(rolls[:5]))  # 多種併記は最初の5個まで
            return

    # 1.3) 音ゲー定数検索(「!定数 曲名」/ 「定数」を含む発言の曲名を照合)
    if songdb is not None:
        s = message.content.strip()
        if s.startswith("!定数"):
            reply = songdb.query(s)
            await ch.send(reply or "その曲はデータになかったよ…ごめんね")
            return
        if "定数" in message.content:
            reply = songdb.query(message.content)
            if reply:
                await ch.send(reply)
                return

    # 1.5) ゴママヨ検出(LLM不要・即座に反応)
    if gomamayo is not None:
        # ランキング / ランダム再生コマンド
        if message.content.strip().startswith("!gomamayo"):
            arg = message.content.strip()[len("!gomamayo"):].strip()
            if arg in ("random", "r", "ランダム"):
                e = gomamayo.random_one(message.guild.id)
                if e:
                    await ch.send(f"過去のゴママヨ: 「{e['text']}」\n"
                                  f"（{e['a']}＋{e['b']} / {e['level']} / by {e['name']}）")
                else:
                    await ch.send("まだ記録されたゴママヨがありません。")
            else:
                await ch.send(gomamayo.ranking(message.guild.id, message.author.id))
            return
        hit = gomamayo.detect(message.content)
        if hit:
            try:
                await message.add_reaction(GOMAMAYO_EMOJI)
            except discord.HTTPException:
                pass
            # ツッコむ(=スコアが発表される)ときだけ得点が入る
            if (time.time() - last_gomamayo.get(ch.id, 0) >= GOMAMAYO_COOLDOWN
                    and random.random() <= GOMAMAYO_PROB):
                last_gomamayo[ch.id] = time.time()
                extra = ""
                awarded = gomamayo.award(message.guild.id, message.author.id,
                                         message.author.display_name, hit)
                if awarded:
                    pts, total = awarded
                    extra = f"【+{pts}点、通計{total}点】"
                await ch.send(f"それ{hit['level']}では？（「{hit['a']}」＋「{hit['b']}」）{extra}")
            return

    # 2) 呼ばれたら必ず返信
    if is_addressed_to_bot(message):
        reply = await generate_reply(ch, message)
        if reply:
            await ch.send(reply, mention_author=False)
        return

    # 2.5) 自然な割り込み系(!ai off で両方止まる)
    if not interject_enabled.get(ch.id, True):
        return

    # 2.5a) トリガーワードに確率で割り込み(判定なしの即答ルート)
    if hit_trigger(message.content):
        if time.time() - last_interject.get(ch.id, 0) < INTERJECT_COOLDOWN:
            return
        if random.random() > INTERJECT_PROB:
            return
        last_interject[ch.id] = time.time()
        reply = await generate_reply(ch, message)
        if reply:
            await ch.send(reply)
        return

    # 2.5b) 自発返信: トリガー外でも、ミア自身に「参加したい?」と聞いてYESなら返す
    if not AUTO_REPLY:
        return
    if time.time() - last_auto.get(ch.id, 0) < AUTO_REPLY_COOLDOWN:
        return
    if len(message.content.strip()) <= 2:  # 「w」等の短文は判定する価値なし
        return
    if message.content.strip().startswith("!"):  # 謎コマンドには反応しない
        return
    if await wants_to_reply(ch, message):
        last_auto[ch.id] = time.time()
        reply = await generate_reply(ch, message)
        if reply:
            await ch.send(reply)


def _start_health_server():
    """RenderなどPaaS用: PORTが指定されていたらヘルスチェック用HTTPサーバーを立てる
    (外部から10分おきに叩かれることでスリープしなくなる)"""
    # RenderはPORTを設定しないこともあるので、未指定なら10000で開く
    port = int(os.environ.get("PORT", "0") or 0) or 10000
    if not port:
        return
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class Health(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *a):
            pass

    t = threading.Thread(
        target=HTTPServer(("0.0.0.0", port), Health).serve_forever, daemon=True)
    t.start()
    log.info("ヘルスチェックサーバーを port %d で起動", port)


if __name__ == "__main__":
    if not LLM_API_KEY:
        log.warning("LLM_API_KEY が未設定です。返信生成が失敗します")
    _start_health_server()
    client.run(DISCORD_TOKEN)
