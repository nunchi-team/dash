"""Читает Google-таблицу «Нунчи тоники — ТТК» (выгрузка .xlsx) и пишет JSON с рецептами для сайта."""
import json, sys, openpyxl

def num(v):
    if v is None or v == "": return None
    if isinstance(v, (int, float)): return float(v)
    try: return float(str(v).replace(",", ".").replace(" ", ""))
    except ValueError: return None

def parse(path):
    wb = openpyxl.load_workbook(path, data_only=True); ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    cell = lambda r, c: rows[r][c] if r < len(rows) and c < len(rows[r]) else None
    # сводка: строка с заголовком «Тоник»
    summ = {}
    i = next(k for k, r in enumerate(rows) if cell(k, 1) == "Тоник")
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
            while cell(j, 1) != "Выход, л (−2% потерь)":
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

if __name__ == "__main__":
    data = parse(sys.argv[1])
    json.dump(data, open(sys.argv[2], "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(len(data["tonics"]), "тоников,", len(data["ref"]), "позиций справочника")
