/* ═══════════════════════════════════════════
   سهم — منطق التطبيق المصغّر (v2.3)
   🎮 يدعم المعاينة خارج تيليجرام عبر ?mock=1
   ═══════════════════════════════════════════ */

const tg = window.Telegram?.WebApp;
const QS = new URLSearchParams(location.search);
const IS_MOCK = QS.has('mock');
const IS_TG = !!(tg && tg.initData && tg.initData.length);
const API = QS.get('api')
  || (location.hostname.endsWith('.pages.dev') ? 'https://sahem-game.onrender.com' : location.origin);

let TOKEN = null;
let USER = null;
let PRICES = [];
let HOLDINGS = {};        // رمز -> كمية مملوكة
let PORTFOLIO = null;
let priceTimer = null;

/* ─── تيليجرام ─── */
try { tg?.ready(); tg?.expand(); } catch {}
try { tg?.setHeaderColor('#0a0e13'); tg?.setBackgroundColor('#0a0e13'); } catch {}
function haptic(kind = 'light') {
  try {
    const h = tg?.HapticFeedback; if (!h) return;
    kind === 'success' || kind === 'error' ? h.notificationOccurred(kind) : h.impactOccurred(kind);
  } catch {}
}

/* ─── أدوات ─── */
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const fmt = (n, d = 2) => (n === null || n === undefined || isNaN(n)) ? '—'
  : Number(n).toLocaleString('en-US', { maximumFractionDigits: d, minimumFractionDigits: d });
const fmt0 = (n) => fmt(n, 0);
function fmtQty(n) {  // الكميات الصغيرة تحتاج منازل أكثر (U24)
  if (n === null || n === undefined || isNaN(n)) return '—';
  const a = Math.abs(Number(n));
  return fmt(n, a > 0 && a < 1 ? 4 : a < 100 ? 2 : 0);
}
const pct = (p) => (p > 0 ? '+' : '') + fmt(p) + '%';
let toastTimer = null;
function toast(msg, ms = 3200) {
  const t = $('toast'); t.textContent = msg; t.classList.add('show');
  clearTimeout(toastTimer); toastTimer = setTimeout(() => t.classList.remove('show'), ms);
}

/* حالة اتصال مبسّطة */
function conn(ok) {
  const d = $('conn-dot'); if (!d) return;
  d.classList.toggle('off', !ok);
  d.title = ok ? 'متصل' : 'انقطع الاتصال';
}

/* حالة خطأ قابلة لإعادة المحاولة */
function showError(box, msg, retry) {
  box.innerHTML = `<div class="empty error-state"><div class="em">⚠️</div><p>${esc(msg)}</p>
    ${retry ? '<button class="btn btn-ghost retry-btn">🔄 إعادة المحاولة</button>' : ''}</div>`;
  const b = box.querySelector('.retry-btn');
  if (b) b.onclick = retry;
}

/* زر الرجوع في تيليجرام */
function showBack(handler) {
  try {
    const bb = tg?.BackButton; if (!bb) return;
    bb.show(); bb.onClick(handler);
  } catch {}
}
function hideBack() { try { tg?.BackButton?.hide(); } catch {} }

const MARKET_INFO = {
  SA: { flag: '🇸🇦', label: 'تداول' },
  US: { flag: '🇺🇸', label: 'أمريكي' },
  CRYPTO: { flag: '🌐', label: 'كريبتو' },
};
function shortSymbol(sym) {
  const base = sym.split('-')[0].split('.')[0];
  return base.length <= 4 ? base : base.slice(0, 4);
}
function avatarHTML(p) {
  const m = MARKET_INFO[p.market] || { flag: '💱' };
  const isUs = p.market === 'US';
  return `<div class="sym-avatar">${isUs ? esc(shortSymbol(p.symbol)) : m.flag}</div>`;
}

/* ─── API ─── */
async function api(path, opts = {}) {
  const headers = { 'Content-Type': 'application/json' };
  if (TOKEN) headers['Authorization'] = 'Bearer ' + TOKEN;
  let res;
  try {
    res = await fetch(API + path, { ...opts, headers });
  } catch (e) {
    conn(false);
    const err = new Error('تعذّر الاتصال بالخادم'); err.offline = true; throw err;
  }
  conn(true);
  if (res.status === 401) {
    TOKEN = null;
    showGate('انتهت الجلسة — أعد فتح التطبيق من البوت');
    const err = new Error('انتهت الجلسة'); err.status = 401; throw err;
  }
  let data = null;
  const txt = await res.text();
  try { data = txt ? JSON.parse(txt) : null; } catch {}
  if (!res.ok) {
    const msg = (data && (data.detail || data.error)) || ('تعذّر إكمال الطلب (' + res.status + ')');
    const err = new Error(String(msg)); err.status = res.status; err.detail = String(msg); throw err;
  }
  return data;
}

function showGate(msg) {
  $('gate-debug').textContent = msg ? '— ' + msg : '';
  $('gate').classList.remove('hidden');
}

/* ─── المصادقة ─── */
async function auth() {
  if (IS_MOCK) {
    TOKEN = 'mock:1';
    USER = { id: 1, username: 'لاعب تجريبي', coins_balance: 72000, level: 3, xp: 1140 };
    return true;
  }
  if (!IS_TG) {
    reportGate('no-initData');
    return false;
  }
  try {
    const d = await fetch(API + '/api/auth', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ initData: tg.initData }),
    }).then(r => { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); });
    TOKEN = d.token;
    USER = d.user;
    return true;
  } catch (e) {
    reportGate('auth-fail: ' + (e && e.message ? e.message : e));
    return false;
  }
}

/* ════════════ اسم اللاعب ════════════ */
/* اسمي أنا — احتياط من تيليجرام فوراً حتى لو صفّي في الخادم لم يُحدث اسمه بعد */
function myName() {
  const u = tg?.initDataUnsafe?.user;
  return (USER?.username || u?.first_name || '').trim() || 'لاعب';
}

/* اسم صف لوحة: أزيّل اسمي الخاص مباشرة من تيليجرام إن كان الصف بلا اسم مخزّن */
function rowName(r, fallback) {
  if (r.user_id != null && USER?.id != null && r.user_id === USER.id) return myName();
  return (r.username || '').trim() || fallback || 'لاعب';
}

/* إبلاغ الخادم لمشكلة تشخيص البوابة — فقط عند الأخطاء الحقيقية (U45) */
function reportGate(reason) {
  try {
    fetch(API + '/api/appdiag', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        reason,
        hasTg: !!tg,
        initDataLen: (tg?.initData || '').length,
        unsafeUser: tg?.initDataUnsafe?.user?.id || null,
        platform: tg?.platform || null,
        url: location.href.slice(0, 200),
        ua: navigator.userAgent.slice(0, 150),
      }),
    }).catch(() => {});
  } catch {}
}

/* ─── الهياكل العظمية ─── */
function skeletons(box, n = 5) {
  box.innerHTML = Array(n).fill('<div class="skel"></div>').join('');
}

/* ════════════ السوق ════════════ */
let currentFilter = 'all';
let currentSearch = '';

$('market-chips').addEventListener('click', (e) => {
  const b = e.target.closest('.chip.px'); if (!b) return;
  document.querySelectorAll('.chip.px').forEach(c => c.classList.remove('active'));
  b.classList.add('active');
  currentFilter = b.dataset.mkt;
  renderPrices();
});
$('search').addEventListener('input', (e) => {
  currentSearch = e.target.value.trim().toLowerCase();
  renderPrices();
});

