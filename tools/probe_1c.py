#!/usr/bin/env python3
"""Разведка 1С: какие поля есть у накладных, счетов, организаций, банковских счетов, номенклатуры.
Названия полей кладёт в robot/status/metadata.json (там нет данных).
Примеры записей (с реальными данными!) кладёт ЗАШИФРОВАННО в robot/status/probe.enc (пароль сайта).
Запускается из workflow, если в репозитории есть файл robot/test/probe.flag."""
import base64, json, os, re, sys, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_managers as B

user, pw, site = (os.environ.get(k, '').strip() for k in ('ODATA_USER', 'ODATA_PASS', 'SITE_PASSWORD'))
ROOT = B.ROOT
out_dir = os.path.join(ROOT, 'robot', 'status'); os.makedirs(out_dir, exist_ok=True)
WANT = ['Document_РасходнаяНакладная', 'Document_СчетНаОплату', 'Catalog_Организации', 'Catalog_БанковскиеСчета', 'Catalog_Номенклатура',
        'Catalog_Контрагенты', 'Catalog_ДоговорыКонтрагентов', 'Catalog_КлассификаторЕдиницИзмерения', 'Catalog_ЕдиницыИзмерения', 'InformationRegister_КонтактнаяИнформация']
meta = {'errors': []}
try:
    req = urllib.request.Request(B.ODATA + '$metadata', headers={'Authorization': 'Basic ' + base64.b64encode((user + ':' + pw).encode()).decode()})
    xml = urllib.request.urlopen(req, timeout=300).read().decode('utf-8', 'replace')
    meta['xml_size'] = len(xml)
    types = {}
    for m in re.finditer(r'<(EntityType|ComplexType) Name="([^"]+)"[^>]*>(.*?)</\1>', xml, re.S):
        props = re.findall(r'<Property Name="([^"]+)" Type="([^"]+)"', m.group(3))
        types[m.group(2)] = props
    for n in WANT:
        if n in types:
            meta[n] = [p + ':' + t.replace('Edm.', '').replace('StandardODATA.', '') for p, t in types[n]]
        # табличные части: <имя>_<Часть>_RowType
    meta['row_types'] = {k: [p for p, _ in v] for k, v in types.items()
                         if k.startswith(('Document_РасходнаяНакладная_', 'Document_СчетНаОплату_')) and k.endswith('_RowType')}
    meta['names_like'] = sorted(k for k in types if any(w in k for w in ('Банк', 'КонтактнаяИнформация', 'ЕдиницыИзмерения', 'Печать')))[:60]
except Exception as e:
    meta['errors'].append('metadata: ' + str(e)[:200])
json.dump(meta, open(os.path.join(out_dir, 'metadata.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)

samples = {}
def grab(name, path, params):
    try:
        samples[name] = B.odata_get(path, params, user, pw).get('value')
    except Exception as e:
        samples[name] = 'ОШИБКА: ' + str(e)[:200]
grab('realization', 'Document_РасходнаяНакладная', {'$filter': 'Posted eq true and DeletionMark eq false', '$orderby': 'Date desc', '$top': 2})
grab('invoice', 'Document_СчетНаОплату', {'$orderby': 'Date desc', '$top': 2})
grab('orgs', 'Catalog_Организации', {'$top': 5})
grab('bank_accounts', 'Catalog_БанковскиеСчета', {'$top': 8})
grab('nomenclature', 'Catalog_Номенклатура', {'$filter': 'IsFolder eq false', '$top': 2})
grab('contact_info_org', 'InformationRegister_КонтактнаяИнформация', {'$top': 6})
try:
    r = samples['realization'][0]
    for key, path in (('counterparty', "Catalog_Контрагенты(guid'%s')" % r.get('Контрагент_Key')), ('contract', "Catalog_ДоговорыКонтрагентов(guid'%s')" % r.get('Договор_Key'))):
        try: samples[key] = B.odata_get(path, {}, user, pw)
        except Exception as e: samples[key] = 'ОШИБКА: ' + str(e)[:200]
except Exception:
    pass
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
