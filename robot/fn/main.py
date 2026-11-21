"""Нунчи — робот (Yandex Cloud Functions, Python 3.12).

Читает Google Таблицы через мост Apps Script и отдаёт сайту рецептов готовые данные.
Запросы — POST с JSON:
  {"action": "health"}                      — проверка связи (без данных)
  {"action": "data", "pw": "..."}           — рецепты всех линеек + склад
  {"action": "publish", "pw": "...", "texts": ["..."]} — отправить варку в группу Telegram (HTML)
  {"action": "addRecipe", "pw": "...", "line": "tonics", "recipe": {...}} — дописать карточку вкуса в таблицу линейки
Переменные окружения: BRIDGE_URL, BRIDGE_KEY, RECIPES_PASSWORD, (необяз.) TG_BOT_TOKEN, TG_CHAT_ID.
"""
import base64, datetime, hmac, json, os, time, traceback, urllib.error, urllib.request

from parsers import parse_ttk, parse_stock
import cardgen

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


def tg_thread():
    tid = os.environ.get("TG_THREAD_ID", "").strip()
    if not tid:
        p = os.path.join(os.path.dirname(__file__), "tg_chat.json")
        if os.path.exists(p):
            tid = str(json.load(open(p)).get("thread_id") or "")
    return int(tid) if tid.isdigit() else None


def tg_chat():
    cid = os.environ.get("TG_CHAT_ID", "").strip()
    if not cid:
        p = os.path.join(os.path.dirname(__file__), "tg_chat.json")
        if os.path.exists(p):
            cid = str(json.load(open(p)).get("chat_id", ""))
    return cid


def bot_ready():
    return bool(os.environ.get("TG_BOT_TOKEN") and tg_chat())


_tg_direct = {}