async function loadPrices(silent = true) {
  try {
    if (!silent) skeletons($('prices-list'), 6);
    PRICES = await api('/api/prices');
    // آخر تحديث للأسعار (U11)
    const stamps = PRICES.map(p => p.updated_at).filter(Boolean).sort();
    if (stamps.length) {
      const d = new Date(stamps[stamps.length - 1]);
      if ($('mkt-updated')) $('mkt-updated').textContent = 'آخر تحديث: ' +
        d.toLocaleTimeString('ar-SA', { hour: '2-digit', minute: '2-digit' });
    }
    renderPrices();
  } catch (e) {
    if (!silent) showError($('prices-list'), e?.detail || 'تعذّر تحميل الأسعار', () => loadPrices(false));
  }
}

function renderPrices() {
  const q = currentSearch;
  const list = PRICES.filter(p =>
    (currentFilter === 'all' || p.market === currentFilter) &&
    (!q || (p.name || '').toLowerCase().includes(q) || p.symbol.toLowerCase().includes(q))
  );
  const box = $('prices-list');
  if (!list.length) {
    box.innerHTML = `<div class="empty"><div class="em">🔍</div><p>لا توجد نتائج مطابقة</p>
      <button class="btn btn-ghost retry-btn" id="clear-search">اعرض الكل</button></div>`;
    const c = box.querySelector('#clear-search');
    if (c) c.onclick = () => { currentSearch = ''; $('search').value = ''; renderPrices(); };
    return;
  }
  box.innerHTML = list.map(p => {
    const ch = p.change_pct ?? 0;
    const cls = ch > 0 ? 'up' : ch < 0 ? 'down' : '';
    const held = (HOLDINGS[p.symbol] || 0) > 0.000001;
    return `<div class="card price-row" data-sym="${esc(p.symbol)}">
      ${avatarHTML(p)}
      <div class="sym-mid">
        <div class="sym-name">${esc(p.name)}</div>
        <div class="sym-meta">${esc(shortSymbol(p.symbol))} • ${(MARKET_INFO[p.market] || {}).label || ''}
          ${held ? `<span class="sym-hold">تملك ${fmtQty(HOLDINGS[p.symbol])}</span>` : ''}</div>
      </div>
      <div class="sym-right">
        ${p.price !== null ? `<div class="sym-price">${fmt(p.price)}</div>
        <div class="sym-change ${cls}">${pct(ch)}</div>` : `<div class="sym-price">—</div>`}
      </div>
    </div>`;
  }).join('');
}

$('prices-list').addEventListener('click', (e) => {
  const row = e.target.closest('.price-row'); if (!row) return;
  const p = PRICES.find(x => x.symbol === row.dataset.sym);
  if (p && p.price !== null) openTradeSheet(p);
});

/* ════════════ ورقة التداول ════════════ */
const SHEET = { sym: null, side: 'buy', qty: 0 };

function openTradeSheet(p) {
  SHEET.sym = p;
  SHEET.side = 'buy';
  SHEET.qty = 0;
  renderSheet();
  $('sheet-backdrop').classList.remove('hidden');
  haptic('light');
  showBack(closeSheet);
}
function closeSheet() {
  $('sheet-backdrop').classList.add('hidden');
  hideBack();
}
$('sheet-backdrop').addEventListener('click', (e) => { if (e.target.id === 'sheet-backdrop') closeSheet(); });

function affordability(p) {
  const maxBuy = PORTFOLIO ? PORTFOLIO.balance / (p.price * 1.001) : 0;
  return { maxBuy, held: HOLDINGS[p.symbol] || 0 };
}

function renderSheet() {
  const p = SHEET.sym;
  const { held } = affordability(p);
  const info = MARKET_INFO[p.market] || {};
  $('sheet-trade').innerHTML = `
    <div class="sheet-handle"></div>
    <button id="sh-close" class="sh-close" aria-label="إغلاق">✕</button>
    <div class="sh-head">
      ${avatarHTML(p)}
      <div><div class="sh-name">${esc(p.name)}</div><div class="sh-sym">${esc(p.symbol)} • ${info.label || ''}</div></div>
      <div class="sh-price"><div class="sh-price-1">${fmt(p.price)}</div><div class="sh-price-2 ${p.change_pct > 0 ? 'up' : p.change_pct < 0 ? 'down' : ''}">${pct(p.change_pct)}</div></div>
    </div>
    <div class="sh-info">
      <div><span>💰 رصيدك النقدي</span><b>${PORTFOLIO ? fmt0(PORTFOLIO.balance) + ' ◈' : '—'}</b></div>
      <div><span>📦 مملوك لديك</span><b>${fmtQty(held)} وحدة</b></div>
    </div>
    <div class="sh-side">
      <button id="side-buy" class="${SHEET.side === 'buy' ? 'sel-buy' : ''}">🟢 شراء</button>
      <button id="side-sell" class="${SHEET.side === 'sell' ? 'sel-sell' : ''}">🔴 بيع</button>
    </div>
    <div class="sh-qty"><input id="sh-qty-in" type="number" min="0" inputmode="decimal" placeholder="0" value="${SHEET.qty || ''}"></div>
    <div class="qty-presets" id="sh-presets">
      <button data-q="1">1</button><button data-q="10">10</button><button data-q="50">50</button>
      <button data-q="100">100</button><button data-q="500">500</button>
      <button data-q="A">${SHEET.side === 'buy' ? 'كل الرصيد' : 'كل المملوك'}</button>
    </div>
    <div class="sh-err" id="sh-err"></div>
    <div class="sh-cost" id="sh-cost"></div>
    <button id="sh-confirm" class="btn btn-block btn-lg sh-confirm ${SHEET.side === 'buy' ? 'btn-buy' : 'btn-sell'}">
      ${SHEET.side === 'buy' ? '🟢 تأكيد الشراء' : '🔴 تأكيد البيع'}
    </button>`;
  $('sheet-trade').querySelectorAll('.qty-presets button').forEach(b => b.addEventListener('click', () => {
    SHEET.qty = b.dataset.q === 'A'
      ? (SHEET.side === 'buy' ? affordability(p).maxBuy : held)
      : Number(b.dataset.q);
    // تحديث الحقل فقط دون إعادة بناء الورقة (يُبقي لوحة المفاتيح) — U23
    $('sh-qty-in').value = SHEET.qty ? Math.floor(SHEET.qty * 10000) / 10000 : '';
    updateCost();
  }));
  $('sh-qty-in').addEventListener('input', (e) => { SHEET.qty = parseFloat(e.target.value) || 0; updateCost(); });
  updateCost();
  $('sh-close').onclick = closeSheet;
  $('side-buy').onclick = () => { SHEET.side = 'buy'; SHEET.qty = 0; renderSheet(); };
  $('side-sell').onclick = () => { SHEET.side = 'sell'; SHEET.qty = 0; renderSheet(); };
  $('sh-confirm').onclick = confirmSheet;
}

function updateCost() {
  const p = SHEET.sym, q = SHEET.qty || 0;
  const cost = p.price * q;
  const fee = cost * 0.001;
  $('sh-cost').innerHTML = q > 0
    ? `الإجمالي ≈ <b>${fmt0(cost + (SHEET.side === 'buy' ? fee : 0))} ◈</b> (عمولة 0.1%)`
    : '';
}

