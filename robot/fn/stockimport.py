"""Импорт остатков из отчёта 1С «Остатки» (Google-таблица в папке «Нунчи склад остатки») в таблицу «Нунчи склад — остатки».

Отчёт: строка 1 — «Организация | Итого по всем складам | … | Основной склад | … | Тихвин …»,
строка 2 — «Номенклатура | Остаток | Резерв | Свободно | …», дальше позиции, в конце «Итого».
Берём только сырьё (по началу названия), остаток «Итого по всем складам» и остатки по каждому складу.
Единицы и связь с названиями в рецептах, которые пользователь поправил в таблице склада, сохраняются при следующих загрузках.
"""
import datetime
import re

MSK = datetime.timezone(datetime.timedelta(hours=3))
STOCK_NAME = "Нунчи склад — остатки"

RAW = [  # (начало названия в 1С, единица по умолчанию)
    ("Ароматизатор", "г"), ("Ботаникал", "г"), ("Экстракт", "г"), ("Кислота Лимонная", "кг"), ("Кислота", "г"),
    ("Сахароза", "кг"), ("Сахар", "кг"), ("Сироп", "л"), ("Сок", "кг"), ("Пюре", "кг"), ("Концентрат", "кг"),
    ("Сорбат", "г"), ("Бензоат", "г"), ("Ксантан", "г"), ("Гуммиарабик", "кг"), ("Краситель", "г"),
    ("Мирт", "г"), ("Мята", "г"), ("Тонка", "г"), ("Листья", "г"), ("Микс трав", "г"), ("Соль", "кг"), ("Эмульсия", "г"), ("Нейтральная эмульсия", "г"),
]

# названия в рецептах → название в 1С (первичная привязка; дальше её можно править в колонке «Название в рецептах»)
ALIASES = {
    "Сахароза": ["Сахар"],
    "Кислота Лимонная  1кг": ["Кислота лимонная"], "Кислота Яблочная": ["Кислота яблочная"], "Кислота Молочная": ["Кислота молочная 80%"],
    "Ботаникал Хинин": ["Хинин"],
    "Ароматизатор лимон лайм": ["Аромка лимон-лайм"], "Ароматизатор Персик": ["Аромка персик"], "Ароматизатор Жасмин": ["Аромка жасмин"],
    "Ароматизатор Клюква": ["Аромка клюква"], "Ароматизатор Цитрус": ["Аромка цитрус"], "Ароматизатор Бузина цветки": ["Аромка бузина"],
    "Ароматизатор Груша": ["Аромка груша"], "Ароматизатор Трава зеленая": ["Аромка трава зелёная"], "Ароматизатор Березовый сок": ["Аромка береза"],
    "Ароматизатор Розовый грейпфрут": ["Аромка розовый грейпфрут"], "Ароматизатор Полынь": ["Аромка полынь"], "Ароматизатор Яблоко": ["Аромка яблоко"],
    "Экстракт Грейпфрут": ["СО2 грейпфрут"], "Экстракт Береза лист": ["СО2 лист березы"], "Экстракт Вербена": ["СО2 вербена"],
    "Экстракт Чабрец": ["СО2 чабрец"], "Экстракт Можжевеловая ягода": ["СО2 можжевельник"], "Экстракт Корица": ["СО2 корица"],
    "Экстракт Шалфей лекарственный": ["СО2 шалфей"], "Экстракт Имбирный": ["СО2 купаж имбирный"], "Экстракт Кардамон": ["СО2 кардамон"],
    "Экстракт Полынь": ["СО2 полынь"], "Экстракт Лемонграсс": ["СО2 лемонграсс"], "Экстракт Кофе": ["Экстракт кофе"], "Экстракт Липа": ["Экстракт липа"],
    "Ботаникал Лист лайма": ["Лист лайма"], "Ботаникал Розовый перец": ["Розовый перец"], "Ботаникал Ройбуш": ["Ройбос"],
    "Ботаникал Персика Цветы": ["Цветы персика"], "Ботаникал Жасмина Цветы": ["Цветы жасмина"], "Ботаникал Зизифора трава": ["Зизифора"],
    "Ботаникал Шалфей": ["Шалфей"], "Ботаникал Подсолнух лепестки": ["Подсолнух"], "Мирт Австралийский": ["Лимонный мирт"],
    "Ботаникал Куркума": ["Куркума сухой экстракт"],
    "Сок  Береза": ["Сок березовый"], "Сок натуральный березовый": ["Сок березовый"], "Сок Лайм": ["Сок лайма"], "Сок Яблоко": ["Конц. яблоко"], "Сок Грейпфрут Баринофф": ["Конц. грейпфрут"],
    "Сок Брусники": ["Конц. брусника"], "Сок Груша": ["Конц. груша"], "Сок Клюква": ["Конц. клюква Меркурий", "Конц. клюква Инкос"],
    "Гуммиарабик (Е414)": ["Гуммиарабик"],
}


