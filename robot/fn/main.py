"""Нунчи — робот (Yandex Cloud Functions, Python 3.12).

Читает Google Таблицы через мост Apps Script и отдаёт сайту рецептов готовые данные.
Запросы — POST с JSON:
  {"action": "health"}                      — проверка связи (без данных)
  {"action": "data", "pw": "..."}           — рецепты всех линеек + склад
Переменные окружения: BRIDGE_URL, BRIDGE_KEY, RECIPES_PASSWORD, (необяз.) TG_BOT_TOKEN, TG_CHAT_ID.
"""
import base64, datetime, hmac, json, os, time, traceback, urllib.request

from parsers import parse_ttk, parse_stock

# Таблицы: ключ линейки, название вкладки на сайте, ID Google-таблицы
LINES = [
    ("tonics", "Тоники", "1SfymN7cuuXXWasY-biRdKRXblA_b2CIq1XwfdLme2MY"),
    ("cordials", "Кордиалы", "1n0Ns7Ohv0L1lH2isubK1SMmNwUTu8Sy2UNf_-FDJ4MM"),
]
STOCK_ID = "1T3rjbM9DYl-h_cDJNriDN7_krTV2UTIEFRg1gWwLi_M"
CACHE_SEC = 45
MSK = datetime.timezone(datetime.timedelta(hours=3))

_cache = {"t": 0, "data": None}


def bridge(ops, timeout=25):
    body = json.dumps({"key": os.environ["BRIDGE_KEY"], "ops": ops}).encode()
    req = urllib.request.Request(os.environ["BRIDGE_URL"], data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # 302 → GET на googleusercontent обрабатывается urllib
        res = json.loads(r.read().decode())
    if not res.get("ok"):
        raise RuntimeError("мост: " + str(res.get("error")))
    return res["results"]


def build_data():
    ops = [{"action": "read", "id": sid} for _, _, sid in LINES] + [{"action": "read", "id": STOCK_ID}]
    res = bridge(ops)
    lines, errors = [], []
    for (key, title, sid), r in zip(LINES, res):
        try:
            d = parse_ttk(r["values"])
            lines.append(dict(key=key, title=title, recipes=d["tonics"], ref=d["ref"], modified=r.get("modified")))
        except Exception as e:  # одна сломанная таблица не роняет весь сайт
            errors.append(f"{title}: таблица не разобралась ({e})")
            lines.append(dict(key=key, title=title, recipes=[], ref={}, error=str(e)))
    data = dict(lines=lines, updated=datetime.datetime.now(MSK).strftime("%d.%m.%Y %H:%M"), live=True, errors=errors)
    try:
        data.update(parse_stock(res[-1]["values"]))
    except Exception as e:
        errors.append(f"Склад: таблица не разобралась ({e})")
    return data


def get_data(fresh=False):
    if fresh or not _cache["data"] or time.time() - _cache["t"] > CACHE_SEC:
        _cache["data"] = build_data()
        _cache["t"] = time.time()
    return _cache["data"]


def check_pw(pw):
    want = os.environ.get("RECIPES_PASSWORD", "")
    return bool(want) and hmac.compare_digest(str(pw or "").encode(), want.encode())


def reply(code, obj):
    return {
        "statusCode": code,
        "headers": {
            "Content-Type": "application/json; charset=utf-8",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type",
            "Cache-Control": "no-store",
        },
        "body": json.dumps(obj, ensure_ascii=False),
    }


def handler(event, context):
    if (event.get("httpMethod") or "").upper() == "OPTIONS":
        return reply(204, {})
    try:
        body = event.get("body") or ""
        if event.get("isBase64Encoded"):
            body = base64.b64decode(body).decode()
        req = json.loads(body or "{}")
    except Exception:
        return reply(400, {"ok": False, "error": "bad request"})
    action = req.get("action")
    try:
        if action == "health":
            d = get_data(fresh=True)
            return reply(200, {"ok": True, "lines": {l["key"]: len(l["recipes"]) for l in d["lines"]},
                               "stock": len(d.get("stock", {})), "errors": d["errors"], "updated": d["updated"]})
        if action == "data":
            if not check_pw(req.get("pw")):
                time.sleep(1)
                return reply(401, {"ok": False, "error": "wrong password"})
            return reply(200, {"ok": True, "data": get_data(fresh=bool(req.get("fresh")))})
        return reply(400, {"ok": False, "error": "unknown action"})
    except Exception as e:
        traceback.print_exc()
        return reply(502, {"ok": False, "error": str(e)})