def tg_send(text):
    msg = {"chat_id": tg_chat(), "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    if tg_thread():
        msg["message_thread_id"] = tg_thread()
    token = os.environ["TG_BOT_TOKEN"]
    res, direct_err = None, _tg_direct.get("err")
    if time.time() - _tg_direct.get("t", 0) > 600:
        direct_err = None
    if direct_err is None:
      try:  # напрямую (из облака Яндекса Telegram может быть недоступен)
        req = urllib.request.Request("https://api.telegram.org/bot%s/sendMessage" % token,
                                     data=json.dumps(msg).encode(), headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=4) as r:
                res = json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            res = json.loads(e.read().decode() or "{}")
      except Exception as e:
        direct_err = e
        _tg_direct.update(err=str(e), t=time.time())
    if res is None:  # через мост Google
        try:
            res = bridge([{"action": "telegram", "token": token, "method": "sendMessage", "payload": msg}], timeout=20)[0]
        except Exception as e:
            raise RuntimeError("Telegram недоступен из облака (%s), а мост ещё старой версии: %s" % (direct_err, e))
    if not res.get("ok"):
        raise RuntimeError("Telegram: " + str(res.get("description", "ошибка")))


UNITS = ("г", "кг", "мл", "л")
GROUPS = [g for g in cardgen.GROUP_ORDER if g not in ("Сахар", "Сироп")]


def probe_notation(sid, nrows):
    """Какую запись формул понимает таблица: en (запятые) или ru (точки с запятой). Пробует в пустой ячейке и стирает."""
    cell = "AD%d" % (nrows + 5)
    rng = "%s:AD%d" % (cell, nrows + 6)
    res = bridge([{"action": "formulas", "id": sid, "range": rng, "values": [["=SUM(1,2)"], ["=SUM(1;2)"]]},
                  {"action": "read", "id": sid}])
    vals = res[1]["values"]
    get = lambda r: vals[r][29] if r < len(vals) and len(vals[r]) > 29 else None
    en, ru = get(nrows + 4), get(nrows + 5)
    bridge([{"action": "write", "id": sid, "range": rng, "values": [[""], [""]]}])
    _probe["last"] = {"en": en, "ru": ru}
    return "ru" if ru == 3 and en != 3 else "en"


_probe = {}


def add_recipe(line, rec, sheet_id=None, stock_id=None):
    """Проверяет рецепт и дописывает карточку в таблицу линейки. Возвращает краткий итог."""
    ids = {k: sid for k, _, sid in LINES}
    if line not in ids and not sheet_id:
        raise ValueError("неизвестная линейка")
    sid = sheet_id or ids[line]
    name = " ".join(str(rec.get("name") or "").split())
    if len(name) < 2:
        raise ValueError("укажите название вкуса")
    vals = bridge([{"action": "read", "id": sid}])[0]["values"]
    ref = parse_ttk(vals)["ref"]
    new_ref, seen = [], set(ref)
    for n in rec.get("newRef") or []:
        nm = " ".join(str(n.get("name") or "").split())
        if not nm or nm in seen:
            continue
        if n.get("group") not in GROUPS:
            raise ValueError("у нового сырья «%s» не выбрана группа" % nm)
        new_ref.append(dict(name=nm, group=n["group"], ss=float(n.get("ss") or 0), acid=float(n.get("acid") or 0),
                            density=float(n.get("density") or 1), supplier=str(n.get("supplier") or "")[:80]))
        seen.add(nm)
    items = []
    for it in rec.get("items") or []:
        nm = " ".join(str(it.get("name") or "").split())
        if not nm:
            continue
        if nm not in seen:
            raise ValueError("сырья «%s» нет в справочнике — добавьте его как новое" % nm)
        if (ref.get(nm) or {}).get("group") in ("Сахар", "Сироп"):
            continue  # сахар и сироп считаются сами
        v = float(it.get("value") or 0)
        if v <= 0:
            raise ValueError("у «%s» не указана норма" % nm)
        u = it.get("unit") if it.get("unit") in UNITS else "г"
        ou = it.get("outUnit") if it.get("outUnit") in ("г", "кг", "л") else "г"
        items.append(dict(name=nm, value=v, unit=u, outUnit=ou, comment=str(it.get("comment") or "")[:200]))
    if not items:
        raise ValueError("добавьте хотя бы один ингредиент")
    clean = dict(name=name, status=rec.get("status") if rec.get("status") in ("Актив", "R&D", "Архив") else "R&D",
                 category=str(rec.get("category") or ""), bottleMl=float(rec.get("bottleMl") or 0) or None,
                 water=float(rec.get("water") or 0) or None, sweetener="Сахар" if rec.get("sweetener") == "Сахар" else "Сироп ВЛ",
                 brixTarget=float(rec.get("brixTarget") or 0) or None, syrupBrix=float(rec.get("syrupBrix") or 0) or None,
                 items=items, newRef=new_ref)
    allref = dict(ref, **{n["name"]: n for n in new_ref})
    cardgen.NOTATION["v"] = probe_notation(sid, len(vals))
    ops = cardgen.plan_ops(sid, vals, clean, allref)
    bridge(ops, timeout=50)
    if new_ref and stock_id != "-":  # новое сырьё — и на склад, с нулевым остатком
        try:
            stid = stock_id or STOCK_ID
            sv = bridge([{"action": "read", "id": stid}])[0]["values"]
            last = max([i for i, r in enumerate(sv) if r and str(r[0]).strip()] or [3]) + 1
            have = {str(r[0]).strip() for r in sv if r}
            rows = [[n["name"], 0, "кг", "", "добавлено с сайта"] for n in new_ref if n["name"] not in have]
            if rows:
                bridge([{"action": "write", "id": stid, "range": "A%d:E%d" % (last + 1, last + len(rows)), "values": rows}])
        except Exception:
            traceback.print_exc()
    _cache["data"] = None
    return dict(name=name, items=len(items), newRef=len(new_ref), ops=len(ops), notation=cardgen.NOTATION["v"], probe=_probe.get("last"))


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
            return reply(200, {"ok": True, "bot": bot_ready(), "lines": {l["key"]: len(l["recipes"]) for l in d["lines"]},
                               "stock": len(d.get("stock", {})), "errors": d["errors"], "updated": d["updated"]})
        if action == "data":
            if not check_pw(req.get("pw")):
                time.sleep(1)
                return reply(401, {"ok": False, "error": "wrong password"})
            d = dict(get_data(fresh=bool(req.get("fresh"))), botReady=bot_ready())
            return reply(200, {"ok": True, "data": d})
        if action == "tgcheck":  # диагностика связи с Telegram из облака
            out = {}
            for host in ("https://api.telegram.org", "https://ya.ru", "https://script.google.com"):
                t0 = time.time()
                try:
                    urllib.request.urlopen(host, timeout=10).read(100); out[host] = "ok %.1fs" % (time.time() - t0)
                except urllib.error.HTTPError as e:
                    out[host] = "http %s %.1fs" % (e.code, time.time() - t0)
                except Exception as e:
                    out[host] = "FAIL %s %.1fs" % (e, time.time() - t0)
            return reply(200, {"ok": True, "net": out})
        if action == "publish":
            if not check_pw(req.get("pw")):
                time.sleep(1)
                return reply(401, {"ok": False, "error": "wrong password"})
            if not bot_ready():
                return reply(409, {"ok": False, "error": "бот не настроен"})
            texts = [str(t)[:4000] for t in (req.get("texts") or [])][:10]
            for t in texts:
                tg_send(t)
                time.sleep(0.4)
            return reply(200, {"ok": True, "sent": len(texts)})
        if action == "addRecipe":
            if not check_pw(req.get("pw")):
                time.sleep(1)
                return reply(401, {"ok": False, "error": "wrong password"})
            try:
                res = add_recipe(req.get("line"), req.get("recipe") or {})
            except ValueError as e:
                return reply(400, {"ok": False, "error": str(e)})
            return reply(200, {"ok": True, "added": res})
        return reply(400, {"ok": False, "error": "unknown action"})
    except Exception as e:
        traceback.print_exc()
        return reply(502, {"ok": False, "error": str(e)})
