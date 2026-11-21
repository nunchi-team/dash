"""Обновляет запасную (зашифрованную) копию сайта рецептов из Google Таблиц через мост.
Запускается в GitHub Actions по расписанию. Переменные: BRIDGE_URL, BRIDGE_KEY, RECIPES_PASSWORD."""
import datetime, hashlib, json, os, subprocess, sys

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "robot", "fn"))
import main  # noqa: E402

status_path = os.path.join(ROOT, "robot", "status", "refresh.json")
hash_path = os.path.join(ROOT, "robot", "status", "data.sha256")
ep_path = os.path.join(ROOT, "robot", "endpoint.json")
now = datetime.datetime.now(main.MSK).strftime("%d.%m.%Y %H:%M")

def status(**kw):
    os.makedirs(os.path.dirname(status_path), exist_ok=True)
    json.dump(dict(checked=now, **kw), open(status_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

import stockimport  # noqa: E402
try:
    imp = stockimport.run(main.bridge, main.STOCK_ID, force=os.environ.get("FORCE_STOCK") == "1", ttk_ids=[s for _, _, s in main.LINES])
except Exception as e:
    imp = {"ok": False, "error": str(e)[:300]}
try:
    data = main.build_data()
except Exception as e:
    status(ok=False, error=str(e)[:500], stock_import=imp)
    print("ошибка:", e); sys.exit(0)

robot_url = json.load(open(ep_path)).get("url", "") if os.path.exists(ep_path) else ""
core = {k: v for k, v in data.items() if k not in ("updated", "live")}
core["lines"] = [{k: v for k, v in l.items() if k != "modified"} for l in data["lines"]]
tpl = open(os.path.join(ROOT, "tools", "recipes_template.html"), encoding="utf-8").read()
h = hashlib.sha256((json.dumps(core, sort_keys=True, ensure_ascii=False) + robot_url + tpl).encode()).hexdigest()
old = open(hash_path).read().strip() if os.path.exists(hash_path) else ""
counts = {l["key"]: len(l["recipes"]) for l in data["lines"]}
if h == old:
    status(ok=True, changed=False, stock_import=imp, lines=counts, stock=len(data.get("stock", {})), errors=data["errors"])
    print("без изменений"); sys.exit(0)

data["live"] = False
tmp = os.path.join(ROOT, "robot", "status", "_data.json")
json.dump(data, open(tmp, "w", encoding="utf-8"), ensure_ascii=False)
subprocess.run([sys.executable, os.path.join(ROOT, "tools", "build_recipes_page.py"), tmp, os.path.join(ROOT, "recipes", "index.html")], check=True)
os.remove(tmp)
open(hash_path, "w").write(h)
status(ok=True, changed=True, stock_import=imp, lines=counts, stock=len(data.get("stock", {})), errors=data["errors"], updated=data["updated"])
print("страница обновлена", counts)
