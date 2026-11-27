/* Мини-генератор PDF для Nunchi: A4, русский текст (шрифт Roboto встраивается), таблицы, перенос по страницам.
   Использование:
     const fonts = await NunchiPDF.loadFonts('/lib/');   // Roboto-Regular.ttf, Roboto-Medium.ttf
     const d = new NunchiPDF(fonts, {footer:'Nunchi'});
     d.text('Заголовок',{size:16,bold:true}); d.table({cols:[{w:1},{w:2,align:'right'}],head:['A','B'],rows:[['x','1']]});
     const blob = await d.finish();                       // Blob application/pdf
*/
(function (root) {
  'use strict';
  const PW0 = 595.28, PH0 = 841.89;

  function parseTTF(buf) {
    const dv = new DataView(buf);
    const n = dv.getUint16(4);
    const T = {};
    for (let i = 0; i < n; i++) {
      const o = 12 + i * 16;
      const tag = String.fromCharCode(dv.getUint8(o), dv.getUint8(o + 1), dv.getUint8(o + 2), dv.getUint8(o + 3));
      T[tag] = { off: dv.getUint32(o + 8), len: dv.getUint32(o + 12) };
    }
    const head = T.head.off, hhea = T.hhea.off;
    const upm = dv.getUint16(head + 18);
    const bbox = [dv.getInt16(head + 36), dv.getInt16(head + 38), dv.getInt16(head + 40), dv.getInt16(head + 42)].map(v => Math.round(v * 1000 / upm));
    const asc = Math.round(dv.getInt16(hhea + 4) * 1000 / upm), desc = Math.round(dv.getInt16(hhea + 6) * 1000 / upm);
    const nHM = dv.getUint16(hhea + 34);
    const hm = T.hmtx.off;
    const adv = gid => dv.getUint16(hm + 4 * Math.min(gid, nHM - 1));
    // cmap
    const cm = T.cmap.off, nt = dv.getUint16(cm + 2);
    let sub = -1;
    for (let i = 0; i < nt; i++) {
      const pid = dv.getUint16(cm + 4 + i * 8), eid = dv.getUint16(cm + 6 + i * 8), off = dv.getUint32(cm + 8 + i * 8);
      if ((pid === 3 && eid === 1) || (pid === 0 && sub < 0)) { sub = cm + off; if (pid === 3) break; }
    }
    if (sub < 0) throw new Error('В шрифте нет таблицы cmap');
    const fmt = dv.getUint16(sub);
    if (fmt !== 4) throw new Error('Формат cmap ' + fmt + ' не поддерживается');
    const segX2 = dv.getUint16(sub + 6), seg = segX2 / 2;
    const endO = sub + 14, startO = endO + segX2 + 2, deltaO = startO + segX2, rangeO = deltaO + segX2;
    function gid(cp) {
      if (cp > 0xffff) return 0;
      for (let s = 0; s < seg; s++) {
        if (cp <= dv.getUint16(endO + s * 2)) {
          const st = dv.getUint16(startO + s * 2);
          if (cp < st) return 0;
          const ro = dv.getUint16(rangeO + s * 2), dl = dv.getInt16(deltaO + s * 2);
          if (ro === 0) return (cp + dl) & 0xffff;
          const g = dv.getUint16(rangeO + s * 2 + ro + (cp - st) * 2);
          return g === 0 ? 0 : (g + dl) & 0xffff;
        }
      }
      return 0;
    }
    const cache = new Map();
    return {
      buf, upm, bbox, asc, desc,
      gid(cp) { let g = cache.get(cp); if (g === undefined) { g = gid(cp); cache.set(cp, g); } return g; },
      adv(g) { return adv(g) * 1000 / upm; },
    };
  }

  const hex4 = n => n.toString(16).padStart(4, '0');
  const f2 = n => (Math.round(n * 100) / 100).toString();
  const utf16hex = cp => {
    if (cp < 0x10000) return hex4(cp);
    cp -= 0x10000; return hex4(0xd800 + (cp >> 10)) + hex4(0xdc00 + (cp & 0x3ff));
  };

  class NunchiPDF {
    constructor(fonts, opt) {
      this.F = fonts; // {regular, bold} = parseTTF results
      this.opt = Object.assign({ margin: 40, footer: '', landscape: false }, opt || {});
      this.PW = this.opt.landscape ? PH0 : PW0; this.PH = this.opt.landscape ? PW0 : PH0;
      this.images = [];
      this.pages = [];
      this.used = { regular: new Map(), bold: new Map() }; // gid -> codepoint
      this._newPage();
    }
    static async loadFonts(base) {
      const get = async n => { const r = await fetch(base + n); if (!r.ok) throw new Error('Не загрузился шрифт ' + n); return r.arrayBuffer(); };
      const [a, b] = await Promise.all([get('Roboto-Regular.ttf'), get('Roboto-Medium.ttf')]);
      return { regular: parseTTF(a), bold: parseTTF(b) };
    }
    _newPage() { this.cur = { ops: [] }; this.pages.push(this.cur); this.y = this.opt.margin; }
    _font(bold) { return bold ? this.F.bold : this.F.regular; }
    width(str, size, bold) {
      const f = this._font(bold); let w = 0;
      for (const ch of str) w += f.adv(f.gid(ch.codePointAt(0)));
      return w * size / 1000;
    }
    wrap(str, maxW, size, bold) {
      const out = [];
      for (const para of String(str == null ? '' : str).split('\n')) {
        let line = '';
        for (const word of para.split(/[ \t]+/).filter(Boolean)) {
          const t = line ? line + ' ' + word : word;
          if (this.width(t, size, bold) <= maxW || !line) {
            if (!line && this.width(word, size, bold) > maxW) { // слишком длинное слово
              let piece = '';
              for (const ch of word) { if (this.width(piece + ch, size, bold) > maxW && piece) { out.push(piece); piece = ''; } piece += ch; }
              line = piece;
            } else line = t;
          } else { out.push(line); line = word; }
        }
        out.push(line);
      }
      return out;
    }
    _draw(str, x, y, size, bold, color) { // y — базовая линия сверху страницы
      const f = this._font(bold), used = this.used[bold ? 'bold' : 'regular'];
      let h = '';
      for (const ch of str) { const cp = ch.codePointAt(0); const g = f.gid(cp); used.set(g, cp); h += hex4(g); }
      if (!h) return;
      const c = color || [0, 0, 0];
      this.cur.ops.push(`BT /${bold ? 'F2' : 'F1'} ${f2(size)} Tf ${c.map(f2).join(' ')} rg 1 0 0 1 ${f2(x)} ${f2(this.PH - y)} Tm <${h}> Tj ET`);
    }
    _rect(x, y, w, h, color) { this.cur.ops.push(`${color.map(f2).join(' ')} rg ${f2(x)} ${f2(this.PH - y - h)} ${f2(w)} ${f2(h)} re f`); }
    _line(x1, y1, x2, y2, color, lw) { this.cur.ops.push(`${(color || [0.8, 0.8, 0.8]).map(f2).join(' ')} RG ${f2(lw || 0.5)} w ${f2(x1)} ${f2(this.PH - y1)} m ${f2(x2)} ${f2(this.PH - y2)} l S`); }
    _room(h) { if (this.y + h > this.PH - this.opt.margin - 14) { this._newPage(); return true; } return false; }
    space(h) { this.y += h; }
    text(str, o) {
      o = Object.assign({ size: 10, bold: false, align: 'left', gap: 3, color: null }, o || {});
      const W = o.w || (this.PW - 2 * this.opt.margin), X0 = o.x != null ? o.x : this.opt.margin, lh = o.size * 1.3;
      for (const ln of this.wrap(str, W, o.size, o.bold)) {
        this._room(lh);
        const w = this.width(ln, o.size, o.bold);
        const x = o.align === 'right' ? X0 + W - w : o.align === 'center' ? X0 + (W - w) / 2 : X0;
        this._draw(ln, x, this.y + o.size, o.size, o.bold, o.color);
        this.y += lh;
      }
      this.y += o.gap;
    }
    // cols: [{w: доля, align:'left'|'right'|'center'}]; head: [строки]; rows: [[ячейки]]; boldRows: индексы; fill: индексы строк с заливкой
    table(t) {
      const size = t.size || 8.5, pad = 3, W = this.PW - 2 * this.opt.margin;
      const tot = t.cols.reduce((s, c) => s + c.w, 0);
      const cw = t.cols.map(c => c.w / tot * W);
      const x0 = this.opt.margin;
      const rowH = (cells, bold) => Math.max(...cells.map((c, i) => this.wrap(c, cw[i] - 2 * pad, size, bold).length)) * size * 1.25 + 2 * pad;
      const drawRow = (cells, bold, fill, isHead) => {
        const h = rowH(cells, bold);
        if (this._room(h)) { if (!isHead && t.head) drawRow(t.head, true, [0.93, 0.93, 0.93], true); }
        if (fill) this._rect(x0, this.y, W, h, fill);
        let x = x0;
        cells.forEach((c, i) => {
          const lines = this.wrap(c, cw[i] - 2 * pad, size, bold);
          lines.forEach((ln, k) => {
            const w = this.width(ln, size, bold), al = t.cols[i].align || 'left';
            const tx = al === 'right' ? x + cw[i] - pad - w : al === 'center' ? x + (cw[i] - w) / 2 : x + pad;
            this._draw(ln, tx, this.y + pad + size + k * size * 1.25 - 1, size, bold);
          });
          x += cw[i];
        });
        this._line(x0, this.y + h, x0 + W, this.y + h);
        this.y += h;
      };
      if (t.head) drawRow(t.head, true, [0.93, 0.93, 0.93], true);
      const br = new Set(t.boldRows || []), fl = new Set(t.fillRows || []);
      t.rows.forEach((r, i) => drawRow(r, br.has(i), fl.has(i) ? [0.96, 0.96, 0.96] : null, false));
      this.y += 6;
    }

    // картинка: img = {rgb:Uint8Array, alpha:Uint8Array, w, h}; x,y — левый верхний угол, w,h — размер в pt
    image(img, x, y, w, h) {
      let i = this.images.indexOf(img); if (i < 0) { this.images.push(img); i = this.images.length - 1; }
      this.cur.ops.push(`q ${f2(w)} 0 0 ${f2(h)} ${f2(x)} ${f2(this.PH - y - h)} cm /Im${i} Do Q`);
    }
    static async imageFromURL(url) {
      const im = new Image(); im.src = url; await im.decode();
      const c = document.createElement('canvas'); c.width = im.naturalWidth; c.height = im.naturalHeight;
      const g = c.getContext('2d'); g.drawImage(im, 0, 0);
      const d = g.getImageData(0, 0, c.width, c.height).data, n = c.width * c.height;
      const rgb = new Uint8Array(n * 3), alpha = new Uint8Array(n);
      for (let i = 0; i < n; i++) { rgb[i * 3] = d[i * 4]; rgb[i * 3 + 1] = d[i * 4 + 1]; rgb[i * 3 + 2] = d[i * 4 + 2]; alpha[i] = d[i * 4 + 3]; }
      return { rgb, alpha, w: c.width, h: c.height };
    }
    _stroke(x, y, w, h) { this.cur.ops.push(`0.2 0.2 0.2 RG 0.6 w ${f2(x)} ${f2(this.PH - y - h)} ${f2(w)} ${f2(h)} re S`); }
    // Таблица с рамками и объединением ячеек.
    // t = {cols:[{w,align,gap}], rows:[строка], boldRows:[...], size}; строка = массив ячеек; ячейка = 'текст' | {t, span, align, bold, nob}
    grid(t) {
      const size = t.size || 8.5, pad = 2.5, W = this.PW - 2 * this.opt.margin, x0 = this.opt.margin;
      const tot = t.cols.reduce((s, c) => s + c.w, 0), cw = t.cols.map(c => c.w / tot * W);
      const br = new Set(t.boldRows || []);
      const norm = row => { let ci = 0; return row.map(c => { c = typeof c === 'string' ? { t: c } : c; const sp = c.span || 1; const o = { t: c.t, span: sp, col: ci, align: c.align, bold: c.bold, nob: c.nob, w: cw.slice(ci, ci + sp).reduce((a, b) => a + b, 0) }; ci += sp; return o; }); };
      t.rows.forEach((row, ri) => {
        const cells = norm(row), bold = br.has(ri);
        const lines = cells.map(c => this.wrap(c.t, c.w - 2 * pad, size, c.bold || bold));
        const h = Math.max(...lines.map(l => l.length)) * size * 1.25 + 2 * pad;
        this._room(h);
        cells.forEach((c, k) => {
          const cx = x0 + cw.slice(0, c.col).reduce((a, b) => a + b, 0);
          if (!c.nob && !t.cols[c.col].gap) this._stroke(cx, this.y, c.w, h);
          lines[k].forEach((ln, j) => {
            const b = c.bold || bold, w = this.width(ln, size, b), al = c.align || t.cols[c.col].align || 'left';
            const tx = al === 'right' ? cx + c.w - pad - w : al === 'center' ? cx + (c.w - w) / 2 : cx + pad;
            this._draw(ln, tx, this.y + pad + size + j * size * 1.25 - 1, size, b);
          });
        });
        this.y += h;
      });
    }

    async finish() {
      const N = this.pages.length;
      this.pages.forEach((p, i) => {
        this.cur = p;
        const s = 'стр. ' + (i + 1) + ' из ' + N, w = this.width(s, 8, false);
        this._draw(s, this.PW - this.opt.margin - w, this.PH - 24, 8, false, [0.5, 0.5, 0.5]);
        if (this.opt.footer) this._draw(this.opt.footer, this.opt.margin, this.PH - 24, 8, false, [0.5, 0.5, 0.5]);
      });
      const enc = new TextEncoder();
      const objs = []; // {head:string, stream:Uint8Array|null}
      const add = (head, stream) => { objs.push({ head, stream: stream || null }); return objs.length; };
      const zip = async u8 => {
        if (typeof CompressionStream === 'undefined') return { d: u8, f: false };
        const cs = new Blob([u8]).stream().pipeThrough(new CompressionStream('deflate'));
        return { d: new Uint8Array(await new Response(cs).arrayBuffer()), f: true };
      };
      // 1 каталог, 2 страницы (заполним позже), затем шрифты
      add('', null); add('', null);
      const fontObj = async (key, name) => {
        const f = this.F[key], used = this.used[key];
        const ff = await zip(new Uint8Array(f.buf));
        const idFile = add(`<< /Length ${ff.d.length} /Length1 ${f.buf.byteLength}${ff.f ? ' /Filter /FlateDecode' : ''} >>`, ff.d);
        const idDesc = add(`<< /Type /FontDescriptor /FontName /${name} /Flags 32 /FontBBox [${f.bbox.join(' ')}] /ItalicAngle 0 /Ascent ${f.asc} /Descent ${f.desc} /CapHeight ${f.asc} /StemV 80 /FontFile2 ${idFile} 0 R >>`);
        const gids = [...used.keys()].sort((a, b) => a - b);
        const W = gids.map(g => `${g} [${Math.round(f.adv(g))}]`).join(' ');
        const idCid = add(`<< /Type /Font /Subtype /CIDFontType2 /BaseFont /${name} /CIDSystemInfo << /Registry (Adobe) /Ordering (Identity) /Supplement 0 >> /FontDescriptor ${idDesc} 0 R /CIDToGIDMap /Identity /DW 600 /W [${W}] >>`);
        let cmap = '/CIDInit /ProcSet findresource begin 12 dict begin begincmap /CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def /CMapName /Adobe-Identity-UCS def /CMapType 2 def 1 begincodespacerange <0000> <FFFF> endcodespacerange\n';
        for (let i = 0; i < gids.length; i += 100) {
          const ch = gids.slice(i, i + 100);
          cmap += ch.length + ' beginbfchar\n' + ch.map(g => `<${hex4(g)}> <${utf16hex(used.get(g))}>`).join('\n') + '\nendbfchar\n';
        }
        cmap += 'endcmap CMapName currentdict /CMap defineresource pop end end';
        const cu = enc.encode(cmap);
        const idTU = add(`<< /Length ${cu.length} >>`, cu);
        return add(`<< /Type /Font /Subtype /Type0 /BaseFont /${name} /Encoding /Identity-H /DescendantFonts [${idCid} 0 R] /ToUnicode ${idTU} 0 R >>`);
      };
      const f1 = await fontObj('regular', 'Roboto-Regular'), f2o = await fontObj('bold', 'Roboto-Medium');
      const imgIds = [];
      for (const im of this.images) {
        const a = await zip(im.alpha), c = await zip(im.rgb);
        const ida = add(`<< /Type /XObject /Subtype /Image /Width ${im.w} /Height ${im.h} /ColorSpace /DeviceGray /BitsPerComponent 8 /Length ${a.d.length}${a.f ? ' /Filter /FlateDecode' : ''} >>`, a.d);
        imgIds.push(add(`<< /Type /XObject /Subtype /Image /Width ${im.w} /Height ${im.h} /ColorSpace /DeviceRGB /BitsPerComponent 8 /SMask ${ida} 0 R /Length ${c.d.length}${c.f ? ' /Filter /FlateDecode' : ''} >>`, c.d));
      }
      const xo = imgIds.length ? ' /XObject << ' + imgIds.map((id, i) => `/Im${i} ${id} 0 R`).join(' ') + ' >>' : '';
      const pageIds = [];
      for (const p of this.pages) {
        const c = await zip(enc.encode(p.ops.join('\n')));
        const idC = add(`<< /Length ${c.d.length}${c.f ? ' /Filter /FlateDecode' : ''} >>`, c.d);
        pageIds.push(add(`<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${this.PW} ${this.PH}] /Resources << /Font << /F1 ${f1} 0 R /F2 ${f2o} 0 R >>${xo} >> /Contents ${idC} 0 R >>`));
      }
      objs[0].head = '<< /Type /Catalog /Pages 2 0 R >>';
      objs[1].head = `<< /Type /Pages /Kids [${pageIds.map(i => i + ' 0 R').join(' ')}] /Count ${pageIds.length} >>`;
      const parts = [], offs = [];
      let pos = 0;
      const push = u8 => { parts.push(u8); pos += u8.length; };
      push(enc.encode('%PDF-1.4\n'));
      objs.forEach((o, i) => {
        offs.push(pos);
        push(enc.encode(`${i + 1} 0 obj\n${o.head}\n`));
        if (o.stream) { push(enc.encode('stream\n')); push(o.stream); push(enc.encode('\nendstream\n')); }
        push(enc.encode('endobj\n'));
      });
      const xr = pos;
      push(enc.encode(`xref\n0 ${objs.length + 1}\n0000000000 65535 f \n` + offs.map(o => String(o).padStart(10, '0') + ' 00000 n \n').join('') +
        `trailer\n<< /Size ${objs.length + 1} /Root 1 0 R >>\nstartxref\n${xr}\n%%EOF`));
      return new Blob(parts, { type: 'application/pdf' });
    }
  }
  root.NunchiPDF = NunchiPDF;
})(window);
