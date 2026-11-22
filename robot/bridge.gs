/**
 * Нунчи — мост к Google Таблицам для робота (Yandex Cloud).
 * Вставляется один раз, больше не меняется.
 * Умеет: прочитать лист таблицы, записать значения в диапазон, добавить строки,
 * передать сообщение в Telegram (из облака Яндекса Telegram недоступен).
 * Версия 3: ещё отдаёт любой файл папки (Excel, PDF) — для загрузки остатков из 1С.
 * Версия 4: раз в час забирает из почты рассылку 1С УНФ «Склад отчет» и кладёт остатки таблицей в папку склада.
 *   Один раз запустить setupMail — включит автопроверку почты.
 * Работает только с файлами из папки «claude рецепты нунчи» и только по секретному ключу.
 */
var ROOT_FOLDER_ID = '1phFTtDIWs5LSYHuYxu1Y2ZG-_nHhZ8b3';

/** Запустить один раз вручную: создаёт секретный ключ и показывает его в журнале. */
function setup() {
  var props = PropertiesService.getScriptProperties();
  var key = props.getProperty('BRIDGE_KEY');
  if (!key) {
    key = Utilities.getUuid().replace(/-/g, '') + Utilities.getUuid().replace(/-/g, '');
    props.setProperty('BRIDGE_KEY', key);
  }
  DriveApp.getFolderById(ROOT_FOLDER_ID).getName(); // запрос доступа к Диску
  UrlFetchApp.fetch('https://api.telegram.org', { muteHttpExceptions: true }); // запрос доступа к интернету
  Logger.log('BRIDGE_KEY = ' + key);
}

function doPost(e) {
  try {
    var req = JSON.parse(e.postData.contents);
    var key = PropertiesService.getScriptProperties().getProperty('BRIDGE_KEY');
    if (!key || req.key !== key) return out({ ok: false, error: 'forbidden' });
    var res = [];
    (req.ops || []).forEach(function (op) { res.push(run(op)); });
    return out({ ok: true, results: res });
  } catch (err) {
    return out({ ok: false, error: String(err) });
  }
}

function doGet() { return out({ ok: true, service: 'nunchi-bridge' }); }

function run(op) {
  if (op.action === 'list') return { files: listFiles() };
  if (op.action === 'telegram') return telegram(op);
  if (op.action === 'listAll') return { files: listAll() };
  if (op.action === 'blob') {
    allowed(op.id);
    var f = DriveApp.getFileById(op.id);
    if (f.getSize() > 15 * 1024 * 1024) throw new Error('file too large');
    var b = f.getBlob();
    return { id: op.id, name: f.getName(), mime: b.getContentType(), modified: f.getLastUpdated().toISOString(), base64: Utilities.base64Encode(b.getBytes()) };
  }
  allowed(op.id);
  var ss = SpreadsheetApp.openById(op.id);
  var sh = op.sheet ? ss.getSheetByName(op.sheet) : ss.getSheets()[0];
  if (op.action === 'read') {
    var vals = sh.getDataRange().getValues().map(function (row) {
      return row.map(function (v) { return v instanceof Date ? Utilities.formatDate(v, 'Europe/Moscow', 'dd.MM.yyyy') : v; });
    });
    return { id: op.id, title: ss.getName(), sheet: sh.getName(), values: vals, modified: DriveApp.getFileById(op.id).getLastUpdated().toISOString() };
  }
  if (op.action === 'write') { sh.getRange(op.range).setValues(op.values); return { id: op.id, written: op.range }; }
  if (op.action === 'formulas') { sh.getRange(op.range).setFormulas(op.values); return { id: op.id, written: op.range }; }
  if (op.action === 'insertRows') { sh.insertRowsAfter(op.after, op.count); return { id: op.id, inserted: op.count }; }
  if (op.action === 'copyRows') {
    sh.getRange(op.from).copyTo(sh.getRange(op.to));
    return { id: op.id, copied: op.to };
  }
  throw new Error('unknown action ' + op.action);
}

/** Проверка, что файл лежит в папке «claude рецепты нунчи» (на любой глубине до 4 уровней). */
function allowed(id) {
  var level = [DriveApp.getFileById(id).getParents()];
  for (var depth = 0; depth < 5 && level.length; depth++) {
    var next = [];
    for (var i = 0; i < level.length; i++) {
      var it = level[i];
      while (it.hasNext()) {
        var f = it.next();
        if (f.getId() === ROOT_FOLDER_ID) return true;
        next.push(f.getParents());
      }
    }
    level = next;
  }
  throw new Error('file outside root folder');
}

