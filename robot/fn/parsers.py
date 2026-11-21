"""Разбор Google-таблиц Нунчи (ТТК линеек и склад). Вход — список строк (как getValues)."""

def num(v):
    if v is None or v == "": return None
    if isinstance(v, (int, float)): return float(v)
    try: return float(str(v).replace(",", ".").replace(" ", ""))
    except ValueError: return None

def parse_ttk(rows):
    cell = lambda r, c: rows[r][c] if r < len(rows) and c < len(rows[r]) else None
    # сводка: строка с заголовком «Тоник» / «Кордиал» / …
    summ = {}
    i = next(k for k, r in enumerate(rows) if cell(k, 1) in ("Тоник", "Кордиал", "Лимонад", "Джин", "Вкус", "Рецепт"))
    k = i + 1
    while cell(k, 1):
        summ[cell(k, 1)] = dict(water=num(cell(k, 3)) or 0, sweetener=cell(k, 4) or "Сироп ВЛ",
                                brixTarget=num(cell(k, 5)), syrupBrix=num(cell(k, 6)) or 66)
        k += 1
    # справочник
    sp0 = next(k for k, r in enumerate(rows) if cell(k, 1) == "Сырьё" and cell(k, 2) == "Группа")
    ref = {}
    k = sp0 + 1
    while k < len(rows):
        n = cell(k, 1)
        if n: ref[str(n).strip()] = dict(group=cell(k, 2) or "", ss=num(cell(k, 3)) or 0, acid=num(cell(k, 4)) or 0,
                                         density=num(cell(k, 5)) or 1, supplier=cell(k, 8) or "", note=cell(k, 9) or "")
        k += 1
    # карточки
    tonics = []
    for k in range(len(rows)):
        if cell(k + 1, 1) == "Статус" and cell(k, 0) and cell(k, 0) in summ:
            name = cell(k, 0)
            t = dict(name=name, status=cell(k + 1, 2) or "", category=cell(k + 1, 4) or "",
                     bottleMl=num(cell(k + 1, 7)) or 200, **summ[name], items=[])
            j = k + 4  # первая строка состава
            while j < len(rows) and cell(j, 1) != "Выход, л (−2% потерь)" and not (cell(j + 1, 1) == "Статус"):
                ing = cell(j, 1)
                if ing:
                    grp = (ref.get(str(ing).strip(), {}).get("group")) or cell(j, 2) or ""
                    it = dict(name=str(ing).strip(), group=grp, comment=cell(j, 9) or "")
                    if grp in ("Сахар", "Сироп"):
                        it["auto"] = True
                    else:
                        it.update(value=num(cell(j, 3)), unit=cell(j, 4) or "г", outUnit=cell(j, 7) or "г")
                    t["items"].append(it)
                j += 1
            tonics.append(t)
    return dict(tonics=tonics, ref=ref)

def parse_stock(rows):
    cell = lambda r, c: rows[r][c] if r < len(rows) and c < len(rows[r]) else None
    hdr = next(k for k in range(len(rows)) if str(cell(k, 0) or "").strip().startswith("Сырьё"))
    date = cell(1, 1)
    if hasattr(date, "strftime"): date = date.strftime("%d.%m.%Y")
    test = "ТЕСТ" in str(cell(1, 2) or "").upper()
    hrow = rows[hdr]
    has_alias = len(hrow) > 5 and str(hrow[5]).strip().startswith("Название в рецептах")
    whcols = [(j, str(hrow[j]).replace("Склад:", "").strip()) for j in range(6, len(hrow)) if str(hrow[j]).startswith("Склад")]
    has_props = len(hrow) > 9 and str(hrow[6]).strip() == "Группа"
    stock, aliases = {}, {}
    for k in range(hdr + 1, len(rows)):
        n = cell(k, 0)
        q = num(cell(k, 1))
        if not n or q is None: continue
        n = str(n).strip()
        e = dict(qty=q, unit=str(cell(k, 2) or "кг").strip(), code=cell(k, 3) or "", note=cell(k, 4) or "")
        if whcols:
            e["wh"] = {w: num(cell(k, j)) or 0 for j, w in whcols}
        if has_props and str(cell(k, 6) or "").strip():
            e.update(group=str(cell(k, 6)).strip(), ss=num(cell(k, 7)) or 0, acid=num(cell(k, 8)) or 0, density=num(cell(k, 9)) or 1)
        stock[n] = e
        if has_alias:
            for a in str(cell(k, 5) or "").split(";"):
                a = a.strip()
                if a: aliases[a] = n
    for a, n in aliases.items():  # название из рецепта → та же позиция склада
        if a not in stock:
            stock[a] = dict(stock[n], src=n)
    return dict(stock=stock, stockDate=str(date or ""), stockTest=test,
                stockSource=str(cell(1, 3) or "") if has_alias else "", warehouses=[w for _, w in whcols])