async function confirmSheet() {
  if (!SHEET.qty || SHEET.qty <= 0) { $('sh-err').textContent = 'أدخل كمية صحيحة'; return; }
  const btn = $('sh-confirm');
  const label = SHEET.side === 'buy' ? '🟢 تأكيد الشراء' : '🔴 تأكيد البيع';
  btn.disabled = true; btn.style.opacity = .6; btn.textContent = '⏳ جاري التنفيذ...';
  try {
    const r = await api('/api/trade', { method: 'POST', body: JSON.stringify({ symbol: SHEET.sym.symbol, side: SHEET.side, quantity: SHEET.qty }) });
    haptic('success');
    toast(SHEET.side === 'buy' ? `✅ اشتريت ${fmtQty(SHEET.qty)} بسعر ${fmt(r.price)}` : `✅ بعت ${fmtQty(SHEET.qty)} بسعر ${fmt(r.price)}`);
    closeSheet();
    await loadPortfolio(true);
    renderPrices();
  } catch (e) {
    haptic('error');
    if (e?.status !== 401) $('sh-err').textContent = e?.detail || 'تعذّر تنفيذ الصفقة';
    btn.disabled = false; btn.style.opacity = 1; btn.textContent = label;
  }
}

/* ════════════ التوقعات ════════════ */
const PRED_W = { up: 2.2, down: 3.3, flat: 4.0 };
async function loadPredict() {
  try {
    const prices = await api('/api/prices');
    PRICES = prices;
    const mine = await api('/api/predictions').catch(() => []);
    const history = await api('/api/predictions/history').catch(() => []);
    const pendingSyms = new Set(mine.map(p => p.symbol));
    const byMarket = {};
    prices.filter(p => p.price !== null).forEach(p => (byMarket[p.market] ||= []).push(p));
    const box = $('predict-list');
    const html = [];
    for (const mk of ['SA', 'US', 'CRYPTO']) {
      if (!byMarket[mk]) continue;
      html.push(`<h3 class="sec-title">${MARKET_INFO[mk].flag} ${MARKET_INFO[mk].label}</h3>`);
      for (const p of byMarket[mk]) {
        if (pendingSyms.has(p.symbol)) continue; // لا تكرر السهم الذي وُضع عليه توقعة
        html.push(`<div class="card predict-card" data-sym="${esc(p.symbol)}">
          <div class="pred-top">${avatarHTML(p)}
            <div class="sym-mid"><div class="sym-name">${esc(p.name)}</div><div class="sym-meta mono">${fmt(p.price)}</div></div>
          </div>
          <div class="pred-btns">
            <button class="pred-btn up" data-d="up">▲ صعود<small>+${PRED_W.up} نقطة</small></button>
            <button class="pred-btn flat" data-d="flat">— ثبات<small>+${PRED_W.flat} نقطة</small></button>
            <button class="pred-btn down" data-d="down">▼ هبوط<small>+${PRED_W.down} نقطة</small></button>
          </div>
        </div>`);
      }
    }
    box.innerHTML = html.join('') || `<div class="empty"><div class="em">🎯</div><p>لا أسعار متاحة بعد</p></div>`;
    box.onclick = (e) => {
      const b = e.target.closest('.pred-btn'); if (!b) return;
      const card = b.closest('.predict-card');
      const sym = card?.dataset.sym;
      if (sym) makePrediction(sym, b.dataset.d);
    };

    // توقعاتي القائمة
    const dirAr = { up: '▲ صعود', down: '▼ هبوط', flat: '— ثبات' };
    $('my-predictions').innerHTML = mine.length ? mine.map(p => {
      return `<div class="card pred-mine">
        <span>${dirAr[p.direction] || esc(p.direction)} <b>${esc(p.symbol)}</b></span>
        <span class="count-badge" data-r="${esc(p.resolves_at)}">…</span>
      </div>`;
    }).join('') : `<div class="empty"><div class="em">🎯</div><p>لا توقعات قائمة — ضع أول توقع!</p></div>`;

    // سجل التوقعات (U1)
    $('my-history').innerHTML = history.length ? history.map(h => {
      const win = h.result === 'win';
      const cls = win ? 'up' : 'down';
      return `<div class="card pred-mine">
        <span>${win ? '✅' : '❌'} ${esc(h.symbol)} — ${dirAr[h.direction] || esc(h.direction)}</span>
        <span class="${cls}">${win ? '+' + fmt(h.points, 0) + ' نقطة' : 'خسارة'}</span>
      </div>`;
    }).join('') : `<div class="empty"><div class="em">📜</div><p>لا نتائج بعد</p></div>`;

    countdownTick();
  } catch (e) {
    showError($('predict-list'), e?.detail || 'تعذّر تحميل التوقعات', loadPredict);
  }
}

async function makePrediction(sym, direction) {
  try {
    await api('/api/predict', { method: 'POST', body: JSON.stringify({ symbol: sym, direction }) });
    haptic('success'); toast('✅ سُجّلت توقعتك! النتيجة بعد إغلاق السوق'); await loadPredict();
  } catch (e) { if (e?.status !== 401) toast(e?.detail || 'تعذّر تسجيل التوقع'); }
}

function countdownTick() {
  document.querySelectorAll('.count-badge[data-r]').forEach(el => {
    const t = new Date(el.dataset.r).getTime();
    const left = t - Date.now();
    if (left <= 0) { el.textContent = '⏳ بانتظار التسوية'; return; }
    const h = Math.floor(left / 3.6e6), m = Math.floor((left % 3.6e6) / 6e4);
    el.textContent = h >= 1 ? `متبقي ${h} س ${m} د` : `متبقي ${m} د`;
  });
}
setInterval(countdownTick, 30000);