/** Пересылка в Telegram: только методы отправки и проверки. */
function telegram(op) {
  var allowedMethods = ['sendMessage', 'getMe', 'getUpdates'];
  if (allowedMethods.indexOf(op.method) < 0) throw new Error('method not allowed');
  var r = UrlFetchApp.fetch('https://api.telegram.org/bot' + op.token + '/' + op.method, {
    method: 'post', contentType: 'application/json', payload: JSON.stringify(op.payload || {}), muteHttpExceptions: true
  });
  return JSON.parse(r.getContentText());
}

/** Все файлы папки (любых типов), без корзины. */
function listAll() {
  var res = [];
  (function walk(folder, path) {
    var fs = folder.getFiles();
    while (fs.hasNext()) {
      var f = fs.next();
      if (f.isTrashed()) continue;
      res.push({ id: f.getId(), name: f.getName(), mime: f.getMimeType(), size: f.getSize(), path: path, modified: f.getLastUpdated().toISOString() });
    }
    var sub = folder.getFolders();
    while (sub.hasNext()) { var s = sub.next(); if (!s.isTrashed()) walk(s, path + '/' + s.getName()); }
  })(DriveApp.getFolderById(ROOT_FOLDER_ID), '');
  return res;
}

function listFiles() {
  var res = [];
  (function walk(folder, path) {
    var fs = folder.getFilesByType(MimeType.GOOGLE_SHEETS);
    while (fs.hasNext()) { var f = fs.next(); res.push({ id: f.getId(), name: f.getName(), path: path, modified: f.getLastUpdated().toISOString() }); }
    var sub = folder.getFolders();
    while (sub.hasNext()) { var s = sub.next(); walk(s, path + '/' + s.getName()); }
  })(DriveApp.getFolderById(ROOT_FOLDER_ID), '');
  return res;
}

function out(o) { return ContentService.createTextOutput(JSON.stringify(o)).setMimeType(ContentService.MimeType.JSON); }


/* ================= Рассылка 1С УНФ → таблица на Диске ================= */
var MAIL_QUERY = 'from:nunchidrink@mail.ru {subject:"Склад отчет" subject:"Склад для робота"} has:attachment newer_than:10d';
var STOCK_FOLDER_ID = '1y2O1RH5ut4Dvs6VpINEjyutiSWveFpGH';  // «Нунчи склад остатки»
var MAIL_SHEET_NAME = 'Остатки 1С — из почты';

/** Запустить один раз вручную: включает проверку почты каждый час и сразу забирает последний отчёт. */
function setupMail() {
  ScriptApp.getProjectTriggers().forEach(function (t) { if (t.getHandlerFunction() === 'importMail') ScriptApp.deleteTrigger(t); });
  ScriptApp.newTrigger('importMail').timeBased().everyHours(1).create();
  PropertiesService.getScriptProperties().deleteProperty('MAIL_LAST');
  Logger.log(importMail());
}

/** Забирает самое свежее письмо с отчётом остатков и обновляет таблицу «Остатки 1С — из почты». */
function importMail() {
  var props = PropertiesService.getScriptProperties();
  var threads = GmailApp.search(MAIL_QUERY, 0, 10), newest = null;
  threads.forEach(function (th) { th.getMessages().forEach(function (m) {
    if (!newest || m.getDate() > newest.getDate()) newest = m; }); });
  if (!newest) return 'писем с отчётом нет';
  if (props.getProperty('MAIL_LAST') === newest.getId()) return 'новых отчётов нет';
  var html = null;
  newest.getAttachments().forEach(function (a) {
    var name = a.getName().toLowerCase();
    var blobs = name.slice(-4) === '.zip' ? Utilities.unzip(a.copyBlob().setContentType('application/zip')) : [a.copyBlob()];
    blobs.forEach(function (b) { if (!html && /\.html?$/i.test(b.getName() || name)) html = b.getDataAsString('UTF-8'); });
  });
  if (!html) return 'в письме нет HTML-отчёта';
  var table = reportToTable(parseHtmlRows(html));
  if (table.length < 3) return 'отчёт пустой';
  writeMailSheet(table, newest.getDate());
  props.setProperty('MAIL_LAST', newest.getId());
  return 'загружено: ' + (table.length - 2) + ' позиций, письмо от ' + newest.getDate();
}