# типовые свойства по виду сырья: (начало названия, группа, СВ %, кислотность % лим.экв, плотность, пометка)
PROPS = [
    ("Ботаникал Хинин", "Хинин", 100, 0, 1, ""),
    ("Ароматизатор", "Ароматизатор", 0, 0, 1, ""), ("Ботаникал", "Травы", 0, 0, 1, ""),
    ("Экстракт", "CO2-экстракт", 0, 0, 1, ""),
    ("Кислота Лимонная", "Кислота", 100, 100, 1, ""), ("Кислота Яблочная", "Кислота", 100, 95.5, 1, ""),
    ("Кислота Молочная", "Кислота", 80, 56.9, 1.2, "80%?"), ("Кислота Аскорбиновая", "Кислота", 100, 36.4, 1, ""),
    ("Кислота", "Кислота", 100, 100, 1, "кислотность уточнить"),
    ("Сахароза", "Сахар", 100, 0, 1.59, ""), ("Сахар", "Сахар", 100, 0, 1.59, ""),
    ("Сок", "Сок", 65, 0, 1.32, "СВ/кисл. уточнить"), ("Пюре", "Сок", 15, 0, 1.05, "СВ/кисл. уточнить"),
    ("Концентрат", "Сок", 65, 0, 1.32, "кисл. уточнить"),
    ("Сорбат", "Консервант", 100, 0, 1, ""), ("Бензоат", "Консервант", 100, 0, 1, ""),
    ("Ксантан", "Гидроколлоид", 90, 0, 1, ""), ("Гуммиарабик", "Гидроколлоид", 90, 0, 1, ""),
    ("Эмульсия", "Гидроколлоид", 0, 0, 1, ""), ("Краситель", "Прочее", 0, 0, 1, ""), ("Соль", "Соль", 100, 0, 1, ""),
    ("Мирт", "Травы", 0, 0, 1, ""), ("Мята", "Травы", 0, 0, 1, ""), ("Тонка", "Травы", 0, 0, 1, ""),
    ("Листья", "Травы", 0, 0, 1, ""), ("Микс трав", "Травы", 0, 0, 1, ""),
]


def default_props(name):
    for pref, g, ss, ac, d, note in PROPS:
        if name.lower().startswith(pref.lower()):
            return dict(group=g, ss=ss, acid=ac, density=d, note=note)
    return dict(group="Прочее", ss=0, acid=0, density=1, note="")


def norm(name):
    """Название без лишних пробелов (в HTML-рассылке 1С двойные пробелы схлопываются)."""
    return " ".join(str(name or "").split())


ALIASES = {norm(k): v for k, v in ALIASES.items()}

# Точная связь по коду 1С (не ломается при переименовании). Одно название рецепта на несколько кодов —
# это одно сырьё от разных поставщиков: остатки складываются.
CODE_ALIASES = {
    "НФ-00000095": ["Аромка клюква"], "НФ-00000457": ["Аромка клюква Кима"],
    "НФ-00000110": ["Конц. клюква Меркурий"], "НФ-00000445": ["Конц. клюква Инкос"],
    "НФ-00000155": ["Конц. брусника"], "НФ-00000444": ["Конц. брусника"],
    "НФ-00000452": ["Аромка терпкость"], "НФ-00000454": ["Нейтральная эмульсия"],
    "НФ-00000443": ["Аромка облепиха"], "НФ-00000438": ["Конц. облепиха"],
    "НФ-00000453": ["Аромка крем-сода"], "НФ-00000458": ["Аромка крем-сода"],
    "НФ-00000106": ["Имбирь сухой экстракт"],
}
CLAIMED = {a: {c for c, v in CODE_ALIASES.items() if a in v} for v in CODE_ALIASES.values() for a in v}