/* ════════════ المحفظة ════════════ */
async function loadPortfolio(silent = false) {
  let pf;
  try {
    pf = await api('/api/portfolio');
  } catch (e) {
    if (!silent) showError($('pf-positions'), e?.detail || 'تعذّر تحميل المحفظة', () => loadPortfolio(false));
    return;
  }
  PORTFOLIO = pf;
  HOLDINGS = {};
  pf.positions.forEach(p => { HOLDINGS[p.symbol] = p.quantity; });
  updateBalance(pf.balance);

  const invested = pf.positions.reduce((s, p) => s + (p.market_value || 0), 0);
  const net = pf.balance + invested;
  $('pf-net').textContent = fmt0(net);
  const basis = 100000;
  const pl = net - basis;
  $('pf-settled').innerHTML = pl === 0 ? 'بدأت للتو 🚀' :
    `<span class="${pl > 0 ? 'up' : 'down'}">${pct(pl / basis * 100)} عن رأس المال (${pl > 0 ? '+' : ''}${fmt0(pl)})</span>`;
  $('pf-cash').textContent = fmt0(pf.balance) + ' ◈';
  $('pf-invested').textContent = fmt0(invested) + ' ◈';
  $('pf-level').textContent = pf.level;
  const xpIn = Math.round((pf.xp % 500) / 500 * 100);
  $('pf-xp-hint').textContent = `${Math.floor(pf.xp)} XP — ${500 - Math.floor(pf.xp % 500)} للرقم التالي`;
  $('pf-xp-bar').style.width = xpIn + '%';

  // مكافأة الحضور اليومية + سلسلة التوقعات (الخطة 3.1)
  const dc = $('daily-card');
  if (dc) {
    const streak = pf.daily_streak || 0;
    const next = fmt0(pf.daily_next_coins || 0);
    const chains = `<span>🔥 حضور <b>${streak}</b> يوم • ✅ إصابات <b>${pf.pred_streak || 0}</b></span>`;
    if (pf.daily_claimed_today) {
      dc.innerHTML = `${chains}<span>تم ✓ — عد غداً <b class="mono">+${next} ◈</b></span>`;
    } else {
      dc.innerHTML = `${chains}<button id="daily-btn" class="btn btn-primary btn-sm">🎁 استلم +${next} ◈</button>`;
      $('daily-btn').onclick = claimDaily;
    }
  }

  // الأوسمة (الخطة 3.4) — المُنجَز مضيء والقيد الانتظار معتم لتحفيز التقدم
  const bc = $('badges-card');
  if (bc && Array.isArray(pf.badges)) {
    const onCount = pf.badges.filter(b => b.earned).length;
    bc.classList.remove('hidden');
    bc.innerHTML = `<div class="badges-title">🏅 وسومك <b>${onCount}/${pf.badges.length}</b></div>
      <div class="badges-row">${pf.badges.map(b =>
        `<span class="badge ${b.earned ? 'on' : ''}" title="${esc(b.desc)}">${b.emoji} ${esc(b.name)}</span>`
      ).join('')}</div>`;
  }

  const box = $('pf-positions');
  box.innerHTML = pf.positions.length ? pf.positions.map(p => {
    const cls = p.pnl_pct > 0 ? 'up' : p.pnl_pct < 0 ? 'down' : '';
    const fake = { symbol: p.symbol, name: p.name, price: p.current_price, market: p.market, change_pct: 0 };
    return `<div class="card price-row" data-sym="${esc(p.symbol)}" data-pos="1">
      ${avatarHTML(fake)}
      <div class="sym-mid">
        <div class="sym-name">${esc(p.name)}${p.price_stale ? ' <span class="sym-hold">سعر غير محدّث</span>' : ''}</div>
        <div class="sym-meta">${fmtQty(p.quantity)} وحدة • متوسط ${fmt(p.avg_cost)} • الآن ${fmt(p.current_price)}</div>
      </div>
      <div class="sym-right">
        <div class="sym-price">${fmt0(p.market_value)} ◈</div>
        <div class="sym-change ${cls}">${pct(p.pnl_pct)}</div>
      </div>
    </div>`;
  }).join('') : `<div class="empty"><div class="em">💼</div><p>محفظتك فارغة — اشترِ أول سهم من تبويب السوق!</p></div>`;
}

async function claimDaily() {
  const b = $('daily-btn');
  if (b) b.disabled = true;
  try {
    const r = await api('/api/daily', { method: 'POST' });
    haptic('success');
    toast(`🎁 +${fmt0(r.coins)} عملة • سلسلة ${r.streak} يوم`);
    await loadPortfolio(true);
  } catch (e) {
    if (b) b.disabled = false;
    if (e?.status !== 401) toast(e?.detail || 'تعذّر استلام المكافأة');
  }
}

$('pf-positions').addEventListener('click', (e) => {
  const row = e.target.closest('.price-row[data-pos]'); if (!row) return;
  const p = PRICES.find(x => x.symbol === row.dataset.sym);
  if (p) openTradeSheet(p);
});

function updateBalance(v) {
  $('balance').textContent = fmt0(v);
  if (USER && PORTFOLIO) $('level-chip').textContent = 'مستوى ' + Math.floor(PORTFOLIO.level || 1);
}

/* ════════════ الصدارة ════════════ */
async function loadLeaderboard() {
  let rows;
  try {
    rows = await api('/api/leaderboard');
  } catch (e) {
    showError($('lb-list'), e?.detail || 'تعذّر تحميل الصدارة', loadLeaderboard);
    return;
  }
  const podium = $('lb-podium'), list = $('lb-list');
  if (!rows.length) {
    podium.innerHTML = '';
    list.innerHTML = `<div class="empty"><div class="em">🏆</div><p>لوحة الصدارة فاضية — كن أول اللاعبين!</p></div>`;
    return;
  }
  const top = rows.slice(0, 3);
  const medals = ['🥇', '🥈', '🥉'];
  const val = (r) => `${fmt(r.score ?? r.weekly_value ?? 0, 1)} نقطة`;
  const crown = (r) => r.champion ? ' 👑' : '';
  const mine = (r) => r.user_id === USER?.id ? ' <span class="you-badge">أنت</span>' : '';
  const meta = (r) => `${r.rounds} جولة • ${r.pred_wins} توقع صحيح`;
  if (top.length === 3) {
    podium.innerHTML = top.map((r, i) => `<div class="pod p${i + 1}">
      <div class="pod-avatar">${medals[i]}</div>
      <div class="pod-name">${esc(rowName(r, 'لاعب ' + (i + 1)))}${crown(r)}${mine(r)}</div>
      <div class="pod-val">${val(r)}</div>
    </div>`).join('');
    list.innerHTML = rows.slice(3).map((r, i) => `<div class="card lb-row${r.user_id === USER?.id ? ' me' : ''}">
      <div class="lb-rank">${i + 4}</div>
      <div class="sym-mid"><div class="sym-name">${esc(rowName(r))}${crown(r)}${mine(r)}</div>
      <div class="sym-meta">${meta(r)}</div></div>
      <div class="sym-price mono" style="color:var(--gold)">${val(r)}</div>
    </div>`).join('');
  } else {
    podium.innerHTML = '';
    list.innerHTML = rows.map((r, i) => `<div class="card lb-row${r.user_id === USER?.id ? ' me' : ''}">
      <div class="lb-rank lb-medal">${medals[i] || (i + 1)}</div>
      <div class="sym-mid"><div class="sym-name">${esc(rowName(r))}${crown(r)}${mine(r)}</div>
      <div class="sym-meta">${meta(r)}</div></div>
      <div class="sym-price mono" style="color:var(--gold)">${val(r)}</div>
    </div>`).join('');
  }
}

/* ════════════ الأركيد ════════════ */
const AR = { timer: null, chart: null, series: null, volume: null, data: [], round: null, lastStep: -1, preset: 0.25, duelOn: false, prevClose: null, avgCost: 0, fails: 0, pvPrev: null, bestDay: null, worstDay: null };
$('arcade-start').addEventListener('click', () => startArcade(false));
$('arcade-quick')?.addEventListener('click', () => startArcade(true));
$('arcade-finish').addEventListener('click', finishArcade);
$('btn-buy').addEventListener('click', () => arTrade('buy'));
$('btn-sell').addEventListener('click', () => arTrade('sell'));
$('arcade-presets').addEventListener('click', (e) => {
  const b = e.target.closest('button'); if (!b) return;
  AR.preset = parseFloat(b.dataset.q);
  document.querySelectorAll('#arcade-presets button').forEach(x => x.classList.remove('sel'));
  b.classList.add('sel');
});

async function startArcade(quick = false) {
  const btn = $(quick ? 'arcade-quick' : 'arcade-start');
  btn.disabled = true;
  try {
    const rnd = await api('/api/arcade/start', { method: 'POST', body: JSON.stringify({ mode: quick ? 'quick' : 'full' }) });
    enterArcadeGame(rnd);
  } catch (e) {
    if (e?.status !== 401) toast(e?.detail || 'تعذّر بدء الجولة');
  } finally { btn.disabled = false; }
}

