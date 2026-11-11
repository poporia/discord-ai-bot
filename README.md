# Discord AI チャットボット

Discordの雑談に自然に参加するAIボットです。

- メンション(@ボット名)されたら必ず返信
- 名前(「エージェント」など)で呼んでも返信
- トリガーワード(「ごはん」「疲れた」など)に確率で割り込み
- 同一チャンネルにはクールダウン付き。うるさくならない制御済み

## 1. Discordボット(トークン)を作る

1. https://discord.com/developers/applications を開いて「New Application」
2. 左メニュー「Bot」→「Reset Token」でトークンをコピー(**他人には見せないこと**)
3. 同ページ下部の「Privileged Gateway Intents」で **MESSAGE CONTENT INTENT** を ON にして保存
4. 左メニュー「OAuth2」→「URL Generator」で
   - Scopes: `bot`
   - Bot Permissions: `View Channels` `Send Messages` `Read Message History`
   を選び、生成されたURLを開いて自分のサーバーに招待

## 2. 実行(Python 3.10 以上)

```bash
pip install -r requirements.txt
cp .env.example .env        # Windows は copy
# .env を編集して DISCORD_TOKEN と LLM_API_KEY を入れる
python bot.py
```

## 3. AIの頭脳(LLM API)

`.env` の `LLM_*` を差し替えれば OpenAI互換API なら何でも動きます。

- **Google Gemini(無料枠あり)**: 初期設定のまま。モデル名はGoogleの公式ドキュメントで最新のものを確認してください
- **OpenAI**:
  ```
  LLM_BASE_URL=https://api.openai.com/v1
  LLM_MODEL=gpt-4o-mini
  ```

## 4. 人格を変える

`persona.txt` を編集してください。起動中でも次の返信から反映されます。

## 5. チャンネル内コマンド

| コマンド | 動作 |
|---|---|
| `!ai` | 状態表示 |
| `!ai off` | そのチャンネルでの自然な割り込みを停止(メンション返信は常に有効) |
| `!ai on` | 割り込みを再開 |

## 6. 常時稼働させたい場合

ボットはプロセスが起動している間だけ動きます。

- **自分のPCで**: `python bot.py` を走らせている間だけ稼働(ターミナルを閉じると停止)
- **24時間**: 下の「Fly.ioでホスティング」または VPS などで実行する

## 7. Fly.ioでホスティング(24時間稼働)

Dockerfile と fly.toml を同梱済みなので、Fly.io CLI があれば数コマンドでデプロイできます。

    # 1. Fly CLI のインストール: https://fly.io/docs/flyctl/install/
    # 2. ログイン(アカウント未作成なら fly auth signup)
    fly auth login

    # 3. このフォルダで実行
    fly launch --no-deploy      # アプリ作成。DBのセットアップは「不要」と答える
    fly secrets set DISCORD_TOKEN=... LLM_API_KEY=...   # .env ではなく secrets で渡す
    fly deploy
    fly logs                    # 起動確認。Ctrl+Cで抜けてもボットは動き続ける

補足:

- `fly.toml` の `app = "..."` は自分のアプリ名に変更(他の人と重複しない名前)
- リージョンは東京(`nrt`)を指定済み。変更したい場合は `primary_region` を編集
- トークンは `fly secrets` で渡す(`.env` は .dockerignore 済みでイメージに入りません)
- **1台のまま運用すること。** `fly scale count 2` などで複数台にすると、同じ発言に二重返信します
- 停止・削除は `fly machine stop` / `fly apps destroy <app名>`

料金は従量制です。最小構成(shared CPU / 256MBメモリ)なら月およそ$2〜3程度。
最新の単価は公式を確認してください: https://docs.fly.io/about/pricing

## セキュリティ

- トークンは `.env` に入れ、GitHubなどに絶対アップロードしない
- うっかり漏れたら Developer Portal で「Reset Token」すれば無効化できる
