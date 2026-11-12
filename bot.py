# -*- coding: utf-8 -*-
"""
Discord AI チャットボット
- メンション(@ボット名)や「ボットの返信」には必ず返信
- 名前で呼ばれても返信
- トリガーワードに確率で自然に割り込み(クールダウン付き)
必要: Python 3.10+ / pip install -r requirements.txt
"""
import asyncio
import json
import logging
import os
import random
import re
import time
from datetime import datetime, timedelta, timezone

import discord
from discord.ext import tasks
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
MONOLOGUE = os.environ.get("MONOLOGUE", "1") == "1"                # ごくまれにひとりごとを言う
MONOLOGUE_PROB = float(os.environ.get("MONOLOGUE_PROB", "0.05"))   # 10分ごとの判定で実行する確率
MONOLOGUE_COOLDOWN = float(os.environ.get("MONOLOGUE_COOLDOWN", "7200"))  # ひとりごとの最短間隔(秒)
MONOLOGUE_CHANNEL_ID = int(os.environ.get("MONOLOGUE_CHANNEL_ID", "0") or 0)  # 指定すればそのチャンネル限定
MONOLOGUE_ACTIVITY_WINDOW = float(os.environ.get("MONOLOGUE_ACTIVITY_WINDOW", "21600"))  # 直近人が話した期間(秒)だけ対象
ALLOWED_CHANNEL_IDS = {
    int(x) for x in os.environ.get("ALLOWED_CHANNEL_IDS", "").replace(" ", "").split(",")
    if x.strip().lstrip("-").isdigit()}  # 固定の発言許可チャンネル(RenderのEnvで指定)
LEARN = os.environ.get("LEARN", "1") == "1"            # サーバーの話し方を「記憶ノート」に吸収させる
LEARN_FILE = os.environ.get("LEARN_FILE", "learned.txt")
LEARN_EVERY = int(os.environ.get("LEARN_EVERY", "30"))  # 人間の発言この数ごとに記憶を更新
GREETINGS = os.environ.get("GREETINGS", "1") == "1"    # 朝の挨拶・夜の挨拶を毎日1回ずつ
GREET_MORNING_HOURS = os.environ.get("GREET_MORNING_HOURS", "5-12")   # 日本時間の窓(この時間帯のどこかで1回)
GREET_NIGHT_HOURS = os.environ.get("GREET_NIGHT_HOURS", "22-3")       # 22時〜翌3時(日をまたぐ)
GREET_STATE_FILE = os.environ.get("GREET_STATE_FILE", "greeting_state.json")
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
learn_enabled: dict[int, bool] = {}  # チャンネルごとの学習ON/OFF(!ai learn off)
allowed_channels: set[int] = set(ALLOWED_CHANNEL_IDS)  # 発言許可チャンネル(Envで固定 or メンションで自動追加)
last_monologue = 0.0          # 最後にひとりごと言った時刻
last_seen_channel = None      # 人間が最後に発言したチャンネル
last_seen_time = 0.0          # その時刻
human_msg_count = 0           # 学習トリガー用カウンタ
greet_state = {"morning": "", "night": ""}  # 各挨拶を最後にした「日」
greet_plan = {"morning": None, "night": None}  # (期間id, 実行予定時刻)
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


def learned_notes() -> str:
    """記憶ノート(サーバーで吸収した言葉遣い・話題)を読む"""
    try:
        with open(LEARN_FILE, encoding="utf-8") as f:
            return f.read().strip()[:1500]
    except FileNotFoundError:
        return ""


async def build_messages(channel, message: discord.Message) -> list:
    sys_text = (load_persona()
                + f"\nあなたの表示名は「{BOT_NAME}」です。"
                + "\n返信には名前やプレフィックス(例: 「エージェント: 〜」)を付けず、"
                  "発言の本文だけをそのまま出力すること。")
    notes = learned_notes()
    if notes:
        sys_text += ("\n\n【あなたがこのサーバーで暮らす中で自然に身につけた記憶】\n"
                     + notes
                     + "\n(この内容をそのまま引用せず、口調や話題の好みとして"
                       "自然に染み込ませること)")
    msgs = [{"role": "system", "content": sys_text}]
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