/** HTML-таблица 1С → строки [{cls, cells:[...]}] */
function parseHtmlRows(html) {
  html = html.replace(/^\uFEFF/, '');
  var rows = [], trRe = /<tr[^>]*>([\s\S]*?)<\/tr>/gi, tdRe = /<td([^>]*)>([\s\S]*?)<\/td>/gi, m, c;
  while ((m = trRe.exec(html))) {
    var cells = [], cls = '';
    tdRe.lastIndex = 0;
    while ((c = tdRe.exec(m[1]))) {
      var attrs = c[1], text = c[2].replace(/<br\s*\/?>/gi, ' ').replace(/<[^>]+>/g, '')
        .replace(/&nbsp;|&#160;/gi, ' ').replace(/&quot;/g, '"').replace(/&laquo;/g, '«').replace(/&raquo;/g, '»')
        .replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&').replace(/\s+/g, ' ').trim();
      if (!cells.length) { var k = /class\s*=\s*"?([\w-]+)/i.exec(attrs); cls = k ? k[1] : ''; }
      cells.push(text);
      var span = /colspan\s*=\s*"?(\d+)/i.exec(attrs);
      for (var x = 1; span && x < +span[1]; x++) cells.push('');
    }
    rows.push({ cls: cls, cells: cells });
  }
  return rows;
}

function num1c(s) { s = String(s || '').replace(/[\s\u00a0]/g, '').replace(',', '.'); var v = parseFloat(s); return isNaN(v) ? 0 : v; }

/** Отчёт «по местам хранения» (склады блоками) → таблица как у отчёта 1С по складам колонками. */
function reportToTable(rows) {
  var start = -1;
  for (var i = 0; i < rows.length; i++) if (/^Номенклатура/.test(rows[i].cells[0] || '')) { start = i + 1; break; }
  if (start < 0) throw new Error('не нашёл строку «Номенклатура»');
  // Вариант «склады колонками» (Основной / Тихвин рядом): отдаём как есть, робот сам разберёт.
  var hdr = rows[start - 1].cells;
  if (hdr.filter(function (c) { return c === 'Остаток'; }).length > 1) {
    var tbl = [start > 1 ? rows[start - 2].cells : [], hdr];
    for (var q = start; q < rows.length; q++) {
      var c0 = rows[q].cells[0];
      if (!c0) continue;
      if (/^итого/i.test(c0)) break;
      tbl.push(rows[q].cells.map(function (v, k) { return k === 0 ? v : (v === '' ? '' : num1c(v)); }));
    }
    return tbl;
  }
  var groupCls = rows[start].cls, whs = [], items = {}, order = [], wh = null;
  for (var j = start; j < rows.length; j++) {
    var r = rows[j], name = r.cells[0];
    if (!name) continue;
    if (/^итого/i.test(name)) break;
    if (r.cls === groupCls) { wh = name; if (whs.indexOf(wh) < 0) whs.push(wh); continue; }
    if (!items[name]) { items[name] = {}; order.push(name); }
    var it = items[name][wh] || (items[name][wh] = { q: 0, f: 0 });
    it.q += num1c(r.cells[1]); it.f += num1c(r.cells[3]);
  }
  var top = ['Организация', 'Итого по всем складам', '', ''], sub = ['Номенклатура', 'Остаток', 'Резерв', 'Свободно'];
  whs.forEach(function (w) { top.push(w, '', ''); sub.push('Остаток', 'Резерв', 'Свободно'); });
  var out = [top, sub];
  order.sort(function (a, b) { return a.localeCompare(b, 'ru'); }).forEach(function (n) {
    var q = 0, f = 0, row = [n, 0, '', 0];
    whs.forEach(function (w) { var x = items[n][w]; row.push(x ? x.q : '', '', x ? x.f : ''); if (x) { q += x.q; f += x.f; } });
    row[1] = q; row[3] = f; out.push(row);
  });
  return out;
}

function writeMailSheet(table, date) {
  var props = PropertiesService.getScriptProperties(), id = props.getProperty('MAIL_SHEET_ID'), ss = null;
  if (id) { try { ss = SpreadsheetApp.openById(id); if (DriveApp.getFileById(id).isTrashed()) ss = null; } catch (e) { ss = null; } }
  if (!ss) {
    ss = SpreadsheetApp.create(MAIL_SHEET_NAME);
    DriveApp.getFileById(ss.getId()).moveTo(DriveApp.getFolderById(STOCK_FOLDER_ID));
    props.setProperty('MAIL_SHEET_ID', ss.getId());
  }
  var sh = ss.getSheets()[0], w = Math.max.apply(null, table.map(function (r) { return r.length; }));
  table = table.map(function (r) { return r.slice(); });
  sh.clear();
  sh.getRange(1, 1, table.length, w).setValues(table.map(function (r) { while (r.length < w) r.push(''); return r; }));
  sh.getRange(1, 1, 2, w).setFontWeight('bold');
  sh.setFrozenRows(2);
  ss.rename(MAIL_SHEET_NAME);
}
