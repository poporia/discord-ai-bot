#!/bin/bash
# 1つのRenderサービスで2体のボットを同時に動かす起動スクリプト
#
# 使い方:
#   1. Renderの Start Command を `bash start.sh` に変更する
#   2. Renderの環境変数に2体目分を追加(B2_ というプレフィックスを付ける):
#        B2_DISCORD_TOKEN          = 2体目のボットトークン
#        B2_BOT_NAME               = 2体目の表示名
#        B2_GOMAMAYO_ONLY          = 1   ← ゴママヨ検出専門にする(雑談しない)
#        B2_GOMAMAYO_PROB          = 1.0        (お好みで: 専門ボットなら毎回指摘)
#        B2_GOMAMAYO_COOLDOWN      = 30         (お好みで)
#        B2_GOMAMAYO_MESSAGE       = それ、ゴママヨですよ⁉
#        B2_ALLOWED_CHANNEL_IDS    = 動かしたいチャンネル(未指定なら全チャンネルで検出)
#        (Blueskyもやらせるなら B2_BSKY_HANDLE / B2_BSKY_PASSWORD)
#      1体目は今まで通りの変数名(プレフィックスなし)のまま
#   3. GitHub に persona2.txt をアップロードしてからデプロイ
#
# 1体だけでいい場合は Start Command を `python bot.py` に戻せばOK
#
# ★ botプロセスが例外などで死んでも10秒後に自動再起動します。
#    健康チェック用Webサーバーは bot.py の外(このスクリプト)ではないため、
#    botだけが死んだ状態を防ぎます。

# 1体目(通常の環境変数: DISCORD_TOKEN など)
while true; do
  python bot.py
  echo "[start.sh] 1体目が落ちたので10秒後に再起動します"
  sleep 10
done &

# 2体目(B2_ プレフィックスの環境変数: B2_DISCORD_TOKEN など)
while true; do
  BOT_ENV_PREFIX=B2 python bot.py
  echo "[start.sh] 2体目が落ちたので10秒後に再起動します"
  sleep 10
done &

wait