def _num(v):
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).replace(" ", "").replace(" ", "").replace(",", "."))
    except ValueError:
        return None


CODE_RE = re.compile(r"^(.*?),\s*([A-Za-zА-Яа-яЁё]{1,4}-?\d{3,})$")


ONLY_CODE_RE = re.compile(r"^[A-Za-zА-Яа-яЁё]{1,4}-?\d{3,}$")


def split_code(cell):
    """«Кислота Лимонная 1кг, НФ-00000002» → («Кислота Лимонная 1кг», «НФ-00000002»)."""
    n = norm(cell)
    m = CODE_RE.match(n)
    return (m.group(1).strip(), m.group(2)) if m else (n, "")


def is_report(values):
    head = [str(c).strip() for r in values[:6] for c in r]
    return any(h.startswith("Номенклатура") for h in head) and "Остаток" in head


def raw_unit(name):
    n = name.strip()
    for pref, unit in RAW:
        if n.lower().startswith(pref.lower()):
            return unit
    return None


def parse_report(values):
    """→ (склады, позиции[{name, qty, free, wh:{склад: qty}}])"""
    hdr = next(i for i, r in enumerate(values[:10]) if r and str(r[0]).strip().startswith("Номенклатура"))
    top = values[hdr - 1] if hdr > 0 else []
    sub = values[hdr]
    groups, cur = [], None  # (название склада, колонка «Остаток», колонка «Свободно»)
    for j in range(1, len(sub)):
        lab = str(top[j]).strip() if j < len(top) else ""
        if lab:
            cur = {"name": lab, "rest": None, "free": None}
            groups.append(cur)
        if cur is None:
            continue
        s = str(sub[j]).strip()
        if s == "Остаток" and cur["rest"] is None:
            cur["rest"] = j
        elif s == "Свободно" and cur["free"] is None:
            cur["free"] = j
    total = next((g for g in groups if g["name"].lower().startswith("итого")), groups[0] if groups else None)
    whs = [g for g in groups if g is not total]
    items, pend = [], ""
    for r in values[hdr + 1:]:
        if not r or not str(r[0]).strip():
            continue
        c0 = norm(r[0])
        if ONLY_CODE_RE.match(c0):  # вид «код строкой выше, название под ним»
            pend = c0
            continue
        name, code = split_code(r[0])
        code, pend = code or pend, ""
        if name.lower().startswith("итого") or raw_unit(name) is None:
            continue
        get = lambda j: _num(r[j]) if j is not None and j < len(r) else None
        items.append(dict(name=name, code=code, qty=get(total["rest"]) or 0.0, free=get(total["free"]),
                          wh={g["name"]: get(g["rest"]) or 0.0 for g in whs}))
    return [g["name"] for g in whs], items


PROP_HDR = ["Группа", "СВ, %", "Кисл., %", "Плотность, кг/л"]


LINK_HDR = ["Сырьё из рецептов — нет на складе", "В каких рецептах", "Код 1С (впиши, напр. НФ-00000198)"]


def read_links(values):
    """Ручные связи из блока «нет на складе»: код 1С или название 1С → [названия из рецептов]."""
    links = {}
    try:
        h = next(i for i, r in enumerate(values) if r and str(r[0]).strip().startswith("Сырьё"))
        c = next(j for j, x in enumerate(values[h]) if str(x).strip() == LINK_HDR[0])
    except StopIteration:
        return links
    for r in values[h + 1:]:
        if len(r) > c + 2 and str(r[c]).strip() and str(r[c + 2]).strip():
            links.setdefault(norm(r[c + 2]).upper(), []).append(norm(r[c]))
    return links