function enterArcadeGame(rnd, pre = null) {
  AR.round = rnd; AR.data = []; AR.lastStep = -1;
  AR.prevClose = null; AR.avgCost = 0; AR.fails = 0;   // L30
  AR.pvPrev = null; AR.bestDay = null; AR.worstDay = null;
  AR.duelOn = rnd.kind === 'duel';
  $('arcade-intro').classList.add('hidden');
  $('duel-intro').classList.add('hidden');
  $('arcade-result').classList.add('hidden');
  $('arcade-game').classList.remove('hidden');
  $('arcade-symbol').textContent = rnd.name;
  $('arcade-log').innerHTML = '';
  $('arcade-avg').textContent = '—';
  $('arcade-progress-bar').style.width = '0%';
  $('arcade-net').classList.add('hidden');
  initChart();
  haptic('success');
  showBack(finishArcade);

  if (pre) {
    // استكمال جولة معلّقة: زرع التاريخ المعروض ثم العد من اللحظة الحالية
    AR.lastStep = pre.step;
    AR.avgCost = pre.avg_cost || 0;
    const hist = pre.history || [];
    if (AR.series && hist.length) {
      AR.series.setData(hist.map(c => ({ time: c.ts, open: c.open, high: c.high, low: c.low, close: c.close })));
      if (AR.volume) AR.volume.setData(hist.map(c => ({ time: c.ts, value: c.volume, color: c.close >= c.open ? '#22c55e55' : '#f43f5e55' })));
      AR.prevClose = hist[hist.length - 1].close;
      const last = hist[hist.length - 1];
      const pv = pre.cash + pre.holdings * last.close;
      const ret = (pv - AR.round.capital) / AR.round.capital * 100;
      $('arcade-date').textContent = `📅 ${last.ts}`;
      $('arcade-dayno').textContent = `اليوم ${pre.step + 1}`;
      $('arcade-progress-bar').style.width = ((pre.step + 1) / Math.max(hist.length, 1) * 100) + '%';
      $('arcade-value').textContent = fmt0(pv);
      $('arcade-return').innerHTML = `<span class="${ret > 0 ? 'up' : ret < 0 ? 'down' : ''}">${pct(ret)}</span>`;
      $('arcade-cash').textContent = fmt0(pre.cash);
      $('arcade-qty').textContent = fmtQty(pre.holdings);
      $('arcade-avg').textContent = pre.holdings > 0 ? fmt(AR.avgCost) : '—';
      $('arcade-price').textContent = fmt(last.close);
      AR.pvPrev = pv;
    }
  }

  AR.timer = setInterval(pollArcadeStep, Math.max(700, rnd.step_seconds * 500));
  pollArcadeStep();
}

let chartResizeWired = false;  // L31: مستمع واحد فقط
function initChart() {
  if (typeof LightweightCharts === 'undefined') {
    $('arcade-chart').innerHTML = '<div class="empty"><div class="em">📈</div><p>تعذّر تحميل الرسم البياني</p></div>';
    return;
  }
  if (AR.chart) { AR.chart.remove(); AR.chart = null; }
  const el = $('arcade-chart');
  el.innerHTML = '';
  AR.chart = LightweightCharts.createChart(el, {
    width: el.clientWidth, height: 230,
    layout: { background: { color: '#131a23' }, textColor: '#8fa2b8', fontFamily: 'Cairo' },
    grid: { vertLines: { color: '#1b2430', visible: true }, horzLines: { color: '#1b2430', visible: true } },
    rightPriceScale: { borderColor: '#243044' },
    timeScale: { borderColor: '#243044' },
    handleScroll: { mouseWheel: true, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: false },
    handleScale: { mouseWheel: false, pinch: true },
    localization: { locale: 'ar' },
  });
  AR.series = AR.chart.addCandlestickSeries({
    upColor: '#22c55e', downColor: '#f43f5e', borderVisible: false,
    wickUpColor: '#22c55e', wickDownColor: '#f43f5e',
  });
  AR.volume = AR.chart.addHistogramSeries({ priceScaleId: '', topColor: '#38bdf855', bottomColor: '#38bdf818' });
  AR.volume.priceScale().applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
  if (!chartResizeWired) {
    chartResizeWired = true;
    window.addEventListener('resize', () => { if (AR.chart) AR.chart.applyOptions({ width: el.clientWidth }); });
  }
}

async function pollArcadeStep() {
  if (!AR.round) return;
  try {
    const s = await api(`/api/arcade/${AR.round.round_id}/step`);
    AR.fails = 0;
    $('arcade-net').classList.add('hidden');
    // القيم المالية تُحدَّث في كل استطلاع — مهم لاستكمال جولة معلّقة
    $('arcade-value').textContent = fmt0(s.portfolio_value);
    const ret = (s.portfolio_value - AR.round.capital) / AR.round.capital * 100;
    $('arcade-return').innerHTML = `<span class="${ret > 0 ? 'up' : ret < 0 ? 'down' : ''}">${pct(ret)}</span>`;
    $('arcade-cash').textContent = fmt0(s.cash);
    $('arcade-qty').textContent = fmtQty(s.holdings);
    $('arcade-avg').textContent = s.holdings > 0 ? fmt(AR.avgCost) : '—';
    if (s.step !== AR.lastStep) {
      AR.lastStep = s.step;
      const c = s.candle;
      if (AR.series) {
        AR.series.update({ time: c.ts, open: c.open, high: c.high, low: c.low, close: c.close });
        AR.volume.update({ time: c.ts, value: c.volume, color: c.close >= c.open ? '#22c55e55' : '#f43f5e55' });
      }
      const prev = AR.prevClose;
      const diff = prev ? (c.close - prev) / prev * 100 : 0;
      AR.prevClose = c.close;
      // أفضل/أسوأ يوم في الجولة (تغيّر قيمة المحفظة اليومي)
      const dayChg = AR.pvPrev ? (s.portfolio_value - AR.pvPrev) / AR.pvPrev * 100 : null;
      if (dayChg !== null) {
        if (!AR.bestDay || dayChg > AR.bestDay.pct) AR.bestDay = { pct: dayChg, date: c.ts };
        if (!AR.worstDay || dayChg < AR.worstDay.pct) AR.worstDay = { pct: dayChg, date: c.ts };
      }
      AR.pvPrev = s.portfolio_value;
      $('arcade-date').textContent = `📅 ${c.ts}`;
      $('arcade-dayno').textContent = `اليوم ${s.step + 1} من ${s.total_steps}`;
      $('arcade-progress-bar').style.width = ((s.step + 1) / s.total_steps * 100) + '%';
      $('arcade-price').textContent = fmt(c.close);
      $('arcade-price').className = 'mono ' + (diff > 0 ? 'up' : diff < 0 ? 'down' : '');
      if (s.is_last) {
        clearInterval(AR.timer);
        toast('🔔 نهاية التاريخ — تُختَم الجولة تلقائياً');
        setTimeout(autoFinish, 2200);
      }
    }
  } catch (e) {
    // H8: لا نوقف الجولة عند انقطاع مؤقت؛ نعيد المحاولة، وننهي فقط إن اختفت الجولة
    if (e?.status === 401) { clearInterval(AR.timer); return; }
    AR.fails++;
    if (e?.status === 404) { clearInterval(AR.timer); autoFinish(); return; }
    $('arcade-net').classList.remove('hidden');
    if (AR.fails > 40) { clearInterval(AR.timer); toast('تعذّر الاتصال — أعد فتح الجولة'); }
  }
}

async function autoFinish() {
  if (!AR.round) return;
  try { showResult(await api(`/api/arcade/${AR.round.round_id}/finish`, { method: 'POST' })); }
  catch (e) { if (e?.status !== 401) toast(e?.detail || 'تعذّر إنهاء الجولة'); }
}

