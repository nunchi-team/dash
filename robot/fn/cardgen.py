"""Дописывает карточку нового вкуса в Google-таблицу ТТК линейки (через мост).

Формат и формулы — ровно как в шаблоне таблиц тоников/кордиалов (build_tonics3 / build_cordials).
Порядок действий моста:
  1) вставить строку в сводку и скопировать оформление предыдущей строки сводки;
  2) вставить блок строк перед «Справочником сырья», скопировать оформление последней карточки;
  3) записать значения и формулы карточки и строки сводки;
  4) дописать новое сырьё в справочник.
"""

GROUP_ORDER = ["Сахар", "Сироп", "Кислота", "Хинин", "Ароматизатор", "CO2-экстракт", "Экстракт", "Травы", "Сок",
               "Гидроколлоид", "Соль", "Консервант"]
EXTRA = 3
COLS = 18  # A..R


def _rho(x):
    return "(0.998260062+0.003838154*{0}+0.0000141736838*{0}^2+0.0000000316524217*{0}^3)".format(x)


def layout(values):
    """Находит в листе сводку, карточки и справочник. Номера строк — 1-based."""
    cell = lambda r, c: values[r][c] if r < len(values) and c < len(values[r]) else ""
    hdr = next(k for k in range(len(values)) if cell(k, 1) in ("Тоник", "Кордиал", "Лимонад", "Джин", "Вкус", "Рецепт"))
    k = hdr + 1
    while cell(k, 1):
        k += 1
    sum_last = k  # 1-based номер последней строки сводки = индекс k-1 → k
    cards = []
    for r in range(len(values)):
        if cell(r + 1, 1) == "Статус" and cell(r, 0):
            y = r + 4
            while y < len(values) and cell(y, 1) != "Выход, л (−2% потерь)":
                y += 1
            cards.append(dict(title=r + 1, first=r + 5, yrow=y + 1, qrow=y + 2, name=cell(r, 0)))
    spr_title = next(r for r in range(len(values)) if str(cell(r, 0)).startswith("Справочник сырья")) + 1
    spr_hdr = next(r for r in range(len(values)) if cell(r, 1) == "Сырьё" and cell(r, 2) == "Группа") + 1
    ref_last = spr_hdr
    for r in range(spr_hdr, len(values)):
        if cell(r, 1):
            ref_last = r + 1
    kind = "cordial" if cell(hdr, 1) == "Кордиал" or "Индекс" in str(cell(hdr, 9)) else "tonic"
    return dict(hdr=hdr + 1, sum_last=sum_last, cards=cards, spr_title=spr_title, spr_hdr=spr_hdr,
                ref_last=ref_last, kind=kind, n_sum=sum_last - hdr - 1)


def order_items(items, ref):
    def g(it):
        grp = (ref.get(it["name"]) or {}).get("group") or it.get("group") or ""
        return GROUP_ORDER.index(grp) if grp in GROUP_ORDER else len(GROUP_ORDER)
    return sorted(items, key=g)


