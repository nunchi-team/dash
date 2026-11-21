"""E2E-проверка добавления вкуса на тестовых копиях таблиц (GitHub Actions). Пишет итог в robot/status/test_add.json."""
import json, os, sys, traceback
ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "robot", "fn"))
import main
from parsers import parse_ttk

req = json.load(open(os.path.join(ROOT, "robot", "test", "request.json"), encoding="utf-8"))
out = []
for t in req["tests"]:
    r = {"line": t["line"], "name": t["recipe"]["name"]}
    try:
        before = parse_ttk(main.bridge([{"action": "read", "id": t["sheet"]}])[0]["values"])
        r["added"] = main.add_recipe(t["line"], t["recipe"], sheet_id=t["sheet"], stock_id="-")
        vals = main.bridge([{"action": "read", "id": t["sheet"]}])[0]["values"]
        after = parse_ttk(vals)
        r["count"] = [len(before["tonics"]), len(after["tonics"])]
        r["old_same"] = [x["name"] for x in before["tonics"]] == [x["name"] for x in after["tonics"][:len(before["tonics"])]]
        new = [x for x in after["tonics"] if x["name"] == t["recipe"]["name"]]
        r["parsed"] = new[0] if new else None
        # вычисленные таблицей значения новой карточки
        rows = [i for i, v in enumerate(vals) if v and v[0] == t["recipe"]["name"]]
        if rows:
            i = rows[-1]
            r["sheet_rows"] = [v[:10] for v in vals[i:i + 4 + 2 + len(t["recipe"]["items"]) + 3 + 2]]
        sumr = [v[:10] for v in vals if len(v) > 1 and v[1] == t["recipe"]["name"]]
        r["summary_row"] = sumr[0] if sumr else None
        r["errors_in_sheet"] = sorted({str(c) for v in vals for c in v if isinstance(c, str) and c.startswith("#")})
        r["ok"] = bool(new) and r["old_same"] and not r["errors_in_sheet"]
    except Exception as e:
        r["ok"] = False; r["error"] = str(e); r["trace"] = traceback.format_exc()[-1500:]
    out.append(r)
os.makedirs(os.path.join(ROOT, "robot", "status"), exist_ok=True)
json.dump(out, open(os.path.join(ROOT, "robot", "status", "test_add.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
print([(x["name"], x["ok"]) for x in out])
