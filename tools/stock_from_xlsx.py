"""Читает Google-таблицу «Нунчи склад — остатки» (.xlsx) и добавляет остатки в JSON сайта.
Использование: python3 tools/stock_from_xlsx.py склад.xlsx data.json  (дописывает stock в data.json)"""
import json, sys, openpyxl

def num(v):
    if v is None or v == "": return None
    if isinstance(v, (int, float)): return float(v)
    try: return float(str(v).replace(",", ".").replace(" ", ""))
    except ValueError: return None

def parse(path):
    ws = openpyxl.load_workbook(path, data_only=True).active
    rows = list(ws.iter_rows(values_only=True))
    cell = lambda r, c: rows[r][c] if r < len(rows) and c < len(rows[r]) else None
    hdr = next(k for k in range(len(rows)) if str(cell(k, 0) or "").strip() == "Сырьё")
    date = cell(1, 1)
    if hasattr(date, "strftime"): date = date.strftime("%d.%m.%Y")
    test = "ТЕСТ" in str(cell(1, 2) or "").upper()
    stock = {}
    for k in range(hdr + 1, len(rows)):
        n = cell(k, 0)
        q = num(cell(k, 1))
        if not n or q is None: continue
        stock[str(n).strip()] = dict(qty=q, unit=str(cell(k, 2) or "кг").strip(), code=cell(k, 3) or "", note=cell(k, 4) or "")
    return dict(stock=stock, stockDate=str(date or ""), stockTest=test)

if __name__ == "__main__":
    s = parse(sys.argv[1])
    data = json.load(open(sys.argv[2], encoding="utf-8"))
    data.update(s)
    json.dump(data, open(sys.argv[2], "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(len(s["stock"]), "позиций склада, дата", s["stockDate"], "ТЕСТ" if s["stockTest"] else "")
