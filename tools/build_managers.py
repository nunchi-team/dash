#!/usr/bin/env python3
"""Сборка страницы менеджеров из данных 1С (УНФ, OData).

Запуск из GitHub Actions каждые 3 часа (workflow «Страница менеджеров»).
Секреты: ODATA_USER, ODATA_PASS, SITE_PASSWORD. Только чтение из 1С.
Результат: зашифрованная страница (по умолчанию index.html) и статус robot/status/managers.json (без названий клиентов).
Если что-то не так, старая страница остаётся как была.
"""
import hashlib
import base64, collections, datetime as dt, json, os, re, sys, time, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ODATA = os.environ.get('ODATA_URL', 'https://1cfresh.com/a/sbm/2291054/odata/standard.odata/')
SINCE = '2023-01-01'
TARGET = os.environ.get('TARGET', 'index.html')
YEAR0 = dt.date(2025, 12, 29)          # первая неделя 2026 года (понедельник)
CONTRACT_WORDS = ('ВКУСВИЛЛ', 'ВКУС ВИЛЛ', 'С-ИМПОРТС', 'С ИМПОРТС', 'СИМПОРТС', 'HOPPERS', 'ХОППЕРС', 'ХОПЕРС')  # контрактное производство
BOSS = {'Аверин', 'Хаушабо'}            # → «Нунчи боссы»
NO_MANAGER = {'Конаков', 'Юрчихин', 'Эльмар', 'Слава'}   # → «Без менеджера»
MON_ABBR = ['янв', 'фев', 'мар', 'апр', 'мая', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек']
MON_PREP = ['январе', 'феврале', 'марте', 'апреле', 'мае', 'июне', 'июле', 'августе', 'сентябре', 'октябре', 'ноябре', 'декабре']
MON_GEN = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря']
ZERO = '00000000-0000-0000-0000-000000000000'


# ---------------- чтение 1С ----------------
def odata_get(path, params, user, pw):
    q = '&'.join(k + '=' + urllib.parse.quote(str(v), safe="(),'$=") for k, v in params.items())
    url = ODATA + urllib.parse.quote(path, safe="/()_'=") + '?$format=json&' + q
    req = urllib.request.Request(url, headers={'Authorization': 'Basic ' + base64.b64encode((user + ':' + pw).encode()).decode(), 'Accept': 'application/json'})
    last = None
    for i in range(4):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.loads(r.read().decode('utf-8-sig'))
        except Exception as e:  # повтор при сбое сети/1С
            last = e; time.sleep(3 * (i + 1))
    raise RuntimeError('1С не ответила: %s' % type(last).__name__ + ' ' + str(last)[:120])


def odata_all(path, params, user, pw, page=1500, maximum=60000):
    out = []
    for skip in range(0, maximum, page):
        p = dict(params); p['$top'] = page; p['$skip'] = skip
        v = odata_get(path, p, user, pw).get('value', [])
        out += v
        if len(v) < page:
            break
    return out


def norm_key(k):
    return (k or ZERO).lower()


API = os.environ.get('API_URL', 'https://api.nunchidrink.ru/nunchi-api/api.php')


def api_export(what, key):
    url = API + '?action=export&what=' + what + '&key=' + urllib.parse.quote(key)
    last = None
    for i in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'nunchi-robot'}), timeout=300) as r:
                return json.loads(r.read().decode('utf-8'))
        except Exception as e:
            last = e; time.sleep(5 * (i + 1))
    raise RuntimeError('хостинг не ответил: %s %s' % (type(last).__name__, str(last)[:150]))


def fetch_orders_api(key):
    j = api_export('orders', key)
    if 'error' in j:
        raise RuntimeError('хостинг: ' + str(j['error']))
    orders = []
    for d, c, m, n in j['orders']:
        try:
            orders.append((dt.date.fromisoformat(d), c, m, n))
        except Exception:
            pass
    return orders, j['clients'], j['employees']