def build_stock_rows(whs, items, current, refs=None, links=None):
    """current: имя → {unit, alias, code, note, props} из текущей таблицы склада (правки пользователя сохраняем).
    refs: справочники ТТК (имя → свойства) — для позиций, уже используемых в рецептах."""
    refs = refs or {}
    hdr = ["Сырьё (как в 1С)", "Остаток", "Ед.", "Код 1С", "Комментарий", "Название в рецептах"] + PROP_HDR + ["Склад: " + w for w in whs]
    rows = []
    names = {it["name"] for it in items}
    bycode = {str(v.get("code")).strip(): v for v in current.values() if str(v.get("code") or "").strip()}

    def renamed(name, table):
        """1С переименовали позицию («Ароматизатор Полынь» → «Ароматизатор Полынь Тарасов»):
        берём самое длинное старое название, с которого начинается новое, если старого в отчёте больше нет."""
        low = name.lower()
        keys = [k for k in table if k not in names and low.startswith(k.lower() + " ")]
        if not keys:
            return None
        k = max(keys, key=len)
        if sum(1 for n in names if n.lower().startswith(k.lower() + " ")) > 1:
            return None  # «Ароматизатор Клюква» → Делер и Кима: не угадываем
        return table[k]

    for it in sorted(items, key=lambda x: x["name"].lower()):
        c = current.get(it["name"]) or bycode.get(it.get("code") or "") or {}
        if not c.get("alias"):
            old = renamed(it["name"], {k: v for k, v in current.items() if v.get("alias")})
            if old:
                c = dict(c or old, alias=old["alias"])
        unit = c.get("unit") or raw_unit(it["name"])
        auto = ALIASES.get(it["name"]) or renamed(it["name"], ALIASES) or []
        alias = c.get("alias") if c.get("alias") is not None and c.get("alias") != "" else "; ".join(auto)
        extra = (links or {}).get(str(it.get("code") or "").upper(), []) + (links or {}).get(it["name"].upper(), [])
        code = str(it.get("code") or "").upper()
        extra = CODE_ALIASES.get(code, []) + extra
        have = [a.strip() for a in str(alias).split(";") if a.strip()]
        have = [a for a in have if a not in CLAIMED or code in CLAIMED[a]]  # название закреплено за другим кодом
        alias = "; ".join(have + [a for a in extra if a not in have])
        note = c.get("note") if c else "ед. проверить"
        pr = c.get("props")
        if not pr or pr.get("group") in (None, ""):
            known = next((refs[a.strip()] for a in [it["name"]] + str(alias).split(";") if a.strip() in refs), None)
            pr = dict(known) if known else default_props(it["name"])
            if not known and pr.get("note"):
                note = "; ".join(x for x in [note, pr["note"]] if x)
        rows.append([it["name"], it["qty"], unit, it.get("code") or c.get("code", ""), note or "", alias,
                     pr.get("group", ""), pr.get("ss", 0), pr.get("acid", 0), pr.get("density", 1)] + [it["wh"].get(w, 0) for w in whs])
    return hdr, rows


def read_current(values):
    cur = {}
    try:
        h = next(i for i, r in enumerate(values) if r and str(r[0]).strip().startswith("Сырьё"))
    except StopIteration:
        return cur
    hdrrow = [str(x).strip() for x in values[h]]
    hasalias = len(hdrrow) > 5 and hdrrow[5].startswith("Название в рецептах")
    hasprops = len(hdrrow) > 9 and hdrrow[6] == "Группа"
    for r in values[h + 1:]:
        if not r or not str(r[0]).strip():
            continue
        e = dict(unit=str(r[2]).strip() if len(r) > 2 and r[2] != "" else "",
                 code=r[3] if len(r) > 3 else "", note=r[4] if len(r) > 4 else "",
                 alias=(r[5] if hasalias and len(r) > 5 else None))
        if hasprops and str(r[6]).strip():
            e["props"] = dict(group=str(r[6]).strip(), ss=_num(r[7]) or 0, acid=_num(r[8]) or 0, density=_num(r[9]) or 1)
        cur[norm(r[0])] = e
    return cur