async def update_memory(channel):
    """人間の発言がある程度貯まったら、LLMに「記憶ノート」を書かせて保存する"""
    try:
        history = [m async for m in channel.history(limit=80)]
        lines = [f"{m.author.display_name}「{clean(m.content)[:100]}」"
                 for m in reversed(history)
                 if m.content and not m.author.bot]
        if len(lines) < 10:
            return
        prev = learned_notes()
        sys_prompt = ("あなたはDiscord住人「ミア」の記憶を管理する編集者です。"
                      "下の会話ログを読み、ミアが自然に吸収すべきことを『記憶ノート』として"
                      "箇条書きで書いてください(最大8行・全体500字以内)。"
                      "書くこと: みんながよく使う言葉やネタ、話題の傾向、"
                      "メンバーの口調の特徴、覚えておくと良さそうな出来事。"
                      "発言をそのまま書き写さず、特徴だけを抽出すること。"
                      "前回のノートがある場合はそれを引き継ぎ、古くなった項目は消してよい。")
        user_prompt = ""
        if prev:
            user_prompt += f"【前回の記憶ノート】\n{prev}\n\n"
        user_prompt += "【最近の会話ログ】\n" + "\n".join(lines)
        resp = await ai.chat.completions.create(
            model=LLM_MODEL,
            messages=[{"role": "system", "content": sys_prompt},
                      {"role": "user", "content": user_prompt}],
            max_tokens=400, temperature=0.5)
        text = (resp.choices[0].message.content or "").strip()
        if text:
            with open(LEARN_FILE, "w", encoding="utf-8") as f:
                f.write(text)
            log.info("記憶ノートを更新しました(%d文字)", len(text))
    except Exception:
        log.exception("記憶ノートの更新に失敗しました")


async def generate_monologue(channel):
    """ひとりごと生成: 誰宛でもない、ぼそっと一言"""
    try:
        mono_sys = (load_persona()
                    + "\nいま誰もあなたに話しかけていません。返事ではなく、"
                      "ぼそっとひとりごと言ってください。"
                      "ルール: 1〜2文・日本語・名前やプレフィックスなし・"
                      "誰かの発言への返答にしない。直近の話題をふと思い出す感じでOK。")
        notes = learned_notes()
        if notes:
            mono_sys += "\n\n【身につけた記憶(口調や話題として染み込ませる)】\n" + notes
        msgs = [{"role": "system", "content": mono_sys}]
        history = [m async for m in channel.history(limit=5)]
        ctx = "\n".join(f"{m.author.display_name}「{clean(m.content)}」"
                        for m in reversed(history) if m.content)
        if ctx:
            msgs.append({"role": "user", "content":
                         f"チャンネルの最近の様子:\n{ctx}\n\n"
                         "(返信ではなく、あなたのひとりごとだけを出力)"})
        resp = await ai.chat.completions.create(
            model=LLM_MODEL, messages=msgs, max_tokens=100, temperature=1.1)
        text = (resp.choices[0].message.content or "").strip()
        return text or None
    except Exception:
        log.exception("ひとりごとの生成に失敗しました")
        return None


def monologue_target():
    """ひとりごとの投稿先: 指定チャンネル or 人間が最後に話したチャンネル"""
    if MONOLOGUE_CHANNEL_ID:
        return client.get_channel(MONOLOGUE_CHANNEL_ID)
    return last_seen_channel


JST = timezone(timedelta(hours=9))


def _load_greet_state():
    try:
        with open(GREET_STATE_FILE, encoding="utf-8") as f:
            greet_state.update(json.load(f))
    except (FileNotFoundError, ValueError):
        pass