def fetch_orders(user, pw):
    rows = odata_all('Document_РасходнаяНакладная', {
        '$select': 'Ref_Key,Number,Date,Контрагент_Key,Ответственный_Key',
        '$filter': "Posted eq true and DeletionMark eq false and Date ge datetime'%sT00:00:00'" % SINCE,
        '$orderby': 'Ref_Key'}, user, pw)
    clients = {}
    for k in odata_all('Catalog_Контрагенты', {'$select': 'Ref_Key,Description,IsFolder', '$orderby': 'Ref_Key'}, user, pw):
        if not k.get('IsFolder'):
            clients[norm_key(k['Ref_Key'])] = (k.get('Description') or '').strip()
    emps = {}
    for e in odata_all('Catalog_Сотрудники', {'$select': 'Ref_Key,Description', '$orderby': 'Ref_Key'}, user, pw):
        emps[norm_key(e['Ref_Key'])] = (e.get('Description') or '').strip()
    orders = []
    for r in rows:
        try:
            d = dt.date.fromisoformat(str(r['Date'])[:10])
        except Exception:
            continue
        orders.append((d, norm_key(r.get('Контрагент_Key')), norm_key(r.get('Ответственный_Key')), str(r.get('Number') or '')))
    return orders, clients, emps


# ---------------- расчёт ----------------
def manager_name(raw):
    """Имя в 1С «Фамилия Имя [Отчество]» → как в дашборде."""
    raw = (raw or '').strip()
    if not raw:
        return 'Без менеджера'
    parts = raw.split()
    if parts[0] in BOSS or (len(parts) > 1 and parts[1] in BOSS):
        return 'Нунчи боссы'
    if parts[0] in NO_MANAGER:
        return 'Без менеджера'
    return parts[1] + ' ' + parts[0] if len(parts) >= 2 else raw


def label_my(d):
    return '%s %d' % (MON_ABBR[d.month - 1], d.year)


def label_dmy(d):
    return '%d %s %d' % (d.day, MON_ABBR[d.month - 1], d.year)


