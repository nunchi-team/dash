#!/usr/bin/env python3
"""Разведка 1С: какие поля есть у накладных, счетов, организаций, банковских счетов, номенклатуры.
Названия полей кладёт в robot/status/metadata.json (там нет данных).
Примеры записей (с реальными данными!) кладёт ЗАШИФРОВАННО в robot/status/probe.enc (пароль сайта).
Запускается из workflow, если в репозитории есть файл robot/test/probe.flag."""
import base64, json, os, re, sys, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_managers as B

user, pw, site = (os.environ.get(k, '').strip() for k in ('ODATA_USER', 'ADMIN_KEY', 'SITE_PASSWORD'))
ROOT = B.ROOT
out_dir = os.path.join(ROOT, 'robot', 'status'); os.makedirs(out_dir, exist_ok=True)
samples = {}
try:
    samples = B.api_export('probe', pw)
except Exception as e:
    samples = {'ОШИБКА': str(e)[:300]}
# названия полей (без данных) — открыто; сами записи — только зашифрованно
def keys_of(v):
    if isinstance(v, list) and v and isinstance(v[0], dict):
        return {k: (type(x).__name__ if not isinstance(x, list) else {'таблица': keys_of(x)}) for k, x in v[0].items()}
    if isinstance(v, dict):
        return {k: type(x).__name__ for k, x in v.items()}
    return str(v)[:200]
meta = {'errors': [], 'fields': {k: keys_of(v) for k, v in samples.items()}}
json.dump(meta, open(os.path.join(out_dir, 'metadata.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
B_ = B.encrypt_page.__globals__
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
salt, iv = os.urandom(16), os.urandom(12)
key = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=300000).derive(site.encode())
ct = AESGCM(key).encrypt(iv, json.dumps(samples, ensure_ascii=False).encode('utf-8'), None)
b = lambda x: base64.b64encode(x).decode()
json.dump({'s': b(salt), 'i': b(iv), 'c': b(ct), 'n': 300000}, open(os.path.join(out_dir, 'probe.enc'), 'w'))
print('probe готов')