def card_rows(rec, P, S, sprav, kind):
    """Строки карточки начиная с P (1-based); S — строка сводки. Возвращает (rows, first, yrow, qrow)."""
    meta, w, first = P + 1, P + 2, P + 4
    items = rec["items"]
    N = 2 + len(items) + EXTRA
    last = first + N - 1
    yrow, qrow = last + 1, last + 2
    blank = lambda: [""] * COLS
    rows = []
    t = blank(); t[0] = rec["name"]; rows.append(t)
    m = blank(); m[1:10] = ["Статус", rec.get("status") or "R&D", "Категория", rec.get("category") or "", "", "Бутылка, мл",
                          rec.get("bottleMl") or (750 if kind == "cordial" else 200), "Подсластитель", "=E%d" % S]
    rows.append(m)
    wr = blank(); wr[1:10] = ["Вода на партию, л", "=D%d" % S, "Brix цель", "=F%d" % S, "", "Brix сиропа", "=G%d" % S, "Brix / pH факт", ""]
    rows.append(wr)
    h = blank(); h[0:10] = ["№", "Ингредиент", "Группа", "Норма на 1 л воды", "Ед. ▼", "г на 1 л воды", "На партию", "Ед. ▼", "Поставщик / артикул", "Комментарий"]
    rows.append(h)
    rng = lambda c: "%s%d:%s%d" % (c, first, c, last)
    num = "(E{w}*(1000+SUM({q}))-100*SUM({r}))".format(w=w, q=rng("Q"), r=rng("R"))
    rhos = _rho("$H$%d" % w)
    allrows = [("Сахар", "SUGAR", "г", "кг", "Считается от Brix цели"),
               ("Сироп ВЛ", "SYRUP", "мл", "л", "Считается от Brix цели и Brix сиропа")]
    allrows += [(it["name"], it.get("value"), it.get("unit") or "г", it.get("outUnit") or "г", it.get("comment") or "") for it in items]
    allrows += [None] * EXTRA
    for k, row in enumerate(allrows, 1):
        r = first + k - 1
        ing, val, unit, ounit, com = row if row else ("", None, "г", "г", "")
        x = blank()
        x[0] = k
        x[1] = ing
        x[2] = '=IF(B{r}="","",IFERROR(VLOOKUP(B{r},{s},2,FALSE),"—"))'.format(r=r, s=sprav)
        if val == "SUGAR":
            x[3] = "=MAX(0,{n}/(100-E{w}))".format(n=num, w=w)
        elif val == "SYRUP":
            x[3] = "=MAX(0,{n}/($H${w}-E{w}))/{rh}".format(n=num, w=w, rh=rhos)
        else:
            x[3] = "" if val is None else val
        x[4] = unit
        x[5] = '=IF(D{r}="","",IF(E{r}="кг",D{r}*1000,IF(E{r}="л",D{r}*1000*M{r},IF(E{r}="мл",D{r}*M{r},D{r}))))'.format(r=r)
        x[6] = ('=IF(F{r}="","",IF(O{r}=0,"не используется",IF(H{r}="кг",F{r}*$C${w}/1000,'
                'IF(H{r}="л",F{r}*$C${w}/1000/M{r},F{r}*$C${w}))))').format(r=r, w=w)
        x[7] = ounit
        x[8] = '=IF(B{r}="","",IFERROR(VLOOKUP(B{r},{s},8,FALSE)&"",""))'.format(r=r, s=sprav)
        x[9] = com
        x[10] = ("=P{r}*$H${w}/100".format(r=r, w=w) if val == "SYRUP"
                 else "=P{r}*IFERROR(VLOOKUP(B{r},{s},3,FALSE),0)/100".format(r=r, s=sprav))
        x[11] = "=P{r}*IFERROR(VLOOKUP(B{r},{s},4,FALSE),0)/100".format(r=r, s=sprav)
        x[12] = ("=" + rhos) if val == "SYRUP" else "=IFERROR(VLOOKUP(B{r},{s},5,FALSE),1)".format(r=r, s=sprav)
        x[13] = '=IF(LEFT(B{r},5)="Хинин",P{r},0)'.format(r=r)
        x[14] = ('=IF(C{r}="Сахар",IF($J${m}="Сахар",1,0),IF(C{r}="Сироп",IF($J${m}="Сироп ВЛ",1,0),1))').format(r=r, m=meta)
        x[15] = '=IF(F{r}="",0,F{r}*O{r})'.format(r=r)
        x[16] = '=IF(OR(C{r}="Сахар",C{r}="Сироп"),0,IF(F{r}="",0,F{r}))'.format(r=r)
        x[17] = "=Q{r}*IFERROR(VLOOKUP(B{r},{s},3,FALSE),0)/100".format(r=r, s=sprav)
        rows.append(x)
    mass = "(1000+SUM(%s))" % rng("P")
    brix = "(SUM(%s)/%s*100)" % (rng("K"), mass)
    rho = _rho(brix)
    vol = "(%s/%s)" % (mass, rho)
    y = blank()
    y[1:10] = ["Выход, л (−2% потерь)", "=$C${w}*{v}/1000*0.98".format(w=w, v=vol), "Бутылок",
               "=ROUNDDOWN(C{y}*1000/$H${m},0)".format(y=yrow, m=meta), "", "Brix проверка", "=" + brix,
               "Кислотность, г/л", "=SUM({l})/{v}*1000".format(l=rng("L"), v=vol)]
    rows.append(y)
    q = blank()
    if kind == "cordial":
        q[1:10] = ["Сырьё на 1 л воды, г", "=SUM(%s)" % rng("P"), "Индекс Brix/кисл.",
                   "=IFERROR({b}/(SUM({l})/{m}*100),0)".format(b=brix, l=rng("L"), m=mass), "",
                   "Сухие в-ва, г/л воды", "=SUM(%s)" % rng("K"), "Brix напитка 1:4", "={b}*{r}/({r}+4)".format(b=brix, r=rho)]
        q[10] = '=IF(E{m}="Ягодные",20,IF(E{m}="Цитрусовые",25,IF(E{m}="Фруктовые",28,33)))'.format(m=meta)
        q[11] = '=IF(E{m}="Ягодные",25,IF(E{m}="Цитрусовые",28,IF(E{m}="Фруктовые",33,40)))'.format(m=meta)
    else:
        q[1:10] = ["Сырьё на 1 л воды, г", "=SUM(%s)" % rng("P"), "Хинин, мг/л",
                   "=SUM({n})*1000000/{v}".format(n=rng("N"), v=vol), "", "Сухие в-ва, г/л воды", "=SUM(%s)" % rng("K"), "", ""]
    rows.append(q)
    return rows, first, yrow, qrow


