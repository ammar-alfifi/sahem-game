/* سهم — منطق التطبيق المصغّر (Vanilla JS) */
const tg = window.Telegram?.WebApp;
tg?.ready();
tg?.expand();
tg?.setHeaderColor('#0d1117');
tg?.setBackgroundColor('#0d1117');

const API = location.origin;
let TOKEN = localStorage.getItem('sahem_token') || null;
let USER = null;

// ---------- أدوات ----------
async function api(path, opts = {}) {
  const headers = { 'Content-Type': 'application/json' };
  if (TOKEN) headers['Authorization'] = 'Bearer ' + TOKEN;
  const res = await fetch(API + path, { ...opts, headers });
  if (res.status === 401) {
    TOKEN = null;
    localStorage.removeItem('sahem_token');
    if (!opts._silent) toast('انتهت الجلسة — أعد فتح التطبيق من البوت');
    throw new Error('unauth');
  }
  if (!res.ok) {
    const e = await res.json().catch(() => ({}));
    console.error('API error', res.status, e);
    if (e.detail) toast(String(e.detail));
    throw new Error('api');
  }
  return res.json();
}

function toast(msg) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.classList.remove('hidden');
  setTimeout(() => el.classList.add('hidden'), 3500);
}

function fmt(n, d = 2) {
  if (n === null || n === undefined) return '—';
  return Number(n).toLocaleString('en-US', { maximumFractionDigits: d, minimumFractionDigits: d });
}
function pctClass(p) { return p > 0 ? 'up' : (p < 0 ? 'down' : 'flatc'); }

// ---------- المصادقة ----------
async function auth() {
  try {
    const initData = tg?.initData || '';
    if (!initData) {
      // خارج تيليجرام (اختبار المتصفح) — وزير بسيط
      toast('افتح التطبيق من داخل بوت سهم لبدء اللعب 🎮');
      return false;
    }
    const r = await fetch(API + '/api/auth', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ initData }),
    });
    if (!r.ok) throw new Error();
    const d = await r.json();
    TOKEN = d.token;
    localStorage.setItem('sahem_token', TOKEN);
    USER = d.user;
    updateBalance(d.user.coins_balance);
    return true;
  } catch { toast('فشل تسجيل الدخول'); return false; }
}

function updateBalance(v) {
  document.getElementById('balance').textContent = fmt(v) + ' سهم';
}

// ---------- التبويبات ----------
document.querySelectorAll('.tab').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    document.querySelectorAll('.tabview').forEach(s => s.classList.remove('active'));
    document.getElementById('tab-' + btn.dataset.tab).classList.add('active');
    const loaders = {
      markets: loadPrices, arcade: null, predict: loadPredict,
      portfolio: loadPortfolio, leaderboard: loadLeaderboard,
    };
    const fn = loaders[btn.dataset.tab];
    if (fn) fn().catch(() => {});
  });
});

document.querySelectorAll('.chip[data-mkt]').forEach(chip => {
  chip.addEventListener('click', () => {
    document.querySelectorAll('.chip[data-mkt]').forEach(c => c.classList.remove('active'));
    chip.classList.add('active');
    renderPrices(chip.dataset.mkt);
  });
});

// ---------- الأسعار ----------
let PRICES = [];
async function loadPrices() {
  PRICES = await api('/api/prices');
  renderPrices('all');
}

function renderPrices(mkt) {
  const box = document.getElementById('prices-list');
  const items = PRICES.filter(p => mkt === 'all' || p.market === mkt);
  box.innerHTML = items.map(p => {
    const ch = p.change_pct ?? 0;
    return `<div class="card price-row">
      <div><div class="sym-name">${p.name}</div>
      <div class="sym-meta">${p.symbol} • ${p.updated_at?.slice(0, 10) || ''}</div></div>
      <div class="sym-price">${p.price !== null ? fmt(p.price, p.market === 'SA' ? 2 : 2) : 'غير متوفر'}
        <div class="sym-change ${pctClass(ch)}">${ch >= 0 ? '+' : ''}${ch}%</div></div>
      ${p.price !== null ? `
      <div style="display:flex; flex-direction:column; gap:4px">
        <button class="btn primary" style="padding:6px 10px; font-size:0.8em" onclick="quickTrade('${p.symbol}','buy')">شراء</button>
        <button class="btn ghost" style="padding:6px 10px; font-size:0.8em; margin:0" onclick="quickTrade('${p.symbol}','sell')">بيع</button>
      </div>` : ''}
    </div>`;
  }).join('');
}

window.quickTrade = async function (symbol, side) {
  const qty = 1000;
  try {
    const r = await api('/api/trade', { method: 'POST', body: JSON.stringify({ symbol, side, quantity: qty }) });
    toast(r.ok ? (side === 'buy' ? `✅ اشتريت ${qty} بسعر ${fmt(r.price)}` : `✅ بعتت ${qty} بسعر ${fmt(r.price)}`) : r.error);
    if (r.ok) {
      const pf = await api('/api/portfolio');
      updateBalance(pf.balance);
    }
  } catch { }
};

