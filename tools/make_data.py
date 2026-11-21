"""Собирает данные сайта из выгрузок Google-таблиц.
Использование: python3 tools/make_data.py тоники.xlsx кордиалы.xlsx склад.xlsx data.json"""
import json, os, sys
sys.path.insert(0, os.path.dirname(__file__))
from tonics_from_xlsx import parse as parse_ttk
from stock_from_xlsx import parse as parse_stock

tonics, cordials, stock, out = sys.argv[1:5]
lines = []
for key, title, path in (("tonics", "Тоники", tonics), ("cordials", "Кордиалы", cordials)):
    d = parse_ttk(path)
    lines.append(dict(key=key, title=title, recipes=d["tonics"], ref=d["ref"]))
data = dict(lines=lines, **parse_stock(stock))
json.dump(data, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
for l in lines: print(l["title"], len(l["recipes"]), "рецептов")
print("склад", len(data["stock"]), "позиций, дата", data["stockDate"], "ТЕСТ" if data["stockTest"] else "")
