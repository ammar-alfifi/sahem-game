/* ═══════════════════════════════════════════
   سهم — منطق التطبيق المصغّر (v2)
   🎮 يدعم المعاينة خارج تيليجرام عبر ?mock=1
   ═══════════════════════════════════════════ */

const tg = window.Telegram?.WebApp;
const IS_MOCK = new URLSearchParams(location.search).has('mock');
const IS_TG = !!(tg && tg.initData && tg.initData.length);
const API = new URLSearchParams(location.search).get('api')
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
const pct = (p) => (p > 0 ? '▲ +' : p < 0 ? '▼ ' : '— ') + fmt(p) + '%';
let toastTimer = null;
function toast(msg, ms = 3200) {
  const t = $('toast'); t.textContent = msg; t.classList.add('show');
  clearTimeout(toastTimer); toastTimer = setTimeout(() => t.classList.remove('show'), ms);
}

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
  const res = await fetch(API + path, { ...opts, headers });
  if (res.status === 401) {
    TOKEN = null;
    if (!opts._silent) {
      toast('انتهت الجلسة — أعد فتح التطبيق من البوت');
      $('gate').classList.remove('hidden');
    }
    throw new Error('unauth');
  }
  if (!res.ok) {
    const e = await res.json().catch(() => ({}));
    if (e.detail) toast(String(e.detail));
    const err = new Error('api'); err.detail = e.detail; throw err;
  }
  return res.json();
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

/* إبلاغ الخادم لمشكلة تشخيص البوابة */
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
  const dbg = $('gate-debug');
  if (dbg) dbg.textContent = 'تشخيص: ' + reason + ' • initData: ' + ((tg?.initData || '').length) + ' حرفاً';
}

/* ─── الهياكل العظمية ─── */
function skeletons(box, n = 5) {
  box.innerHTML = Array(n).fill('<div class="skel"></div>').join('');
}

/* ═════════-market الفلترة والبحث═════════ */
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
  currentSearch = e.target.value.trim();
  renderPrices();
});

/* ════════════ السوق ════════════ */
async function loadPrices(silent = true) {
  try {
    if (!silent) skeletons($('prices-list'), 6);
    PRICES = await api('/api/prices');
    renderPrices();
  } catch {}
}