def compute(orders, clients, emps, today, cord=None):
    """orders: [(date, client_key, manager_key, number)] → словарь для window.__D."""
    skip = {k for k, n in clients.items() if any(w in n.upper() for w in CONTRACT_WORDS)}
    by = collections.defaultdict(list)          # клиент → [(date, manager_key)]
    for d, c, m, num in orders:
        if c == ZERO or c in skip or d > today:
            continue
        by[c].append((d, m))
    for c in by:
        by[c].sort(key=lambda x: x[0])
    dates = {c: [d for d, _ in v] for c, v in by.items()}

    def last_before(c, day):        # последний заказ клиента не позже day
        best = None
        for d in dates[c]:
            if d <= day: best = d
            else: break
        return best

    def count_upto(c, day):
        return sum(1 for d in dates[c] if d <= day)

    def active_on(day, mn=0, mx=60):
        n = 0
        for c in dates:
            L = last_before(c, day)
            if L and mn <= (day - L).days <= mx:
                n += 1
        return n

    def risk_on(day):
        return sum(1 for c in dates if (L := last_before(c, day)) and 31 <= (day - L).days <= 60 and count_upto(c, day) >= 2)

    def points_between(a, b):
        return {c for c in dates if any(a <= d <= b for d in dates[c])}

    docs_between = lambda a, b: sum(1 for c in dates for d in dates[c] if a <= d <= b)

    def lost_between(a, b):         # исполнилось 61 день без заказа внутри [a, b]
        res = []
        for c in dates:
            L = last_before(c, b)
            if L and a <= L + dt.timedelta(days=61) <= b:
                res.append(c)
        return res

    def came_between(a, b):         # (клиент, 'new'|'ret')
        res = []
        for c in dates:
            ds = dates[c]
            idx = [i for i, d in enumerate(ds) if a <= d <= b]
            if not idx:
                continue
            i = idx[0]
            if i == 0:
                res.append((c, 'new'))
            elif (ds[i] - ds[i - 1]).days >= 90:
                res.append((c, 'ret'))
        return res

    # ---- по неделям 2026 ----
    weekly = []
    jan1 = dt.date(today.year, 1, 1)
    ws = jan1 - dt.timedelta(days=jan1.weekday())   # понедельник недели, в которую входит 1 января
    while ws <= today:
        we_full = ws + dt.timedelta(days=6)
        we = min(we_full, today)
        partial = 1 if we < we_full else 0
        ly = dt.timedelta(days=364)
        came = came_between(ws, we)
        weekly.append({
            'week': ws.isoformat(), 'week_end': we.isoformat(),
            'orders': str(docs_between(ws, we)), 'points': str(len(points_between(ws, we))),
            'points_ly': str(len(points_between(ws - ly, we - ly))),
            'new': str(sum(1 for _, t in came if t == 'new')), 'returned': str(sum(1 for _, t in came if t == 'ret')),
            'lost': str(len(lost_between(ws, we))),
            'active': str(active_on(we)), 'active_ly': str(active_on(we - ly)),
            'at_risk': str(risk_on(we)), 'partial': str(partial)})
        ws += dt.timedelta(days=7)

    # ---- по месяцам ----
    months = []
    for m in range(1, today.month + 1):
        a = dt.date(today.year, m, 1)
        nxt = dt.date(today.year + (m == 12), m % 12 + 1, 1)
        b = min(nxt - dt.timedelta(days=1), today)
        part = 1 if b < nxt - dt.timedelta(days=1) else 0
        a0 = dt.date(today.year - 1, m, 1)
        b0 = dt.date(today.year - 1, m, min(b.day, (dt.date(today.year - 1 + (m == 12), m % 12 + 1, 1) - dt.timedelta(days=1)).day))
        months.append({'month': str(m), 'pts26': str(len(points_between(a, b))), 'pts25': str(len(points_between(a0, b0))), 'partial': str(part)})

    # ---- менеджер клиента: последний, указанный в накладных ----
    def mgr(c):
        for d, m in reversed(by[c]):
            if m != ZERO and emps.get(m):
                return manager_name(emps[m])
        return 'Без менеджера'

    def cord_of(c):
        if cord is None: return ''
        cr = cord.get(c)
        return 'Нет' if not cr else ('Да' if cr[1] >= (today - dt.timedelta(days=365)).isoformat() else 'Раньше')

    # ---- точки года ----
    cur_first = dt.date(today.year, today.month, 1)
    prev_last = cur_first - dt.timedelta(days=1)
    prev_first = dt.date(prev_last.year, prev_last.month, 1)
    pts = []
    for c in dates:
        yd = [d for d in dates[c] if d.year == today.year]
        if not yd:
            continue
        L = dates[c][-1]
        months_all = len({(d.year, d.month) for d in dates[c]})
        if L >= cur_first:
            status, prio, po = 'Заказал в %s' % MON_PREP[today.month - 1], 'Заказывает', 4
        elif L >= prev_first:
            status, prio, po = 'Был в %s, в %s нет' % (MON_PREP[prev_last.month - 1], MON_PREP[today.month - 1]), 'Срочно', 0
        else:
            nm = L.month % 12
            status = 'Не заказывает с %s' % MON_GEN[nm]
            if months_all >= 3: prio, po = 'Высокий', 1
            elif months_all == 2: prio, po = 'Средний', 2
            else: prio, po = 'Низкий', 3
        cc = ''
        if cord is not None:   # Да — брала за последние 12 месяцев, Раньше — брала давно, Нет — ни разу
            cr = cord.get(c)
            cc = 'Нет' if not cr else ('Да' if cr[1] >= (today - dt.timedelta(days=365)).isoformat() else 'Раньше')
        pts.append({'year': str(today.year), 'client': clients.get(c, c), 'manager': mgr(c), 'status': status, 'priority': prio,
                    'prio_order': str(po), 'last_label': label_my(L), 'months_all': str(months_all), 'cordial': cc})
    pts.sort(key=lambda r: (int(r['prio_order']), -int(r['months_all']), r['client']))

    # ---- списки на кнопках «Клиентская база» (по последней неделе) ----
    last = weekly[-1]
    ws_l, we_l = dt.date.fromisoformat(last['week']), dt.date.fromisoformat(last['week_end'])
    lists = []

    def item(kind, c, note=None):
        L = dates[c][-1]
        return {'list': kind, 'client': clients.get(c, c), 'manager': mgr(c), 'cordial': cord_of(c), 'last_order': label_dmy(L),
                'days': str((today - L).days), 'orders': str(len(dates[c])), 'note': note, 'key': kind + '|' + clients.get(c, c)}
    for c in dates:
        L = last_before(c, today)
        if L is None: continue
        age = (today - L).days
        if age <= 60: lists.append(item('active', c))
        if 31 <= age <= 60 and len(dates[c]) >= 2: lists.append(item('risk', c))
    for c in lost_between(ws_l, we_l):
        lists.append(item('lost', c))
    for c, t in came_between(ws_l, we_l):
        lists.append(item('came', c, 'новая точка' if t == 'new' else 'вернулась после перерыва'))

    return {'year': str(today.year), 'weekly': weekly, 'months': months, 'points_years': pts, 'base_lists': lists,
            '_skipped_contract_clients': len(skip & set(dates))}