async function finishArcade() {
  if (!AR.round) return;
  if (!confirm('هل تريد إنهاء الجولة الآن؟ لن تتمكن من متابعتها.')) return;
  clearInterval(AR.timer);
  const fin = $('arcade-finish'); fin.disabled = true;
  await autoFinish();
  fin.disabled = false;
}

async function arTrade(side) {
  if (!AR.round) return;
  const s = await api(`/api/arcade/${AR.round.round_id}/step`).catch(() => null);
  if (!s) { toast('تعذّر تنفيذ الصفقة'); return; }
  const price = s.candle.close;
  let q;
  if (side === 'buy') {
    q = AR.preset > 0 ? s.cash * AR.preset / (price * 1.001) : s.cash / (price * 1.001);
  } else {
    q = AR.preset > 0 ? s.holdings * AR.preset : s.holdings;
  }
  q = Math.floor(q * 100) / 100;
  if (q <= 0) { toast(side === 'buy' ? 'لا نقود لديك' : 'لا مقتنيات لديك'); haptic('error'); return; }
  try {
    const r = await api(`/api/arcade/${AR.round.round_id}/trade`, {
      method: 'POST', body: JSON.stringify({ side, quantity: q }),
    });
    AR.avgCost = r.avg_cost;
    haptic('light');
    arLog(`${side === 'buy' ? '🟢 شراء' : '🔴 بيع'} ${fmtQty(q)} @ ${fmt(r.executed_price)}`);
    $('arcade-cash').textContent = fmt0(r.cash);
    $('arcade-qty').textContent = fmtQty(r.holdings);
    $('arcade-avg').textContent = r.holdings > 0 ? fmt(r.avg_cost) : '—';
  } catch (e) { if (e?.status !== 401) { toast(e?.detail || 'تعذّر تنفيذ الصفقة'); haptic('error'); } }
}

function arLog(msg) {
  const l = $('arcade-log');
  l.innerHTML = `<div>${esc(msg)}</div>` + l.innerHTML;
}

function showResult(r) {
  AR.round = null;
  hideBack();
  $('arcade-game').classList.add('hidden');
  $('arcade-result').classList.remove('hidden');
  const rankEmoji = { 'أسطورة 🏆': '🏆', 'محترف 🥇': '🥇', 'ناجح ✅': '✅', 'متمهل 😐': '😐', 'خاسر 💀': '💀' };
  const rankClass = r.rank.includes('أسطورة') ? 'up' : r.rank.includes('خاسر') ? 'down' : '';
  $('result-rank').innerHTML = `${rankEmoji[r.rank] || ''} ${esc(r.rank)}`;
  $('result-rank').className = 'result-rank ' + rankClass;
  $('result-pct').innerHTML = `<span class="${r.return_pct >= 0 ? 'up' : 'down'}">${pct(r.return_pct)}</span>`;

  // جملة توجيهية تشرح السبب بعد كل نتيجة (U43) — في الجولة الفردية فقط
  const tipBox = $('result-tip');
  tipBox.classList.remove('hidden');
  if (r.duel) {
    tipBox.classList.add('hidden');
  } else if (r.rank.includes('أسطورة') || r.rank.includes('محترف')) {
    tipBox.textContent = `🚀 تفوقت على السوق بـ ${pct(r.excess_return_pct)} — نفس الأسلوب سيرفعك للأعلى`;
  } else if (r.rank.includes('ناجح')) {
    tipBox.textContent = `✅ تجاوزت السوق بهامش ${pct(r.excess_return_pct)} — الردهمة على سرعة الدخول والخروج`;
  } else if (r.rank.includes('متمهل')) {
    tipBox.textContent = `😐 تراجعت عن السوق بـ ${pct(r.excess_return_pct)} — جرب الدخول المبكر ثم التزم بالانتشار`;
  } else {
    tipBox.textContent = `💀 تراجعت عن السوق بـ ${pct(Math.abs(r.excess_return_pct))} — حدد وجهة الخروج مبكراً حتى لا تأكل الأرباح كلها`;
  }
  $('r-final').textContent = fmt0(r.final_value) + ' ◈';
  $('r-stock').innerHTML = `<span class="${r.return_pct >= 0 ? 'up' : 'down'}">${pct(r.return_pct)}</span>`;
  $('r-bench').innerHTML = r.benchmark_available === false
    ? `<span class="muted">غير متاح</span>`
    : `<span class="${r.benchmark_return_pct >= 0 ? 'up' : 'down'}">${pct(r.benchmark_return_pct)}</span>`;
  $('r-excess').innerHTML = `<span class="${r.excess_return_pct >= 0 ? 'up' : 'down'}">${pct(r.excess_return_pct)}</span>`;
  $('r-days').textContent = r.days;
  $('r-bonus').innerHTML = r.bonus_coins > 0 ? `<span style="color:var(--gold)">+${fmt0(r.bonus_coins)} ◈</span>` : '—';
  $('result-xp').textContent = `⭐ +${r.points} XP`;
  const ex = $('result-extra');
  ex.innerHTML = (AR.bestDay && AR.worstDay && AR.bestDay.date !== AR.worstDay.date)
    ? `🔥 أفضل يوم لك: ${esc(AR.bestDay.date)} (${pct(AR.bestDay.pct)})<br>🥶 أثقل يوم: ${esc(AR.worstDay.date)} (${pct(AR.worstDay.pct)})`
    : '';
  haptic(r.rank.includes('خاسر') ? 'error' : 'success');
  const d = r.duel;
  const wasDuel = AR.duelOn;
  if (d) {
    const el = $('result-duel');
    el.classList.remove('hidden');
    el.innerHTML = `<div class="vs-badge">⚔️</div> ${esc(d.message || '')}`;
  } else {
    $('result-duel').classList.add('hidden');
  }
  AR.duelOn = false;
  $('arcade-again').onclick = () => {
    $('arcade-result').classList.add('hidden');
    if (wasDuel || (d && d.state === 'done')) {
      setArcadeMode('duel');
      loadDuels().catch(() => {});
    } else {
      $('arcade-intro').classList.remove('hidden');
    }
  };
  loadPortfolio(true).catch(() => {});
}

/* ════════════ المبارزات 1v1 (المرحلة 2) ════════════ */
const BOT_USER = 'Sahmgame_bot';
let AMODE = 'solo';

function timeLeftText(iso) {
  const t = new Date(iso).getTime();
  if (isNaN(t)) return '';
  const left = t - Date.now();
  if (left <= 0) return '';
  const h = Math.floor(left / 3.6e6), m = Math.floor((left % 3.6e6) / 6e4);
  return h >= 1 ? `متبقي ${h} س ${m} د` : `متبقي ${m} د`;
}

function setArcadeMode(mode) {
  if (AR.round) { toast('أنهِ جولتك الحالية أولاً'); return; }  // H9/U8
  AMODE = mode;
  document.querySelectorAll('#arcade-seg .seg-b').forEach(b => b.classList.toggle('active', b.dataset.mode === mode));
  $('arcade-intro').classList.toggle('hidden', mode !== 'solo');
  $('duel-intro').classList.toggle('hidden', mode !== 'duel');
  haptic('light');
  if (mode === 'duel') loadDuels().catch(() => {});
}

document.querySelectorAll('#arcade-seg .seg-b').forEach(b =>
  b.addEventListener('click', () => setArcadeMode(b.dataset.mode)));