function renderPrices() {
  const list = PRICES.filter(p =>
    (currentFilter === 'all' || p.market === currentFilter) &&
    (!currentSearch || p.name.includes(currentSearch) || p.symbol.toUpperCase().includes(currentSearch.toUpperCase()))
  );
  const box = $('prices-list');
  if (!list.length) {
    box.innerHTML = `<div class="empty"><div class="em">🔍</div><p>لا توجد نتائج مطابقة</p></div>`;
    return;
  }
  box.innerHTML = list.map(p => {
    const ch = p.change_pct ?? 0;
    const cls = ch > 0 ? 'up' : ch < 0 ? 'down' : '';
    const held = HOLDINGS[p.symbol] > 0.000001;
    return `<div class="card price-row" data-sym="${esc(p.symbol)}">
      ${avatarHTML(p)}
      <div class="sym-mid">
        <div class="sym-name">${esc(p.name)}</div>
        <div class="sym-meta">${esc(shortSymbol(p.symbol))} • ${(MARKET_INFO[p.market] || {}).label || ''}
          ${held ? `<span class="sym-hold">تملك ${fmt(HOLDINGS[p.symbol], 0)}</span>` : ''}</div>
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
}
function closeSheet() {
  $('sheet-backdrop').classList.add('hidden');
}
$('sheet-backdrop').addEventListener('click', (e) => { if (e.target.id === 'sheet-backdrop') closeSheet(); });

function affordability(p) {
  const bal = PORTFOLIO ? PORTFOLIO.balance / (p.price * 1.001) : 0;
  return { maxBuy: bal, held: HOLDINGS[p.symbol] || 0 };
}

function renderSheet() {
  const p = SHEET.sym;
  const { held } = affordability(p);
  const info = MARKET_INFO[p.market] || {};
  $('sheet-trade').innerHTML = `
    <div class="sheet-handle"></div>
    <div class="sh-head">
      ${avatarHTML(p)}
      <div><div class="sh-name">${esc(p.name)}</div><div class="sh-sym">${esc(p.symbol)} • ${info.label || ''}</div></div>
      <div class="sh-price"><div class="sh-price-1">${fmt(p.price)}</div><div class="sh-price-2 ${p.change_pct > 0 ? 'up' : p.change_pct < 0 ? 'down' : ''}">${pct(p.change_pct)}</div></div>
    </div>
    <div class="sh-info">
      <div><span>💰 رصيدك النقدي</span><b>${PORTFOLIO ? fmt0(PORTFOLIO.balance) + ' ◈' : '—'}</b></div>
      <div><span>📦 مملوك لديك</span><b>${fmt(held, 0)} وحدة</b></div>
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
    <button id="sh-confirm" class="btn btn-block btn-lg ${SHEET.side === 'buy' ? 'btn-buy' : 'btn-sell'}">
      ${SHEET.side === 'buy' ? '🟢 تأكيد الشراء' : '🔴 تأكيد البيع'}
    </button>`;
  $('sheet-trade').querySelectorAll('.qty-presets button').forEach(b => b.addEventListener('click', () => {
    SHEET.qty = b.dataset.q === 'A'
      ? (SHEET.side === 'buy' ? affordability(p).maxBuy : held)
      : Number(b.dataset.q);
    renderSheet();
  }));
  $('sh-qty-in').addEventListener('input', (e) => { SHEET.qty = parseFloat(e.target.value) || 0; updateCost(); });
  updateCost();
  $('side-buy').onclick = () => { SHEET.side = 'buy'; renderSheet(); };
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
  btn.disabled = true; btn.style.opacity = .6; btn.textContent = '⏳ جاري التنفيذ...';
  try {
    const r = await api('/api/trade', { method: 'POST', body: JSON.stringify({ symbol: SHEET.sym.symbol, side: SHEET.side, quantity: SHEET.qty }) });
    if (!r.ok) { toast(r.error); btn.disabled = false; btn.style.opacity = 1; btn.textContent = SHEET.side === 'buy' ? '🟢 تأكيد الشراء' : '🔴 تأكيد البيع'; return; }
    haptic('success');
    toast(SHEET.side === 'buy' ? `✅ اشتريت ${fmt(SHEET.qty, 0)} بسعر ${fmt(r.price)}` : `✅ بعت ${fmt(SHEET.qty, 0)} بسعر ${fmt(r.price)}`);
    closeSheet();
    await loadPortfolio(true);
    renderPrices();
  } catch { closeSheet(); }
}

/* ════════════ التوقعات ════════════ */
const PRED_W = { up: 2.2, down: 3.3, flat: 4.0 };
async function loadPredict() {
  const prices = await api('/api/prices').catch(() => []);
  PRICES = prices; // مزامنة الكاش
  const mine = await api('/api/predictions').catch(() => []);
  const pendingSyms = new Set(mine.map(p => p.symbol));
  const byMarket = {};
  prices.filter(p => p.price !== null).forEach(p => (byMarket[p.market] ||= []).push(p));
  const box = $('predict-list');
  skeletonOrList(box, 4);
  const html = [];
  for (const mk of ['SA', 'US', 'CRYPTO']) {
    if (!byMarket[mk]) continue;
    html.push(`<h3 class="sec-title">${MARKET_INFO[mk].flag} ${MARKET_INFO[mk].label}</h3>`);
    for (const p of byMarket[mk]) {
      if (pendingSyms.has(p.symbol)) continue; // لا تكرر السهم الذي وُضع عليه توقعة
      html.push(`<div class="card predict-card">
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
  box.innerHTML = html.join('');
  box.onclick = (e) => {
    const b = e.target.closest('.pred-btn'); if (!b) return;
    const card = b.closest('.predict-card');
    const name = card.querySelector('.sym-name')?.textContent;
    const sym = PRICES.find(x => x.name === name)?.symbol;
    if (sym) makePrediction(sym, b.dataset.d);
  };

  // توقعاتي
  const dirAr = { up: '▲ صعود', down: '▼ هبوط', flat: '— ثبات' };
  $('my-predictions').innerHTML = mine.length ? mine.map(p => {
    const dir = p.direction;
    return `<div class="card pred-mine">
      <span>${dirAr[dir] || dir} <b>${esc(p.symbol)}</b></span>
      <span class="count-badge" data-r="${esc(p.resolves_at)}">…</span>
    </div>`;
  }).join('') : `<div class="empty"><div class="em">🎯</div><p>لا توقعات قائمة — ضع أول توقع!</p></div>`;
  countdownTick();
}

function skeletonOrList(box, n) { skeletons(box, n); }

async function makePrediction(sym, direction) {
  try {
    const r = await api('/api/predict', { method: 'POST', body: JSON.stringify({ symbol: sym, direction }) });
    if (r.ok) { haptic('success'); toast('✅ سُجّلت توقعتك! النتيجة بعد إغلاق السوق'); await loadPredict(); }
    else toast(r.error);
  } catch {}
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
  const pf = await api('/api/portfolio').catch(() => null);
  if (!pf) return;
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

  const box = $('pf-positions');
  if (!silent) box.innerHTML = '';
  box.innerHTML = pf.positions.length ? pf.positions.map(p => {
    const cls = p.pnl_pct > 0 ? 'up' : p.pnl_pct < 0 ? 'down' : '';
    const fake = { symbol: p.symbol, name: p.name, price: p.current_price, market: p.market, change_pct: p.change_pct ?? 0 };
    return `<div class="card price-row" data-sym="${esc(p.symbol)}" data-pos="1">
      ${avatarHTML(fake)}
      <div class="sym-mid">
        <div class="sym-name">${esc(p.name)}</div>
        <div class="sym-meta">متوسط ${fmt(p.avg_cost)} • الآن ${fmt(p.current_price)}</div>
      </div>
      <div class="sym-right">
        <div class="sym-price">${fmt0(p.market_value)} ◈</div>
        <div class="sym-change ${cls}">${pct(p.pnl_pct)}</div>
      </div>
    </div>`;
  }).join('') : `<div class="empty"><div class="em">💼</div><p>محفظتك فارغة — اشترِ أول سهم من تبويب السوق!</p></div>`;
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
  skeletons($('lb-list'), 4);
  const rows = await api('/api/leaderboard').catch(() => []);
  const podium = $('lb-podium'), list = $('lb-list');
  if (!rows.length) {
    podium.innerHTML = '';
    list.innerHTML = `<div class="empty"><div class="em">🏆</div><p>لوحة الصدارة فاضية — كن أول اللاعبين!</p></div>`;
    return;
  }
  const top = rows.slice(0, 3);
  const medals = ['🥇', '🥈', '🥉'];
  if (top.length === 3) {
    podium.innerHTML = top.map((r, i) => `<div class="pod p${i + 1}">
      <div class="pod-avatar">${medals[i]}</div>
      <div class="pod-name">${esc(r.username || 'لاعب ' + (i + 1))}</div>
      <div class="pod-val">${fmt(r.weekly_value || 0, 0)}</div>
    </div>`).join('');
    list.innerHTML = rows.slice(3).map((r, i) => `<div class="card lb-row">
      <div class="lb-rank">${i + 4}</div>
      <div class="sym-mid"><div class="sym-name">${esc(r.username || 'لاعب')}</div>
      <div class="sym-meta">مستوى ${r.level} • ${r.rounds} جولة</div></div>
      <div class="sym-price mono" style="color:var(--gold)">${fmt(r.weekly_value || 0, 0)} ◈</div>
    </div>`).join('');
  } else {
    podium.innerHTML = '';
    list.innerHTML = rows.map((r, i) => `<div class="card lb-row">
      <div class="lb-rank lb-medal">${medals[i] || (i + 1)}</div>
      <div class="sym-mid"><div class="sym-name">${esc(r.username || 'لاعب')}</div>
      <div class="sym-meta">مستوى ${r.level} • ${r.rounds} جولة</div></div>
      <div class="sym-price mono" style="color:var(--gold)">${fmt(r.weekly_value || 0, 0)} ◈</div>
    </div>`).join('');
  }
}

/* ════════════ الأركيد ════════════ */
const AR = { timer: null, chart: null, series: null, volume: null, data: [], round: null, lastStep: -1, preset: 0.25, duelOn: false };
$('arcade-start').addEventListener('click', startArcade);
$('arcade-finish').addEventListener('click', finishArcade);
$('btn-buy').addEventListener('click', () => arTrade('buy'));
$('btn-sell').addEventListener('click', () => arTrade('sell'));
$('arcade-presets').addEventListener('click', (e) => {
  const b = e.target.closest('button'); if (!b) return;
  AR.preset = parseFloat(b.dataset.q);
  document.querySelectorAll('#arcade-presets button').forEach(x => x.classList.remove('sel'));
  b.classList.add('sel');
});

async function startArcade() {
  try {
    const rnd = await api('/api/arcade/start', { method: 'POST' });
    enterArcadeGame(rnd);
  } catch {}
}

function enterArcadeGame(rnd) {
  AR.round = rnd; AR.data = []; AR.lastStep = -1;
  $('arcade-intro').classList.add('hidden');
  $('duel-intro').classList.add('hidden');
  $('arcade-result').classList.add('hidden');
  $('arcade-game').classList.remove('hidden');
  $('arcade-symbol').textContent = rnd.name;
  $('arcade-log').innerHTML = '';
  $('arcade-avg').textContent = '—';
  $('arcade-progress-bar').style.width = '0%';
  initChart();
  haptic('success');
  AR.timer = setInterval(pollArcadeStep, Math.max(700, rnd.step_seconds * 500));
  pollArcadeStep();
}

function initChart() {
  if (AR.chart) { AR.chart.remove(); AR.chart = null; }
  const el = $('arcade-chart');
  AR.chart = LightweightCharts.createChart(el, {
    width: el.clientWidth, height: 230,
    layout: { background: { color: '#131a23' }, textColor: '#8fa2b8', fontFamily: 'Cairo' },
    grid: { vertLines: { color: '#1b2430', visible: true }, horzLines: { color: '#1b2430', visible: true } },
    rightPriceScale: { borderColor: '#243044' },
    timeScale: { borderColor: '#243044' },
    localization: { locale: 'ar' },
  });
  AR.series = AR.chart.addCandlestickSeries({
    upColor: '#22c55e', downColor: '#f43f5e', borderVisible: false,
    wickUpColor: '#22c55e', wickDownColor: '#f43f5e',
  });
  AR.volume = AR.chart.addHistogramSeries({ priceScaleId: '', topColor: '#38bdf855', bottomColor: '#38bdf818' });
  AR.volume.priceScale().applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
  window.addEventListener('resize', () => { if (AR.chart) AR.chart.applyOptions({ width: el.clientWidth }); });
}

async function pollArcadeStep() {
  if (!AR.round) return;
  try {
    const s = await api(`/api/arcade/${AR.round.round_id}/step`);
    if (s.step !== AR.lastStep) {
      AR.lastStep = s.step;
      const c = s.candle;
      AR.series.update({ time: c.ts, open: c.open, high: c.high, low: c.low, close: c.close });
      AR.volume.update({ time: c.ts, value: c.volume, color: c.close >= c.open ? '#22c55e55' : '#f43f5e55' });
      const prev = AR.prevClose;
      const diff = prev ? (c.close - prev) / prev * 100 : 0;
      AR.prevClose = c.close;
      $('arcade-date').textContent = `📅 ${c.ts}`;
      $('arcade-dayno').textContent = `اليوم ${s.step + 1} من ${s.total_steps}`;
      $('arcade-progress-bar').style.width = ((s.step + 1) / s.total_steps * 100) + '%';
      $('arcade-value').textContent = fmt0(s.portfolio_value);
      const ret = (s.portfolio_value - AR.round.capital) / AR.round.capital * 100;
      $('arcade-return').innerHTML = `<span class="${ret > 0 ? 'up' : ret < 0 ? 'down' : ''}">${pct(ret)}</span>`;
      $('arcade-cash').textContent = fmt0(s.cash);
      $('arcade-qty').textContent = fmt(s.holdings, 0);
      $('arcade-avg').textContent = s.holdings > 0 ? fmt(getAvgCost()) : '—';
      $('arcade-price').textContent = fmt(c.close);
      if (prev) $('arcade-price').className = 'mono ' + (diff > 0 ? 'up' : diff < 0 ? 'down' : '');
      if (s.is_last) {
        clearInterval(AR.timer);
        toast('🔕 نهاية التاريخ — تُختَم الجولة تلقائياً');
        setTimeout(autoFinish, 2200);
      }
    }
  } catch { clearInterval(AR.timer); }
}

AR.avgCost = 0;
function getAvgCost() { return AR.avgCost; }

async function autoFinish() {
  try { showResult(await api(`/api/arcade/${AR.round.round_id}/finish`, { method: 'POST' })); }
  catch {}
}

async function finishArcade() {
  if (!AR.round) return;
  clearInterval(AR.timer);
  const fin = $('arcade-finish'); fin.disabled = true;
  await autoFinish();
  fin.disabled = false;
}

async function arTrade(side) {
  if (!AR.round) return;
  const s = await api(`/api/arcade/${AR.round.round_id}/step`).catch(() => null);
  if (!s) return;
  const price = s.candle.close;
  let q;
  if (side === 'buy') {
    const maxQty = s.cash / (price * 1.001);
    q = AR.preset > 0 ? s.cash * AR.preset / (price * 1.001) : maxQty;
  } else {
    q = AR.preset > 0 ? s.holdings * AR.preset : s.holdings;
  }
  q = Math.floor(q * 100) / 100;
  if (q <= 0) { toast(side === 'buy' ? 'لا نقود لديك' : 'لا مقتنيات لديك'); haptic('error'); return; }
  try {
    const r = await api(`/api/arcade/${AR.round.round_id}/trade`, {
      method: 'POST', body: JSON.stringify({ side, quantity: q }),
    });
    if (r.ok) {
      AR.avgCost = r.avg_cost;
      haptic('light');
      arLog(`${side === 'buy' ? '🟢 شراء' : '🔴 بيع'} ${fmt(q, 0)} @ ${fmt(r.executed_price)}`);
      $('arcade-cash').textContent = fmt0(r.cash);
      $('arcade-qty').textContent = fmt(r.holdings, 0);
      $('arcade-avg').textContent = r.holdings > 0 ? fmt(r.avg_cost) : '—';
    } else { toast(r.error); haptic('error'); }
  } catch {}
}

function arLog(msg) {
  const l = $('arcade-log');
  l.innerHTML = `<div>${msg}</div>` + l.innerHTML;
}

function showResult(r) {
  AR.round = null;
  $('arcade-game').classList.add('hidden');
  $('arcade-result').classList.remove('hidden');
  const rankEmoji = { 'أسطورة 🏆': '🏆', 'محترف 🥇': '🥇', 'ناجح ✅': '✅', 'متمهل 😐': '😐', 'خاسر 💀': '💀' };
  const rankClass = r.rank.includes('أسطورة') ? 'up' : r.rank.includes('خاسر') ? 'down' : '';
  $('result-rank').innerHTML = `${rankEmoji[r.rank] || ''} ${esc(r.rank)}`;
  $('result-rank').className = 'result-rank ' + rankClass;
  $('result-pct').innerHTML = `<span class="${r.return_pct >= 0 ? 'up' : 'down'}">${pct(r.return_pct)}</span>`;
  $('r-final').textContent = fmt0(r.final_value) + ' ◈';
  $('r-stock').innerHTML = `<span class="${r.return_pct >= 0 ? 'up' : 'down'}">${pct(r.return_pct)}</span>`;
  $('r-bench').innerHTML = `<span class="${r.benchmark_return_pct >= 0 ? 'up' : 'down'}">${pct(r.benchmark_return_pct)}</span>`;
  $('r-excess').innerHTML = `<span class="${r.excess_return_pct >= 0 ? 'up' : 'down'}">${pct(r.excess_return_pct)}</span>`;
  $('r-days').textContent = r.days;
  $('r-bonus').innerHTML = r.bonus_coins > 0 ? `<span style="color:var(--gold)">+${fmt0(r.bonus_coins)} ◈</span>` : '—';
  $('result-xp').textContent = `⭐ +${r.points} XP`;
  haptic(r.rank.includes('خاسر') ? 'error' : 'success');
  // مصير المبارزة (إن جاءت من مبارزة)
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
  skeletons($('duel-list'), 3);
  const list = await api('/api/duels').catch(() => []);
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
  // عدّاد الخصم: إعادة تحميل لطيفة كل 30 ثانية إن كانت هناك مباراة «بانتظار الخصم»
  duelAutoTimer && clearTimeout(duelAutoTimer);
  if (list.some(d => d.status === 'active' && (d.challenger_excess == null) !== (d.opponent_excess == null))) {
    duelAutoTimer = setTimeout(() => { if (AMODE === 'duel') loadDuels().catch(() => {}); }, 30000);
  }
}
let duelAutoTimer = null;

function duelCard(d) {
  const win = d.winner_id;
  const meCh = d.challenger_id === USER?.id;   // هويتي الداخلية
  const myExcess = meCh ? d.challenger_excess : d.opponent_excess;
  const oppName = meCh ? d.opponent_name : d.challenger_name;
  const won = win && win === USER?.id;
  const lost = win && win !== USER?.id;
  // من رأى المبارزة أنا لاعبها أم خليط طلب انضمام شخص؟ (لا — القائمة فقط مبارزاتي)

  let state = '', right = '', emoji = '⚔️';
  if (d.status === 'open') {
    const left = timeLeftText(d.expires_at);
    emoji = '📣';
    state = `<div class="duel-title">تحدي مفتوح بانتظار خصم${left ? ` <span class="duel-timer">${left}</span>` : ''}</div>
      <div class="duel-meta">${esc(d.symbol_name)} • ${d.session_len} يوم • من ${d.start_ts} إلى ${d.end_ts}</div>
      <div class="duel-share"><code>${d.code}</code>
      <button class="btn btn-ghost btn-sm duel-copy" data-code="${d.code}">🔗 نسخ رابط الدعوة</button></div>`;
  } else if (d.status === 'expired') {
    emoji = '⌛';
    state = `<div class="duel-title">انتهت صلاحية التحدي</div>
      <div class="duel-meta">${esc(d.symbol_name)} • ${d.session_len} يوم</div>`;
  } else if (d.status === 'active') {
    if (myExcess != null) {
      state = `<div class="duel-title">بانتظار ${esc(oppName || 'الخصم')} يُنهي جولته…</div>
        <div class="duel-meta">${esc(d.symbol_name)} • ${d.session_len} يوم • متاح حتى ${d.expires_at.slice(0, 16).replace('T', ' ')}</div>`;
      right = `<div class="duel-side"><b class="mono ${myExcess >= 0 ? 'up' : 'down'}">${pct(myExcess)}</b><span class="duel-name">عائدك</span></div>`;
    } else {
      state = `<div class="duel-title">جاهزة للعب! 🆚 ${esc(oppName || 'خصم')}</div>
        <div class="duel-meta">${esc(d.symbol_name)} • ${d.session_len} يوم • متاح حتى ${d.expires_at.slice(0, 16).replace('T', ' ')}</div>`;
      right = `<button class="btn btn-primary duel-btn duel-play" data-id="${d.id}">العب جولتك</button>`;
    }
  } else { // finished
    emoji = won ? '🏆' : lost ? '💀' : '🤝';
    const a = pct(d.challenger_excess ?? 0), b = pct(d.opponent_excess ?? 0);
    state = `<div class="duel-title ${won ? 'win' : lost ? 'lose' : 'tie'}">${won ? 'فوز!' : lost ? 'خسارة' : 'تعادل'}</div>
      <div class="duel-meta">${esc(d.challenger_name)} ${a} <span class="vs-badge">VS</span> ${esc(d.opponent_name || 'خصم')} ${b}</div>`;
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
    } catch (e) { toast(e?.message || 'تعذّر البدء'); b.disabled = false; b.textContent = 'العب جولتك'; }
  }));
  root.querySelectorAll('.duel-copy').forEach(b => b.addEventListener('click', async () => {
    const link = `https://t.me/${BOT_USER}?start=join_${b.dataset.code}`;
    try { await navigator.clipboard.writeText(link); toast('تم نسخ رابط الدعوة ✅'); }
    catch { toast('رمز التحدي: ' + b.dataset.code); }
  }));
}

