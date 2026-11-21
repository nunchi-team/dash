"""Собирает зашифрованную страницу recipes/index.html из JSON с тониками.
Использование: RECIPES_PASSWORD=... python3 tools/build_recipes_page.py data.json recipes/index.html"""
import base64, datetime, json, os, sys, hashlib
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

src, out = sys.argv[1], sys.argv[2]
pw = os.environ["RECIPES_PASSWORD"].encode()
data = json.load(open(src, encoding="utf-8"))
data.setdefault("updated", datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=3))).strftime("%d.%m.%Y %H:%M"))
salt, iv, n = os.urandom(16), os.urandom(12), 600000
key = hashlib.pbkdf2_hmac("sha256", pw, salt, n, 32)
ct = AESGCM(key).encrypt(iv, json.dumps(data, ensure_ascii=False).encode(), None)
b = lambda x: base64.b64encode(x).decode()
payload = json.dumps({"s": b(salt), "i": b(iv), "c": b(ct), "n": n})
tpl = open(os.path.join(os.path.dirname(__file__), "recipes_template.html"), encoding="utf-8").read()
ep = os.path.join(os.path.dirname(__file__), "..", "robot", "endpoint.json")
robot = json.load(open(ep)).get("url", "") if os.path.exists(ep) else ""
open(out, "w", encoding="utf-8").write(tpl.replace("__PAYLOAD__", payload).replace("__ROBOT_URL__", robot))
print("ok", out, len(ct), "bytes encrypted")