$('duel-create').addEventListener('click', createDuel);
$('duel-quick').addEventListener('click', () => joinDuel('?'));
$('duel-join').addEventListener('click', () => {
  const code = $('duel-code').value.trim().toUpperCase();
  if (!code) { toast('اكتب رمز التحدي'); return; }
  joinDuel(code);
});

async function loadDuels() {
  let list;
  try {
    list = await api('/api/duels');
  } catch (e) {
    $('seg-duel-dot').hidden = true;
    if (e?.status === 401) return;
    showError($('duel-list'), e?.detail || 'تعذّر تحميل المبارزات', loadDuels);
    return;
  }
  const active = list.filter(d => d.status === 'active' || d.status === 'open');
  $('seg-duel-dot').hidden = active.length === 0;
  const el = $('duel-list');
  if (!list.length) {
    el.innerHTML = `<div class="empty"><div class="em">⚔️</div><p>لا مبارزات بعد — أنشئ تحدّياً واقرعه لأصدقائك!</p></div>`;
    return;
  }
  el.innerHTML = list.map(d => duelCard(d)).join('')
    + `<button class="btn btn-ghost btn-sm duel-refresh">🔄 تحديث القائمة</button>`;
  wireDuelCard(el);
  duelAutoTimer && clearTimeout(duelAutoTimer);
  if (list.some(d => d.status === 'active' && (d.challenger_excess == null) !== (d.opponent_excess == null))) {
    duelAutoTimer = setTimeout(() => { if (AMODE === 'duel') loadDuels().catch(() => {}); }, 30000);
  }
}
let duelAutoTimer = null;

function duelCard(d) {
  const win = d.winner_id;
  const meCh = d.challenger_id === USER?.id;
  const myExcess = meCh ? d.challenger_excess : d.opponent_excess;
  const oppName = meCh ? d.opponent_name : d.challenger_name;
  const oppExcess = meCh ? d.opponent_excess : d.challenger_excess;
  const won = win && win === USER?.id;
  const lost = win && win !== USER?.id;

  let state = '', right = '', emoji = '⚔️';
  if (d.status === 'open') {
    const left = timeLeftText(d.expires_at);
    emoji = '📣';
    state = `<div class="duel-title">تحدي مفتوح بانتظار خصم${left ? ` <span class="duel-timer">${left}</span>` : ''}</div>
      <div class="duel-meta">${esc(d.symbol_name)} • ${d.session_len} يوم • من ${esc(d.start_ts)} إلى ${esc(d.end_ts)}</div>
      <div class="duel-share"><code>${esc(d.code)}</code>
      <button class="btn btn-ghost btn-sm duel-copy" data-code="${esc(d.code)}">🔗 نسخ رابط الدعوة</button></div>`;
  } else if (d.status === 'expired') {
    emoji = '⌛';
    state = `<div class="duel-title">انتهت صلاحية التحدي</div>
      <div class="duel-meta">${esc(d.symbol_name)} • ${d.session_len} يوم</div>`;
  } else if (d.status === 'active') {
    if (myExcess != null) {
      state = `<div class="duel-title">بانتظار ${esc(oppName || 'الخصم')} يُنهي جولته…</div>
        <div class="duel-meta">${esc(d.symbol_name)} • ${d.session_len} يوم • متاح حتى ${esc((d.expires_at || '').slice(0, 16).replace('T', ' '))}</div>`;
      right = `<div class="duel-side"><b class="mono ${myExcess >= 0 ? 'up' : 'down'}">${pct(myExcess)}</b><span class="duel-name">عائدك</span></div>`;
    } else {
      state = `<div class="duel-title">جاهزة للعب! 🆚 ${esc(oppName || 'خصم')}</div>
        <div class="duel-meta">${esc(d.symbol_name)} • ${d.session_len} يوم • متاح حتى ${esc((d.expires_at || '').slice(0, 16).replace('T', ' '))}</div>`;
      right = `<button class="btn btn-primary duel-btn duel-play" data-id="${d.id}">العب جولتك</button>`;
    }
  } else { // finished
    emoji = won ? '🏆' : lost ? '💀' : '🤝';
    const a = d.challenger_excess != null ? pct(d.challenger_excess) : 'لم يُنهِ';
    const b = d.opponent_excess != null ? pct(d.opponent_excess) : 'لم يُنهِ';
    state = `<div class="duel-title ${won ? 'win' : lost ? 'lose' : 'tie'}">${won ? 'فوز!' : lost ? 'خسارة' : 'تعادل'}</div>
      <div class="duel-meta">${esc(d.challenger_name)} ${a} <span class="vs-badge">VS</span> ${esc(d.opponent_name || 'خصم')} ${b}</div>
      <div class="duel-rematch-wrap">
        <button class="btn btn-ghost btn-sm duel-rematch">🆚 مبارزة جديدة (نافذة جديدة)</button>
      </div>`;
  }
  return `<div class="card duel-card">
    <div class="duel-emoji">${emoji}</div>
    <div class="duel-mid">${state}</div>
    ${right || ''}
  </div>`;
}

function wireDuelCard(root) {
  root.querySelectorAll('.duel-play').forEach(b => b.addEventListener('click', async () => {
    b.disabled = true; b.textContent = '⏳';
    try {
      const res = await api(`/api/duels/${b.dataset.id}/play`, { method: 'POST' });
      AR.duelOn = true;
      enterArcadeGame(res.round);
    } catch (e) { toast(e?.detail || 'تعذّر البدء'); b.disabled = false; b.textContent = 'العب جولتك'; }
  }));
  root.querySelectorAll('.duel-rematch').forEach(b => b.addEventListener('click', () => {
    if (AR.round) { toast('أنهِ جولتك الحالية أولاً'); return; }
    createDuel();  // نافذة جديدة عمداً — إعادة نفس النافذة تكشف المستقبل للطرفين
  }));
  root.querySelectorAll('.duel-copy').forEach(b => b.addEventListener('click', async () => {
    const link = `https://t.me/${BOT_USER}?start=join_${b.dataset.code}`;
    try { await navigator.clipboard.writeText(link); toast('تم نسخ رابط الدعوة ✅'); }
    catch { toast('رمز التحدي: ' + b.dataset.code); }
  }));
}

async function createDuel() {
  const btn = $('duel-create'); btn.disabled = true; btn.textContent = '⏳ جاري التجهيز…';
  try {
    const res = await api('/api/duels', { method: 'POST' });
    haptic('success');
    await loadDuels();
    toast(`تحدي جاهز — شارك الرمز ${res.duel.code}`);
  } catch (e) { if (e?.status !== 401) toast(e?.detail || 'تعذّر الإنشاء'); }
  btn.disabled = false; btn.textContent = '🎯 أنشئ تحدّياً وشاركه';
}

$('duel-list').addEventListener('click', (e) => {
  if (e.target.closest('.duel-refresh')) { loadDuels().catch(() => {}); haptic('light'); }
});

async function joinDuel(code) {
  try {
    await api('/api/duels/join', { method: 'POST', body: JSON.stringify({ code }) });
    haptic('success');
    toast('⚔️ قبلت التحدي — العب جولتك الآن!');
    await loadDuels();
  } catch (e) { if (e?.status !== 401) toast(e?.detail || 'فشل الانضمام'); }
}

/* ════════════ استكمال جولة معلّقة (الخطة 2.2) ════════════ */
let RESUME = null;