def run(bridge, stock_id, force=False, ttk_ids=()):
    """Ищет свежий отчёт 1С в папке склада и переносит в таблицу склада. Возвращает итог (dict)."""
    files = bridge([{"action": "list"}])[0]["files"]
    folder = next((f["path"] for f in files if f["id"] == stock_id), None)
    cands = [f for f in files if f["id"] != stock_id and (folder is None or f["path"] == folder)]
    cands.sort(key=lambda f: f["modified"], reverse=True)
    reads = bridge([{"action": "read", "id": stock_id}] + [{"action": "read", "id": f["id"]} for f in cands[:5]])
    stock_vals, others = reads[0]["values"], reads[1:]
    src = next(((f, r) for f, r in zip(cands, others) if is_report(r["values"])), None)
    if not src:
        return {"ok": True, "imported": False, "reason": "в папке склада нет отчёта 1С (таблица с колонками «Номенклатура» и «Остаток»)"}
    f, rep = src
    stamp = "%s|%s|v6" % (f["id"], f["modified"])  # v2 — формат со свойствами сырья
    marker = str(stock_vals[1][4]).strip() if len(stock_vals) > 1 and len(stock_vals[1]) > 4 else ""
    if marker == stamp and not force and not read_links(stock_vals):
        return {"ok": True, "imported": False, "reason": "этот отчёт уже загружен", "source": f["name"]}
    whs, items = parse_report(rep["values"])
    refs, used = {}, {}
    try:
        from parsers import parse_ttk
        for r in bridge([{"action": "read", "id": i} for i in ttk_ids]) if ttk_ids else []:
            t = parse_ttk(r["values"])
            for n, v in t["ref"].items():
                refs.setdefault(n, v)
            for rec in t["tonics"]:
                for ing in rec["items"]:
                    if not ing.get("auto") and ing["name"]:
                        used.setdefault(ing["name"], []).append(rec["name"])
    except Exception:
        refs, used = {}, {}
    links = read_links(stock_vals)
    hdr, rows = build_stock_rows(whs, items, read_current(stock_vals), refs, links)
    ulow = {n.lower(): n for n in used}
    for r in rows:  # «Сок Манго» в 1С = «Сок манго» в рецепте: дописываем точное написание из рецепта
        n = ulow.get(r[0].lower())
        have = [a.strip() for a in str(r[5]).split(";") if a.strip()]
        if n and n != r[0] and n not in have:
            r[5] = "; ".join(have + [n])
    known = {r[0].lower() for r in rows} | {a.strip().lower() for r in rows for a in str(r[5]).split(";") if a.strip()}
    miss = sorted((n for n in used if n.lower() not in known and (refs.get(n, {}).get("group") or "") != "Вода"), key=str.lower)
    hdr = hdr + [""] + LINK_HDR
    rows = [r + [""] * 4 for r in rows]
    for k, n in enumerate(miss):
        if k >= len(rows):
            rows.append([""] * len(hdr))
        rows[k][-4:] = ["", n, ", ".join(sorted(set(used[n]))), ""]
    width = max(len(hdr), max((len(r) for r in stock_vals), default=0))
    hdr = hdr + [""] * (width - len(hdr))
    mod = datetime.datetime.fromisoformat(f["modified"].replace("Z", "+00:00")).astimezone(MSK)
    old_n = max(len(stock_vals), 5)
    body = [hdr] + rows + [[""] * width for _ in range(max(0, old_n - 4 - len(rows)) + 5)]
    body = [r + [""] * (width - len(r)) for r in body]
    col = (chr(ord("A") + (width - 1) // 26 - 1) if width > 26 else "") + chr(ord("A") + (width - 1) % 26)
    ops = [
        {"action": "write", "id": stock_id, "range": "A1:E2", "values": [
            ["Нунчи — остатки сырья на складе (из 1С)", "", "", "", ""],
            ["Дата остатков", mod.strftime("%d.%m.%Y %H:%M"), "", "Загружено из «%s». Ед. и «Название в рецептах» можно править — сохранятся." % f["name"], stamp]]},
        {"action": "write", "id": stock_id, "range": "A4:%s%d" % (col, 3 + len(body)), "values": body},
    ]
    bridge(ops, timeout=50)
    real = [r for r in rows if r[0]]
    return {"ok": True, "imported": True, "source": f["name"], "items": len(real), "with_alias": sum(1 for r in real if r[5]),
            "warehouses": whs, "unlinked": len(miss)}