def _save_greet_state():
    try:
        with open(GREET_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(greet_state, f)
    except OSError:
        pass


def _parse_hours(spec: str):
    a, b = spec.split("-")
    return int(a) % 24, int(b) % 24


def _in_window(h: int, start: int, end: int) -> bool:
    if start <= end:
        return start <= h < end
    return h >= start or h < end  # 22-3 のように日をまたぐ窓


def _greet_period(now: datetime, start: int) -> str:
    """この窓の開始日で「今日もう言った」を判定(深夜窓は日をまたいで同一期間)"""
    d = now.date() if now.hour >= start else (now - timedelta(days=1)).date()
    return d.isoformat()


def _window_end(now: datetime, end: int) -> datetime:
    e = now.replace(hour=end, minute=0, second=0, microsecond=0)
    if e <= now:
        e += timedelta(days=1)
    return e


async def generate_greeting(kind: str) -> str | None:
    """朝/夜の挨拶生成: その日の気分で少し違う一文"""
    try:
        now = datetime.now(JST)
        part = "朝" if kind == "morning" else "夜"
        instr = (f"時刻は日本時間{now.strftime('%H:%M')}です。"
                 f"Discordサーバーに自然に{part}の挨拶をしてください。")
        if kind == "morning":
            instr += "「おはよう」系で。"
        else:
            instr += "「おやすみ」系で、そろそろ寝る感じ。"
        sys_text = (load_persona()
                    + "\n" + instr
                    + "\nルール: 1〜2文・日本語・名前やプレフィックスなし・"
                      "毎日同じ言い回しをしない(ランダム感を出す)。")
        notes = learned_notes()
        if notes:
            sys_text += "\n\n【身につけた記憶(口調や話題として染み込ませる)】\n" + notes
        resp = await ai.chat.completions.create(
            model=LLM_MODEL, messages=[{"role": "system", "content": sys_text}],
            max_tokens=100, temperature=1.1)
        text = (resp.choices[0].message.content or "").strip()
        return text or None
    except Exception:
        log.exception("挨拶の生成に失敗しました")
        return None


@tasks.loop(minutes=10)
async def greeting_loop():
    """朝と夜、それぞれの時間帯の中でランダムな時刻に1回だけ挨拶する"""
    if not GREETINGS:
        return
    now = datetime.now(JST)
    for kind, spec in (("morning", GREET_MORNING_HOURS),
                       ("night", GREET_NIGHT_HOURS)):
        start, end = _parse_hours(spec)
        if not _in_window(now.hour, start, end):
            greet_plan[kind] = None
            continue
        period = _greet_period(now, start)
        if greet_state.get(kind) == period:
            continue  # 今日はもう言った
        plan = greet_plan.get(kind)
        if plan is None or plan[0] != period:
            # この窓の中のランダムな時刻に予約(窓の残り時間のランダム位置)
            remain = (_window_end(now, end) - now).total_seconds()
            greet_plan[kind] = (period,
                                now + timedelta(seconds=random.uniform(
                                    60, max(120, remain * 0.9))))
            continue  # 実行は次回 tick 以降
        if now >= plan[1]:
            ch = last_seen_channel or (
                client.get_channel(MONOLOGUE_CHANNEL_ID)
                if MONOLOGUE_CHANNEL_ID else None)
            if ch is None or not interject_enabled.get(ch.id, True):
                continue
            if ch.id not in allowed_channels:
                continue  # 許可されていないチャンネルでは挨拶しない
            text = await generate_greeting(kind)
            if text:
                await ch.send(text)
                greet_state[kind] = period
                _save_greet_state()
                log.info("%s の挨拶を # に投稿しました", kind)
            greet_plan[kind] = None


@tasks.loop(minutes=10)
async def monologue_loop():
    """10分おきにサイコロを振り、ごくまれにひとりごとを言う"""
    global last_monologue
    if not MONOLOGUE:
        return
    if time.time() - last_seen_time > MONOLOGUE_ACTIVITY_WINDOW:
        return  # 誰も話してないサーバーで独り言は言わない(無駄打ち防止)
    ch = monologue_target()
    if ch is None or not interject_enabled.get(ch.id, True):
        return
    if ch.id not in allowed_channels:
        return  # メンションされたことのないチャンネルではひとりごとを言わない
    if time.time() - last_monologue < MONOLOGUE_COOLDOWN:
        return
    if random.random() > MONOLOGUE_PROB:
        return
    reply = await generate_monologue(ch)
    if reply:
        await ch.send(reply)
        last_monologue = time.time()


@client.event
async def on_ready():
    log.info("ログインしました: %s (参加サーバー数: %d)", client.user, len(client.guilds))
    _load_greet_state()
    if not monologue_loop.is_running():
        monologue_loop.start()
    if not greeting_loop.is_running():
        greeting_loop.start()


@client.event
async def on_message(message: discord.Message):
    if message.author.bot or message.guild is None:
        return
    ch = message.channel

    # ひとりごと・挨拶の投稿先候補: 人間の発言があった場所と時刻を覚えておく
    # (ただし発言許可チャンネル=メンションされた場所だけを相手にする)
    global last_seen_channel, last_seen_time, human_msg_count
    if ch.id in allowed_channels:
        last_seen_channel = ch
        last_seen_time = time.time()

    # 学習: 人間の発言が LEARN_EVERY 件貯まったら記憶ノートを更新(裏で非同期に走る)
    # !ai learn off されたチャンネルは観察対象から外す
    human_msg_count += 1
    if LEARN and learn_enabled.get(ch.id, True) and human_msg_count >= LEARN_EVERY:
        human_msg_count = 0
        asyncio.create_task(update_memory(ch))

    # チャンネル内コマンド
    if message.content.strip().startswith("!ai"):
        arg = message.content.strip()[3:].strip()
        if arg == "off":
            interject_enabled[ch.id] = False
            await ch.send("このチャンネルでは黙ります(メンションとダイス等のコマンドには反応します)。"
                          "学習も止めたい場合は `!ai learn off` もどうぞ。")
        elif arg == "on":
            interject_enabled[ch.id] = True
            learn_enabled[ch.id] = True
            allowed_channels.add(ch.id)
            await ch.send("このチャンネルでの会話、再開します。")
        elif arg == "here":
            allowed_channels.add(ch.id)
            await ch.send("このチャンネルを発言OKリストに追加しました(ひとりごと・挨拶もここで言うようになります)。")
        elif arg == "hide":
            allowed_channels.discard(ch.id)
            await ch.send("このチャンネルを発言OKリストから外しました。"
                          "以後、メンションされたときだけここで返事します(ひとりごと・挨拶は言いません)。")
        elif arg == "learn off":
            learn_enabled[ch.id] = False
            await ch.send("このチャンネルの発言は覚えないようにします。会話には今まで通り参加します。")
        elif arg == "learn on":
            learn_enabled[ch.id] = True
            await ch.send("このチャンネルも観察対象に戻します。")
        else:
            talk = "ON" if interject_enabled.get(ch.id, True) else "OFF"
            learn_ch = "ON" if learn_enabled.get(ch.id, True) else "OFF"
            allow = "許可" if ch.id in allowed_channels else "未許可(メンションで許可)"
            fixed = " (Envで固定)" if ALLOWED_CHANNEL_IDS else ""
            goma = "使える" if gomamayo else "無効(モジュール不足)"
            mono = "使える" if MONOLOGUE else "オフ"
            learn = "使える" if LEARN else "オフ"
            greet = "使える" if GREETINGS else "オフ"
            await ch.send(f"稼働中 / このチャンネルで喋る: {talk} / このチャンネルを学習: {learn_ch} / このチャンネルの発言: {allow}{fixed}\n"
                          f"全体設定 / ゴママヨ検出: {goma} / ひとりごと: {mono} / 学習: {learn} / 挨拶: {greet}\n"
                          "コマンド: `!ai off` `!ai on` `!ai here` `!ai hide` `!ai learn off` `!ai learn on`")
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
        hit = (gomamayo.detect(message.content)
               if interject_enabled.get(ch.id, True) else None)
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

    # 2) 呼ばれたら必ず返信(そのチャンネルが発言許可リストに入る)
    if is_addressed_to_bot(message):
        allowed_channels.add(ch.id)
        reply = await generate_reply(ch, message)
        if reply:
            await ch.send(reply, mention_author=False)
        return

    # 2.5) 自然な割り込み系(メンションされたことのないチャンネルでは発言しない)
    if not interject_enabled.get(ch.id, True):
        return
    if ch.id not in allowed_channels:
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