# ---------------- сборка страницы ----------------
def decrypt_stamp(password):
    """Печать и подпись лежат в репозитории зашифрованными (файл tools/stamp.enc)."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    p = json.load(open(os.path.join(HERE, 'stamp.enc'), encoding='utf-8'))
    key = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=base64.b64decode(p['s']), iterations=p['n']).derive(password.encode())
    return json.loads(AESGCM(key).decrypt(base64.b64decode(p['i']), base64.b64decode(p['c']), None).decode())


def encrypt_page(html, password, iters=300000):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    salt, iv = hashlib.sha256(b'nunchi-team-site-salt-v1').digest()[:16], os.urandom(12)  # соль постоянная: телефон хранит готовый ключ и не считает его заново
    key = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=iters).derive(password.encode())
    ct = AESGCM(key).encrypt(iv, html.encode('utf-8'), None)
    b = lambda x: base64.b64encode(x).decode()
    payload = json.dumps({'s': b(salt), 'i': b(iv), 'c': b(ct), 'n': iters})
    shell = open(os.path.join(HERE, 'shell.html'), encoding='utf-8').read()
    return shell.replace('__PAYLOAD__', payload)


def build_html(data, stamp):
    tpl = open(os.path.join(HERE, 'managers_template.html'), encoding='utf-8').read()
    sec = open(os.path.join(HERE, 'docs_section.html'), encoding='utf-8').read()
    sec = sec.replace('__SIGN__', stamp.get('sign', '')).replace('__STAMP__', stamp.get('stamp', ''))
    marker = '<section class="card kick" id="kick">'
    assert tpl.count(marker) == 1, 'в шаблоне нет блока «Пинок недели»'
    yr = int(data.get('year') or dt.date.today().year)
    def _yr(t):   # подписи с годом в шаблоне — по году данных: в 2027 году сам станет «2027» и сравнение с 2026
        return '\n'.join(l if (l.startswith('!function') or 'window.__D = ' in l) else l.replace('2026', '\x01').replace('2025', str(yr - 1)).replace('\x01', str(yr)) for l in t.split('\n'))
    tpl = _yr(tpl)
    tpl = tpl.replace(marker, sec + '\n  ' + marker)
    tpl, nk = re.subn(r'<section class="card kick" id="kick">.*?</section>\s*', '', tpl, count=1, flags=re.S)  # «Пинок недели» убран
    assert nk == 1, 'не нашёл блок «Пинок недели» для удаления'
    pub = {k: v for k, v in data.items() if not k.startswith('_')}
    j = json.dumps(pub, ensure_ascii=False, separators=(',', ':')).replace('</', '<\\/')
    tpl, n = re.subn(r'window\.__D = \{.*?\};\n', lambda m: 'window.__D = ' + j + ';\n', tpl, count=1, flags=re.S)
    assert n == 1, 'в шаблоне нет данных window.__D'
    return tpl


def write_status(**kw):
    os.makedirs(os.path.join(ROOT, 'robot', 'status'), exist_ok=True)
    kw['at'] = dt.datetime.now(dt.timezone(dt.timedelta(hours=3))).strftime('%d.%m.%Y %H:%M')
    json.dump(kw, open(os.path.join(ROOT, 'robot', 'status', 'managers.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)


def main():
    user, pw, site = (os.environ.get(k, '').strip() for k in ('ODATA_USER', 'ADMIN_KEY', 'SITE_PASSWORD'))
    miss = [k for k, v in (('ADMIN_KEY', pw),) if not v]
    if miss:
        write_status(ok=False, step='нет секретов: ' + ', '.join(miss)); print('нет секретов', miss); return
    try:
        orders, clients, emps = fetch_orders_api(pw)
        today = dt.datetime.now(dt.timezone(dt.timedelta(hours=3))).date()
        if len(orders) < 500:
            raise RuntimeError('из 1С пришло слишком мало накладных (%d): страницу не трогаю' % len(orders))
        cord, cinfo = None, {}
        try:
            cj = api_export('cordial', pw)
            if 'error' in cj:
                raise RuntimeError(str(cj['error']))
            cord = cj.get('cordial') or {}
            cinfo = {'cordial_items': cj.get('item_count'), 'cordial_lines': cj.get('lines'), 'cordial_clients': len(cord), 'cordial_names': (cj.get('items') or [])[:40]}
            if not cj.get('item_count') or not cj.get('lines'):
                cord = None   # правило не сработало — лучше ничего не показывать, чем показать неправду
        except Exception as e:
            cinfo = {'cordial_error': str(e)[:200]}
        data = compute(orders, clients, emps, today, cord)
        try:  # пароль сайта: если его меняли на самом сайте, он лежит на хостинге
            site_new = (api_export('sitepw', pw) or {}).get('password')
        except Exception:
            site_new = None
        if site_new:
            site = site_new
        if not site:
            raise RuntimeError('нет пароля сайта (секрет SITE_PASSWORD или пароль, заданный на сайте)')
        html = build_html(data, {})
        path = os.path.join(ROOT, TARGET)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        hp = os.path.join(ROOT, 'robot', 'status', 'page.sha256')
        hh = hashlib.sha256((site + '\n' + html).encode('utf-8')).hexdigest()
        same = os.path.exists(path) and os.path.exists(hp) and open(hp).read().strip() == hh
        if same:
            out = open(path, encoding='utf-8').read()  # данные не менялись — файл не трогаем, у телефонов остаётся кэш
        else:
            out = encrypt_page(html, site)
            open(path, 'w', encoding='utf-8').write(out)
            os.makedirs(os.path.dirname(hp), exist_ok=True); open(hp, 'w').write(hh)
        w = data['weekly'][-1]
        cnt = collections.Counter(r['priority'] for r in data['points_years'])
        write_status(ok=True, step='готово', target=TARGET, orders_read=len(orders), clients_in_1c=len(clients),
                     contract_clients_excluded=data['_skipped_contract_clients'], last_week=w, months=data['months'],
                     points_year=len(data['points_years']), priorities=dict(cnt),
                     lists=dict(collections.Counter(r['list'] for r in data['base_lists'])), **cinfo)
        print('готово', TARGET, len(out) // 1024, 'КБ')
    except Exception as e:
        msg = str(e)
        for s in (pw, user, site):
            if s: msg = msg.replace(s, '***')
        write_status(ok=False, step='ошибка', error=msg[:400]); print('ОШИБКА', msg[:400])


if __name__ == '__main__':
    main()
