"""Находит самые свежие Google-таблицы в папке (кроме наших ТТК и склада), читает их и сохраняет
ЗАШИФРОВАННО (паролем сайта) в robot/status/inspect.enc — чтобы не публиковать данные склада в открытом виде."""
import base64, hashlib, json, os, sys
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "robot", "fn"))
import main
known = {sid for _, _, sid in main.LINES} | {main.STOCK_ID}
files = [f for f in main.bridge([{"action": "list"}])[0]["files"] if f["id"] not in known]
files.sort(key=lambda f: f["modified"], reverse=True)
out = {"files": files[:10], "sheets": []}
for f in files[:3]:
    try:
        r = main.bridge([{"action": "read", "id": f["id"]}])[0]
        out["sheets"].append({"name": f["name"], "path": f["path"], "id": f["id"], "rows": r["values"][:400]})
    except Exception as e:
        out["sheets"].append({"name": f["name"], "error": str(e)})
pw = os.environ["RECIPES_PASSWORD"].encode(); salt, iv = os.urandom(16), os.urandom(12)
key = hashlib.pbkdf2_hmac("sha256", pw, salt, 200000, 32)
ct = AESGCM(key).encrypt(iv, json.dumps(out, ensure_ascii=False, default=str).encode(), None)
b = lambda x: base64.b64encode(x).decode()
json.dump({"s": b(salt), "i": b(iv), "c": b(ct), "n": 200000}, open(os.path.join(ROOT, "robot", "status", "inspect.enc"), "w"))
print("ok", [f["name"] for f in files[:10]])