async function createDuel() {
  const btn = $('duel-create'); btn.disabled = true; btn.textContent = '⏳ جاري التعداد…';
  try {
    const res = await api('/api/duels', { method: 'POST' });
    haptic('success');
    await loadDuels();
    toast(`تحدي جاهز — شارك الرمز ${res.duel.code}`);
  } catch (e) { toast(e?.message || 'تعذّر الإنشاء'); }
  btn.disabled = false; btn.textContent = '🎯 أنشئ تحدّياً وشاركه';
}

$('duel-list').addEventListener('click', (e) => {
  if (e.target.closest('.duel-refresh')) { loadDuels().catch(() => {}); haptic('light'); }
});

async function joinDuel(code) {
  try {
    const res = await api('/api/duels/join', { method: 'POST', body: JSON.stringify({ code }) });
    haptic('success');
    toast('⚔️ قبلت التحدي — العب جولتك الآن!');
    await loadDuels();
  } catch (e) { toast(e?.message || 'فشل الانضمام'); }
}

/* ════════════ الدوري الأسبوعي (المرحلة 2) ════════════ */
async function loadLeague() {
  const lg = await api('/api/league').catch(() => null);
  if (!lg) return;
  $('lg-countdown').textContent = '⏳ ' + lg.countdown
    + (lg.players ? ` • ${lg.players} لاعب` : '');
  const medals = { 1: '🥇', 2: '🥈', 3: '🥉' };
  const top = (lg.standings || []).slice(0, 5);
  $('lg-top').innerHTML = top.length
    ? top.map(r => `<div class="lg-row${r.username === USER?.username ? ' me' : ''}">
        <span class="lg-rank">${medals[r.rank] || r.rank}</span>
        <span class="lg-name">${esc(r.username || 'لاعب')}</span>
        <span class="lg-score">${r.score >= 0 ? '+' : ''}${fmt(r.score, 1)} نقطة
          <small class="lg-meta">${r.rounds} جولة • ${r.pred_wins} توقّع</small></span>
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
}

/* ════════════ التبويبات ════════════ */
const LOADERS = {
  markets: () => loadPrices(false),
  arcade: null,
  predict: loadPredict,
  portfolio: () => loadPortfolio(false),
  leaderboard: () => Promise.allSettled([loadLeague(), loadLeaderboard()]),
};
$('bottom-nav').addEventListener('click', (e) => {
  const btn = e.target.closest('.tab'); if (!btn || btn.classList.contains('active')) return;
  document.querySelectorAll('.bottom-nav .tab').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  document.querySelectorAll('.tabview').forEach(s => s.classList.remove('active'));
  $('tab-' + btn.dataset.tab).classList.add('active');
  haptic('light');
  LOADERS[btn.dataset.tab]?.()?.catch?.(() => {});
});

/*PHA ════════════ الإقلاع ════════════ */
(async () => {
  const authed = await auth();
  if (!authed) {
    $('splash').classList.add('fade');
    $('splash').classList.add('hidden');
    $('gate').classList.remove('hidden');
    return;
  }
  try {
    loadPortfolio(true).catch(() => {});
    await loadPrices(false);
  } catch {}
  // إقلاع ناعم
  const sp = $('splash');
  sp.classList.add('fade');
  setTimeout(() => sp.classList.add('hidden'), 400);
  // تحديث الأسعار دورياً أثناء وجودنا في تبويب السوق
  priceTimer = setInterval(() => {
    if ($('tab-markets').classList.contains('active')) loadPrices(true);
  }, 60000);
})();
