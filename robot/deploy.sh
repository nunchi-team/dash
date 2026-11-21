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
FOLDER=$(echo "$YC_FOLDER_ID" | tr -d '[:space:]')
if [ "${FOLDER:0:3}" != "b1g" ]; then
  # в секрете не ID каталога — берём каталог, где живёт сервисный аккаунт
  SA_ID=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["service_account_id"])' "$KEYF" 2>>"$LOG")
  FOLDER=$(yc iam service-account get --id "$SA_ID" --format json 2>>"$LOG" | python3 -c 'import json,sys;print(json.load(sys.stdin)["folder_id"])' 2>>"$LOG")
  [ -n "$FOLDER" ] || FOLDER="b1g6vsokqeducjk9l8vl"   # каталог default (из консоли)
  echo "YC_FOLDER_ID не похож на ID каталога, использую $FOLDER" >>"$LOG"
fi
yc config set folder-id "$FOLDER" >>"$LOG" 2>&1 || fail "ID каталога (YC_FOLDER_ID)"
unset YC_FOLDER_ID   # иначе yc берёт каталог из окружения, а не из настроек

if ! yc serverless function get --name "$NAME" >/dev/null 2>>"$LOG"; then
  yc serverless function create --name "$NAME" --description "Нунчи: рецепты, склад, варки" >>"$LOG" 2>&1 || fail "создание функции"
fi
yc serverless function allow-unauthenticated-invoke --name "$NAME" >>"$LOG" 2>&1 || fail "публичный доступ к функции"

# группа Telegram: ищем по сообщению /start@бот в группе (getUpdates), сохраняем в robot/fn/tg_chat.json
if [ -n "${TG_BOT_TOKEN:-}" ] && [ -z "${TG_CHAT_ID:-}" ] && [ ! -s robot/fn/tg_chat.json ]; then
  curl -s -m 20 "https://api.telegram.org/bot$TG_BOT_TOKEN/getUpdates?allowed_updates=%5B%22message%22,%22my_chat_member%22%5D" | python3 -c '
import json, sys
d = json.load(sys.stdin)
chat = None
for u in d.get("result", []):
    m = u.get("message") or u.get("my_chat_member") or {}
    c = m.get("chat") or {}
    if c.get("type") in ("group", "supergroup"):
        chat = {"chat_id": c["id"], "title": c.get("title", "")}
if chat:
    json.dump(chat, open("robot/fn/tg_chat.json", "w"), ensure_ascii=False)
    print("группа найдена:", chat["title"])
    open("/tmp/tg_new", "w").write("1")
else:
    print("группа не найдена: бот не видел сообщений в группе", d.get("description", ""))
' >>"$LOG" 2>&1
fi

ENVS="BRIDGE_URL=$(echo "$BRIDGE_URL" | tr -d '[:space:]'),BRIDGE_KEY=$(echo "$BRIDGE_KEY" | tr -d '[:space:]'),RECIPES_PASSWORD=$RECIPES_PASSWORD"
[ -n "${TG_BOT_TOKEN:-}" ] && ENVS="$ENVS,TG_BOT_TOKEN=$TG_BOT_TOKEN"
[ -n "${TG_CHAT_ID:-}" ] && ENVS="$ENVS,TG_CHAT_ID=$TG_CHAT_ID"
yc serverless function version create --function-name "$NAME" --runtime python312 --entrypoint main.handler \
  --memory 256m --execution-timeout 30s --source-path robot/fn --environment "$ENVS" >/dev/null 2>>"$LOG" || fail "выкладка версии"

ID=$(yc serverless function get --name "$NAME" --format json | python3 -c 'import json,sys;print(json.load(sys.stdin)["id"])')
URL="https://functions.yandexcloud.net/$ID"
printf '{"url": "%s"}\n' "$URL" > robot/endpoint.json

if [ -f /tmp/tg_new ]; then
  CID=$(python3 -c 'import json;print(json.load(open("robot/fn/tg_chat.json"))["chat_id"])')
  curl -s -m 20 -X POST "https://api.telegram.org/bot$TG_BOT_TOKEN/sendMessage" -H 'Content-Type: application/json' \
    -d "{\"chat_id\": $CID, \"text\": \"👋 Бот Нунчи подключён. Сюда будут приходить варки с сайта рецептов.\"}" | python3 -c 'import json,sys;d=json.load(sys.stdin);print("приветствие:", "ok" if d.get("ok") else d.get("description"))' >>"$LOG" 2>&1
fi
HEALTH=$(curl -s -m 60 -X POST "$URL" -H 'Content-Type: application/json' -d '{"action":"health"}')
echo "health: $HEALTH" >>"$LOG"
if echo "$HEALTH" | grep -q '"ok": true'; then
  write_status true "готово" "{\"url\": \"$URL\", \"health\": $HEALTH}"
else
  write_status false "робот выложен, но не читает таблицы" "{\"url\": \"$URL\"}"
fi