// ---------- التوقّع ----------
async function loadPredict() {
  const prices = await api('/api/prices');
  const byMarket = {};
  prices.filter(p => p.price !== null).forEach(p => (byMarket[p.market] ||= []).push(p));
  const mkName = { SA: '🇸🇦 تداول', US: '🇺🇸 الأمريكي', CRYPTO: '🌐 كريبتو' };
  const box = document.getElementById('predict-list');
  box.innerHTML = '';
  for (const mk of ['SA', 'US', 'CRYPTO']) {
    if (!byMarket[mk]) continue;
    box.innerHTML += `<h3 class="hint">${mkName[mk]}</h3>`;
    for (const p of byMarket[mk].slice(0, 6)) {
      box.innerHTML += `<div class="card">
        <div class="price-row" style="border:none; padding:0 0 8px">
          <b>${p.name}</b>
          <b>${fmt(p.price)}</b>
        </div>
        <div style="display:flex; gap:6px">
          <button class="btn buy" onclick="predict('${p.symbol}','up')">⬆️ صعود</button>
          <button class="btn sell" onclick="predict('${p.symbol}','down')">⬇️ هبوط</button>
          <button class="btn ghost" style="width:auto" onclick="predict('${p.symbol}','flat')">↔️ ثبات</button>
        </div>
      </div>`;
    }
  }
  const mine = await api('/api/predictions');
  const m = document.getElementById('my-predictions');
  m.innerHTML = mine.length ? mine.map(p => `<div class="card">🎯 ${p.symbol} — ${p.direction === 'up' ? '⬆️ صعود' : p.direction === 'down' ? '⬇️ هبوط' : '↔️ ثبات'} <span class="hint">(${p.resolves_at?.slice(0, 16).replace('T', ' ')})</span></div>`).join('') : '<p class="hint">لا توجد توقعات قائمة</p>';
}
window.predict = async function (symbol, direction) {
  try {
    const r = await api('/api/predict', { method: 'POST', body: JSON.stringify({ symbol, direction }) });
    toast(r.ok ? '✅ سُجّلت توقعتك! النتيجة بعد إغلاق السوق' : (r.error || 'فشل'));
    if (r.ok) loadPredict();
  } catch { }
};

// ---------- المحفظة ----------
async function loadPortfolio() {
  const pf = await api('/api/portfolio');
  updateBalance(pf.balance);
  document.getElementById('pf-cash').textContent = fmt(pf.balance) + ' سهم';
  document.getElementById('pf-level').textContent = pf.level;
  document.getElementById('pf-xp').textContent = pf.xp;
  const box = document.getElementById('pf-positions');
  box.innerHTML = pf.positions.length
    ? pf.positions.map(p => `<div class="card price-row">
        <div><div class="sym-name">${p.name}</div>
        <div class="sym-meta">${fmt(p.quantity)} وحدة @ ${fmt(p.avg_cost)}</div></div>
        <div class="sym-price">${fmt(p.market_value)}
        <div class="sym-change ${pctClass(p.pnl_pct)}">${p.pnl_pct >= 0 ? '+' : ''}${p.pnl_pct}%</div></div>
      </div>`).join('')
    : '<p class="hint">محفظتك فارغة — ابدأ الشراء من تبويب الأسعار!</p>';
}

// ---------- الصدارة ----------
async function loadLeaderboard() {
  const rows = await api('/api/leaderboard');
  const medals = ['🥇', '🥈', '🥉'];
  document.getElementById('lb-list').innerHTML = rows.length
    ? rows.map((r, i) => `<div class="card price-row">
        <div><b>${medals[i] || (i + 1) + '.'} ${r.username || 'لاعب'}</b>
        <div class="sym-meta">مستوى ${r.level}</div></div>
        <div class="sym-price">${fmt(r.weekly_value || 0, 0)}
        <div class="sym-change">${r.rounds} جولة</div></div>
      </div>`).join('')
    : '<p class="hint">لوحة الصدارة فاضية — كن أول اللاعبين! 🏆</p>';
}

// ---------- الأركيد ----------
let AR = { timer: null, chart: null, series: null, data: [], round: null };

document.getElementById('arcade-start').addEventListener('click', startArcade);
document.getElementById('arcade-again').addEventListener('click', () => {
  document.getElementById('arcade-result').classList.add('hidden');
  document.getElementById('arcade-intro').classList.remove('hidden');
});
document.getElementById('arcade-finish').addEventListener('click', finishArcade);
document.getElementById('btn-buy').addEventListener('click', () => arTrade('buy'));
document.getElementById('btn-sell').addEventListener('click', () => arTrade('sell'));

async function startArcade() {
  try {
    const rnd = await api('/api/arcade/start', { method: 'POST' });
    AR.round = rnd;
    AR.data = [];
    AR.lastStep = -1;
    document.getElementById('arcade-intro').classList.add('hidden');
    document.getElementById('arcade-result').classList.add('hidden');
    const g = document.getElementById('arcade-game');
    g.classList.remove('hidden');
    document.getElementById('arcade-symbol').textContent = rnd.name;
    initChart();
    AR.timer = setInterval(pollArcadeStep, Math.max(700, rnd.step_seconds * 500));
    pollArcadeStep();
  } catch { }
}