def summary_row(rec, num, S, first, yrow, qrow, meta, kind):
    if kind == "cordial":
        j = '=TEXT(E{q},"0.0")&" · "&TEXT(J{q},"0.0")&" Bx"'.format(q=qrow)
    else:
        j = '=TEXT(J{y},"0.00")&" г/л · "&TEXT(E{q},"0")&" мг/л"'.format(y=yrow, q=qrow)
    return [num, rec["name"], "=C%d" % meta, rec.get("water") or 1000, rec.get("sweetener") or "Сироп ВЛ",
            rec.get("brixTarget") or (45 if kind == "cordial" else 6), rec.get("syrupBrix") or 67,
            '=IF(E{s}="Сахар",TEXT(F{f}*D{s}/1000,"0.0")&" кг сахара",TEXT(D{f1}*D{s}/1000,"0.0")&" л сиропа")'.format(s=S, f=first, f1=first + 1),
            '=TEXT(C{y},"0")&" л · "&TEXT(E{y},"0")&" бут."'.format(y=yrow), j]


def _col(i):
    return chr(ord("A") + i)


def to_locale(f, notation):
    """Перевод формулы в запись таблицы: ru — разделитель «;», дробная часть «,» (вне кавычек)."""
    if notation != "ru":
        return f
    out, q = [], False
    for i, ch in enumerate(f):
        if ch == '"':
            q = not q; out.append(ch); continue
        if not q and ch == ",":
            out.append(";"); continue
        if not q and ch == "." and i > 0 and f[i - 1].isdigit() and i + 1 < len(f) and f[i + 1].isdigit():
            out.append(","); continue
        out.append(ch)
    return "".join(out)


NOTATION = {"v": "en"}


def write_cells(op, r0, rows):
    """Значения — setValues (без формул), формулы — setFormulas (английская запись, не зависит от языка таблицы)."""
    width = max(len(r) for r in rows)
    vals = [[("" if isinstance(v, str) and v.startswith("=") else v) for v in r] + [""] * (width - len(r)) for r in rows]
    op(action="write", range="A%d:%s%d" % (r0, _col(width - 1), r0 + len(rows) - 1), values=vals)
    for i, r in enumerate(rows):
        j = 0
        while j < len(r):
            if isinstance(r[j], str) and r[j].startswith("="):
                k = j
                while k + 1 < len(r) and isinstance(r[k + 1], str) and r[k + 1].startswith("="):
                    k += 1
                op(action="formulas", range="%s%d:%s%d" % (_col(j), r0 + i, _col(k), r0 + i),
                   values=[[to_locale(f, NOTATION["v"]) for f in r[j:k + 1]]])
                j = k + 1
            else:
                j += 1


def plan_ops(sheet_id, values, rec, ref):
    """Возвращает список операций моста для добавления рецепта rec в лист values."""
    L = layout(values)
    if not L["cards"]:
        raise ValueError("в таблице нет ни одной карточки-образца")
    if any(c["name"] == rec["name"] for c in L["cards"]):
        raise ValueError("вкус с таким названием уже есть")
    kind = L["kind"]
    tpl = L["cards"][-1]
    rec = dict(rec, items=order_items(rec["items"], ref))
    N = 2 + len(rec["items"]) + EXTRA
    ops = []
    op = lambda **kw: ops.append(dict(id=sheet_id, **kw))
    # 1) строка сводки
    S = L["sum_last"] + 1
    op(action="insertRows", after=L["sum_last"], count=1)
    op(action="copyRows", **{"from": "A%d:R%d" % (L["sum_last"], L["sum_last"]), "to": "A%d" % S})
    sh = 1  # сдвиг всего, что ниже сводки
    # 2) блок карточки перед справочником
    P = L["spr_title"] + sh
    count = N + 8
    op(action="insertRows", after=P - 1, count=count)
    t = {k: v + sh for k, v in tpl.items() if isinstance(v, int)}
    op(action="copyRows", **{"from": "A%d:R%d" % (t["title"], t["title"] + 3), "to": "A%d" % P})
    op(action="copyRows", **{"from": "A%d:R%d" % (t["first"], t["first"] + 1), "to": "A%d" % (P + 4)})
    plain = t["first"] + 2 if t["first"] + 2 < t["yrow"] else t["first"]
    for k in range(N - 2):
        op(action="copyRows", **{"from": "A%d:R%d" % (plain, plain), "to": "A%d" % (P + 6 + k)})
    op(action="copyRows", **{"from": "A%d:R%d" % (t["yrow"], t["yrow"] + 1), "to": "A%d" % (P + 4 + N)})
    # 3) значения и формулы
    spr_hdr = L["spr_hdr"] + sh + count
    sprav = "$B$%d:$I$%d" % (spr_hdr + 1, spr_hdr + 1 + max(60, L["ref_last"] - L["spr_hdr"] + 40))
    rows, first, yrow, qrow = card_rows(rec, P, S, sprav, kind)
    write_cells(op, P, rows)
    write_cells(op, S, [summary_row(rec, L["n_sum"] + 1, S, first, yrow, qrow, P + 1, kind)])
    # 4) новое сырьё в справочник
    new_ref = rec.get("newRef") or []
    if new_ref:
        r0 = L["ref_last"] + sh + count + 1
        vals = [["", n["name"], n.get("group", ""), n.get("ss", 0), n.get("acid", 0), n.get("density", 1), "", "",
                 n.get("supplier", ""), n.get("note", "")] for n in new_ref]
        op(action="write", range="A%d:J%d" % (r0, r0 + len(vals) - 1), values=vals)
    return ops
