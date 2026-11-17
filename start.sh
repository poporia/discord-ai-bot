#!/bin/bash
# 1つのRenderサービスで2体のボットを同時に動かす起動スクリプト

python bot.py &
BOT_ENV_PREFIX=B2 python bot.py &
wait
