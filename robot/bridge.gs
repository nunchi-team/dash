/**
 * Нунчи — мост к Google Таблицам для робота (Yandex Cloud).
 * Вставляется один раз, больше не меняется.
 * Умеет: прочитать лист таблицы, записать значения в диапазон, добавить строки,
 * передать сообщение в Telegram (из облака Яндекса Telegram недоступен).
 * Версия 2.
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