async function loadArcadeHub() {
  if (AR.round) return;
  try {
    const r = await api('/api/arcade/active');
    RESUME = (r && r.active) ? r.active : null;
  } catch { RESUME = null; }
  const el = $('arcade-resume');
  if (!el) return;
  el.classList.toggle('hidden', !RESUME);
  if (RESUME) {
    $('resume-sym').textContent =
      `${RESUME.name} • ${RESUME.kind === 'duel' ? '⚔️ مبارزة' : '⚡ جولة فردية'}`;
  }
}

$('btn-resume').addEventListener('click', async () => {
  if (!RESUME) return;
  const b = $('btn-resume'); b.disabled = true;
  try {
    const d = await api(`/api/arcade/${RESUME.round_id}/resume`);
    RESUME = null;
    $('arcade-result')?.classList.add('hidden');
    enterArcadeGame(d.round, d);
  } catch (e) {
    toast(e?.detail || 'تعذّر استكمال الجولة');
    b.disabled = false;
  }
});

/* ════════════ التحديات اليومية/الأسبوعية (الخطة 3.3) ════════════ */
async function loadQuests() {
  try {
    const q = await api('/api/quests');
    renderQuests(q);
  } catch { /* التحديات ليست حرجة — الصمت أفضل من وهج خطأ دائم */ }
}

function renderQuests(q) {
  const mk = (box, title, list) => {
    const el = $(box); if (!el) return;
    el.innerHTML = `<div class="q-head">${title}</div>` + (list || []).map(x =>
      `<div class="q-row${x.done ? ' done' : ''}">
        <span>${x.emoji} ${esc(x.title)}</span>
        <b class="mono">${x.done ? '✓ +' + fmt0(x.reward) + ' ◈' : `${x.current}/${x.target}`}</b>
      </div>`).join('');
  };
  mk('quest-daily', '🎯 تحديات اليوم', q.daily);
  mk('quest-weekly', '🗓️ تحديات الأسبوع', q.weekly);
}

/* ════════════ الدوري الأسبوعي (المرحلة 2) ════════════ */
async function loadLeague() {
  let lg;
  try {
    lg = await api('/api/league');
  } catch (e) {
    if ($('lg-top')) showError($('lg-top'), e?.detail || 'تعذّر تحميل الدوري', loadLeague);
    return;
  }
  $('lg-countdown').textContent = '⏳ ' + lg.countdown
    + (lg.players ? ` • ${lg.players} لاعب` : '');
  const medals = { 1: '🥇', 2: '🥈', 3: '🥉' };
  const top = (lg.standings || []).slice(0, 5);
  $('lg-top').innerHTML = top.length
    ? top.map(r => `<div class="lg-row${r.user_id === USER?.id ? ' me' : ''}">
        <span class="lg-rank">${medals[r.rank] || r.rank}</span>
        <span class="lg-name">${esc(rowName(r))}${r.user_id === USER?.id ? ' <span class="you-badge">أنت</span>' : ''}</span>
        <span class="lg-score">${r.score >= 0 ? '+' : ''}${fmt(r.score, 1)} نقطة
          <small class="lg-meta">${r.rounds} جولة • ${r.pred_wins} توقع</small></span>
      </div>`).join('')
    : '<div class="lg-row"><span class="lg-name">لا نتائج هذا الأسبوع بعد — العب جولة!</span></div>';
  const me = $('lg-me');
  const m = lg.me;
  me.classList.toggle('hidden', !m || !m.rank);
  if (m && m.rank) {
    me.innerHTML = `<span>🧍 مركزك <b>${m.rank}</b></span>
      <span class="lg-gap">${esc(m.gap_text || '')}</span>`;
  }
  $('lg-prizes').innerHTML = (lg.prizes || [])
    .map(p => `<span style="margin-left:10px">🏅 ${p.rank}: ${fmt0(p.coins)} ◈ + ${p.xp} XP</span>`).join('');
  const champ = lg.champion;
  if ($('lg-rules')) {
    $('lg-rules').innerHTML = 'النقاط = عائدك الزائد + 2 لكل توقع صحيح • على الأقل 3 جولات مكتملة لجائزة • توزيع يوم الجمعة'
      + (champ ? `<br>🏆 بطل الأسبوع الماضي: <b>${esc(champ.username || 'لاعب')}</b> (${fmt0(champ.score)} نقطة)` : '');
  }
}

/* ════════════ وضع كيفية اللعب (U9) ════════════ */
function openHowto() { $('howto').classList.remove('hidden'); showBack(closeHowto); }
function closeHowto() {
  $('howto').classList.add('hidden'); hideBack();
  try { localStorage.setItem('sahem_howto_seen', '1'); } catch {}  // مرة واحدة فقط
}
$('howto-btn').addEventListener('click', openHowto);
$('howto-close').addEventListener('click', closeHowto);
$('howto').addEventListener('click', (e) => { if (e.target.id === 'howto') closeHowto(); });

/* ════════════ التبويبات ════════════ */
const LOADERS = {
  markets: () => loadPrices(false),
  arcade: loadArcadeHub,
  predict: loadPredict,
  portfolio: () => Promise.allSettled([loadPortfolio(false), loadQuests()]),
  leaderboard: () => Promise.allSettled([loadLeague(), loadLeaderboard()]),
};

function showTab(name, updateHash = true) {
  const el = $('tab-' + name);
  if (!el) name = 'markets';
  document.querySelectorAll('.bottom-nav .tab').forEach(b => b.classList.toggle('active', b.dataset.tab === name));
  document.querySelectorAll('.tabview').forEach(s => s.classList.remove('active'));
  ($('tab-' + name) || $('tab-markets')).classList.add('active');
  haptic('light');
  LOADERS[name]?.()?.catch?.(() => {});
  if (updateHash) { try { history.replaceState(null, '', '#' + name); } catch {} }
}

$('bottom-nav').addEventListener('click', (e) => {
  const btn = e.target.closest('.tab'); if (!btn || btn.classList.contains('active')) return;
  showTab(btn.dataset.tab);
});

/* دعم الروابط العميقة #arcade / #leaderboard من البوت (H6/U2) */
function applyHash() {
  const name = (location.hash || '').replace('#', '');
  if (['markets', 'arcade', 'predict', 'portfolio', 'leaderboard'].includes(name)) {
    showTab(name, false);
    return true;
  }
  return false;
}
window.addEventListener('hashchange', applyHash);

/* ════════════ الإقلاع ════════════ */
(async () => {
  const authed = await auth();
  if (!authed) {
    $('splash').classList.add('fade');
    setTimeout(() => $('splash').classList.add('hidden'), 300);
    $('gate').classList.remove('hidden');
    return;
  }
  // شاشة «كيف ألعب» تلقائياً أول مرة (U9) — لا تُفتح مع الروابط العميقة ولا في وضع المعاينة
  try {
    const seen = localStorage.getItem('sahem_howto_seen');
    if (!seen && !IS_MOCK) {
      window.__howtoPending = true;
    }
  } catch {}

  loadPortfolio(true).catch(() => {});
  await loadPrices(false);

  const sp = $('splash');
  sp.classList.add('fade');
  setTimeout(() => sp.classList.add('hidden'), 400);

  const deepLinked = applyHash();  // افتح التبويب المطلوب من الرابط
  if (window.__howtoPending && !deepLinked) {
    setTimeout(openHowto, 700);
    delete window.__howtoPending;
  }

  priceTimer = setInterval(() => {
    if ($('tab-markets').classList.contains('active')) loadPrices(true);
  }, 60000);
})();