function initChart() {
  if (AR.chart) { AR.chart.remove(); AR.chart = null; }
  const el = document.getElementById('arcade-chart');
  AR.chart = LightweightCharts.createChart(el, {
    width: el.clientWidth, height: 240,
    layout: { background: { color: '#161b22' }, textColor: '#8b949e' },
    grid: { vertLines: { color: '#2d364022' }, horzLines: { color: '#2d364022' } },
    rightPriceScale: { borderColor: '#2d3640' },
    timeScale: { borderColor: '#2d3640' },
    localization: { locale: 'ar' },
  });
  AR.series = AR.chart.addCandlestickSeries({
    upColor: '#2ea043', downColor: '#f85149', borderVisible: false,
    wickUpColor: '#2ea043', wickDownColor: '#f85149',
  });
  AR.volume = AR.chart.addHistogramSeries({ priceScaleId: '', topColor: '#4b8bbe66', bottomColor: '#4b8bbe22' });
  AR.volume.priceScale().applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });
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
      AR.volume.update({ time: c.ts, value: c.volume, color: c.close >= c.open ? '#2ea04366' : '#f8514966' });
      document.getElementById('arcade-date').textContent = `📅 ${c.ts} — اليوم ${s.step + 1}/${s.total_steps}`;
      document.getElementById('arcade-value').textContent = fmt(s.portfolio_value, 0);
      document.getElementById('arcade-cash').textContent = fmt(s.cash, 0);
      document.getElementById('arcade-qty').textContent = fmt(s.holdings, 2);
      if (s.is_last) {
        clearInterval(AR.timer);
        setTimeout(autoFinish, 2500);
      }
    }
  } catch (e) { clearInterval(AR.timer); }
}

async function autoFinish() {
  try {
    const res = await api(`/api/arcade/${AR.round.round_id}/finish`, { method: 'POST' });
    showResult(res);
  } catch { }
}

async function finishArcade() {
  if (!AR.round) return;
  clearInterval(AR.timer);
  await autoFinish();
}

async function arTrade(side) {
  const q = parseFloat(document.getElementById('trade-qty').value) || 0;
  try {
    const r = await api(`/api/arcade/${AR.round.round_id}/trade`, {
      method: 'POST', body: JSON.stringify({ side, quantity: q }),
    });
    if (r.ok) {
      arLog(`${side === 'buy' ? '🟢' : '🔴'} ${side === 'buy' ? 'شراء' : 'بيع'} ${q} @ ${fmt(r.executed_price)}`);
      document.getElementById('trade-qty').value = '';
      const s = await api(`/api/arcade/${AR.round.round_id}/step`);
      document.getElementById('arcade-cash').textContent = fmt(r.cash, 0);
      document.getElementById('arcade-qty').textContent = fmt(r.holdings, 2);
      document.getElementById('arcade-value').textContent = fmt(s.portfolio_value, 0);
    } else {
      toast(r.error);
    }
  } catch { }
}

function arLog(msg) {
  const l = document.getElementById('arcade-log');
  l.innerHTML = `<div>${msg}</div>` + l.innerHTML;
}

function showResult(r) {
  AR.round = null;
  document.getElementById('arcade-game').classList.add('hidden');
  const res = document.getElementById('arcade-result');
  res.classList.remove('hidden');
  document.getElementById('result-rank').textContent = { 'أسطورة 🏆': '🏆 أسطورية!', 'محترف 🥇': '🥇 احتراف!', 'ناجح ✅': '✅ ناجح!', 'متمهل 😐': '😐 ممتِل', 'خاسر 💀': '💀 خسرت' }[r.rank] || r.rank;
  document.getElementById('result-details').innerHTML = `
    <div class="big ${pctClass(r.return_pct)}">${r.return_pct >= 0 ? '+' : ''}${fmt(r.return_pct)}%</div>
    <p>💰 القيمة النهائية: <b>${fmt(r.final_value)}</b> / رأس المال: ${fmt(r.capital, 0)}</p>
    <p>📊 عائد السهم: ${fmt(r.return_pct)}% • السوق: ${fmt(r.benchmark_return_pct)}%</p>
    <p>🎯 <b>العائد الزائد: ${fmt(r.excess_return_pct)}%</b></p>
    <p>🪙 مكافأة الربح: <b class="up">${r.bonus_coins}</b> • XP: <b class="up">${r.points}</b> • الأيام: ${r.days}</p>`;
  refreshBalanceFromServer();
}

async function refreshBalanceFromServer() {
  try {
    const pf = await api('/api/portfolio');
    updateBalance(pf.balance);
  } catch { }
}

// ---------- الإقلاع ----------
(async () => {
  const authed = await auth();
  try {
    await loadPrices();
  } catch { }
})();
