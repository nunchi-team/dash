#!/usr/bin/env bash
# Выкладывает робота в Yandex Cloud Functions. Запускается из GitHub Actions.
# Секреты: YC_SA_KEY, YC_FOLDER_ID, BRIDGE_URL, BRIDGE_KEY, RECIPES_PASSWORD, (необяз.) TG_BOT_TOKEN, TG_CHAT_ID
set -u
mkdir -p robot/status
LOG=$(mktemp)
NAME=nunchi-robot

write_status() {  # $1 ok(true/false) $2 шаг $3 доп. json
  python3 - "$1" "$2" "$LOG" "${3:-{\}}" <<'PY'
import json, os, sys, datetime
ok, step, log, extra = sys.argv[1] == "true", sys.argv[2], sys.argv[3], sys.argv[4]
txt = open(log, encoding="utf-8", errors="replace").read()
for k in ("YC_SA_KEY", "BRIDGE_URL", "BRIDGE_KEY", "RECIPES_PASSWORD", "TG_BOT_TOKEN"):
    v = os.environ.get(k, "")
    if len(v) > 4: txt = txt.replace(v, "***")
lines = [l for l in txt.splitlines() if "private_key" not in l and "BEGIN" not in l][-25:]
st = dict(ok=ok, step=step, at=datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=3))).strftime("%d.%m.%Y %H:%M"), log=lines)
try: st.update(json.loads(extra))
except Exception: st["extra"] = extra[:300]
json.dump(st, open("robot/status/deploy.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
PY
}
fail() { echo "ОШИБКА на шаге: $1"; write_status false "$1"; exit 0; }

for v in YC_SA_KEY YC_FOLDER_ID BRIDGE_URL BRIDGE_KEY RECIPES_PASSWORD; do
  [ -n "${!v:-}" ] || { echo "нет секрета $v" >>"$LOG"; fail "секрет $v не задан"; }
done

curl -sSL https://storage.yandexcloud.net/yandexcloud-yc/install.sh | bash -s -- -i "$HOME/yc" -n >>"$LOG" 2>&1 || fail "установка yc"
export PATH="$HOME/yc/bin:$PATH"

KEYF=$(mktemp); printf '%s' "$YC_SA_KEY" > "$KEYF"
yc config profile create robot >>"$LOG" 2>&1
yc config set service-account-key "$KEYF" >>"$LOG" 2>&1 || fail "ключ Яндекса (YC_SA_KEY)"
yc config set folder-id "$(echo "$YC_FOLDER_ID" | tr -d '[:space:]')" >>"$LOG" 2>&1 || fail "ID каталога (YC_FOLDER_ID)"

if ! yc serverless function get --name "$NAME" >/dev/null 2>>"$LOG"; then
  yc serverless function create --name "$NAME" --description "Нунчи: рецепты, склад, варки" >>"$LOG" 2>&1 || fail "создание функции"
fi
yc serverless function allow-unauthenticated-invoke --name "$NAME" >>"$LOG" 2>&1 || fail "публичный доступ к функции"

ENVS="BRIDGE_URL=$(echo "$BRIDGE_URL" | tr -d '[:space:]'),BRIDGE_KEY=$(echo "$BRIDGE_KEY" | tr -d '[:space:]'),RECIPES_PASSWORD=$RECIPES_PASSWORD"
[ -n "${TG_BOT_TOKEN:-}" ] && ENVS="$ENVS,TG_BOT_TOKEN=$TG_BOT_TOKEN"
[ -n "${TG_CHAT_ID:-}" ] && ENVS="$ENVS,TG_CHAT_ID=$TG_CHAT_ID"
yc serverless function version create --function-name "$NAME" --runtime python312 --entrypoint main.handler \
  --memory 256m --execution-timeout 30s --source-path robot/fn --environment "$ENVS" >/dev/null 2>>"$LOG" || fail "выкладка версии"

ID=$(yc serverless function get --name "$NAME" --format json | python3 -c 'import json,sys;print(json.load(sys.stdin)["id"])')
URL="https://functions.yandexcloud.net/$ID"
printf '{"url": "%s"}\n' "$URL" > robot/endpoint.json

HEALTH=$(curl -s -m 60 -X POST "$URL" -H 'Content-Type: application/json' -d '{"action":"health"}')
echo "health: $HEALTH" >>"$LOG"
if echo "$HEALTH" | grep -q '"ok": true'; then
  write_status true "готово" "{\"url\": \"$URL\", \"health\": $HEALTH}"
else
  write_status false "робот выложен, но не читает таблицы" "{\"url\": \"$URL\"}"
fi
