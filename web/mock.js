/* سهم — وضع المعاينة التجريبي (?mock=1)
   يفعّل بيانات تجريبية لعرض التصميم دون تيليجرام — صفرة الخادم الحقيقي لا تتأثر */
(function () {
  if (!new URLSearchParams(location.search).has('mock')) return;

  const prices = {
    '2222.SR': { name: 'أرامكو السعودية', market: 'SA', price: 25.74, change_pct: -0.39 },
    '1120.SR': { name: 'مصرف الراجحي', market: 'SA', price: 62.30, change_pct: -1.42 },
    '2010.SR': { name: 'سابك', market: 'SA', price: 45.80, change_pct: -1.63 },
    '1180.SR': { name: 'بنك الإنماء', market: 'SA', price: 21.10, change_pct: 0.48 },
    '2280.SR': { name: 'المراعي', market: 'SA', price: 54.90, change_pct: 1.21 },
    'AAPL': { name: 'Apple', market: 'US', price: 178.20, change_pct: 0.85 },
    'MSFT': { name: 'Microsoft', market: 'US', price: 415.10, change_pct: -0.32 },
    'NVDA': { name: 'NVIDIA', market: 'US', price: 131.60, change_pct: 2.44 },
    'TSLA': { name: 'Tesla', market: 'US', price: 262.40, change_pct: -1.10 },
    'BTC-USD': { name: 'بيتكوين', market: 'CRYPTO', price: 68240, change_pct: 1.8 },
    'ETH-USD': { name: 'إيثريوم', market: 'CRYPTO', price: 3420, change_pct: -0.9 },
  };

  let holdings = { 'AAPL': 50, 'BTC-USD': 0.35 };
  let cash = 72000;
  let pricesUpdated = prices;
  let arcade = null;
  let duelGame = false;
  let myDuels = [
    {
      id: 5, code: 'QA3K7P', symbol: 'GOOGL', symbol_name: 'Google',
      start_ts: '2022-07-28', end_ts: '2022-09-20', session_len: 30,
      status: 'open', challenger_id: 1, challenger_name: 'لاعب تجريبي',
      opponent_id: null, opponent_name: null,
      challenger_excess: null, opponent_excess: null, winner_id: null,
      expires_at: new Date(Date.now() + 24 * 3600e3).toISOString().slice(0, 19),
    },
    {
      id: 4, code: 'MM2X9B', symbol: 'NVDA', symbol_name: 'NVIDIA',
      start_ts: '2020-06-11', end_ts: '2020-07-21', session_len: 28,
      status: 'active', challenger_id: 9, challenger_name: 'المتحسّب',
      opponent_id: 1, opponent_name: 'لاعب تجريبي',
      challenger_excess: 3.9, opponent_excess: null, winner_id: null,
      expires_at: new Date(Date.now() + 9 * 3600e3).toISOString().slice(0, 19),
    },
    {
      id: 3, code: 'MM2X9B', symbol: 'NVDA', symbol_name: 'NVIDIA',
      start_ts: '2020-06-11', end_ts: '2020-07-21', session_len: 28,
      status: 'finished', challenger_id: 9, challenger_name: 'المتحسّب',
      opponent_id: 1, opponent_name: 'لاعب تجريبي',
      challenger_excess: 4.2, opponent_excess: 11.8, winner_id: 1,
      expires_at: new Date(Date.now() - 3600e3).toISOString().slice(0, 19),
    },
  ];

  function mockArcadeFinish() {
    if (!duelGame) {
      duelGame = false;
      return { final_value: 108300, capital: 100000, return_pct: 8.3, benchmark_return_pct: 2.1, excess_return_pct: 6.2, rank: 'محترف 🥇', points: 220, bonus_coins: 830, days: 34 };
    }
    duelGame = false;
    const d = myDuels[0];
    d.status = 'finished'; d.challenger_excess = 6.2; d.opponent_excess = -1.4; d.winner_id = 1;
    return {
      final_value: 106200, capital: 100000, return_pct: 6.2, benchmark_return_pct: 8.1, excess_return_pct: -1.9,
      rank: 'متمهل 😐', points: 45, bonus_coins: 620, days: 30,
      duel: { state: 'done', message: '🏆 فزت بالمبارزة! +120 نقطة و+5,000 عملة', duel: { ...d } },
    };
  }

  function around(name, market, symbol) {
    const p = pricesUpdated[symbol];
    return { symbol, name: p.name, market: p.market, price: p.price, change_pct: p.change_pct, updated_at: new Date().toISOString() };
  }

  const routes = {
    '/api/auth': { token: 'mock:1', user: { id: 1, username: 'لاعب تجريبي', coins_balance: 72000, level: 3, xp: 1140 } },
    '/api/prices': () => Object.entries(prices).map(([s, p]) => ({ symbol: s, name: p.name, market: p.market, price: p.price, change_pct: p.change_pct, updated_at: new Date().toISOString() })),
    '/api/trade': () => ({ ok: true, price: 99, cash, holdings: 1 }),
    '/api/portfolio': () => ({
      balance: cash, level: 3, xp: 1140,
      daily_streak: 3, pred_streak: 2, daily_claimed_today: false, daily_next_coins: 1000,
      badges: [
        { id: 'first_trade', emoji: '🥇', name: 'أول صفقة', desc: '', earned: true },
        { id: 'first_round', emoji: '🎮', name: 'أول جولة', desc: '', earned: true },
        { id: 'analyst', emoji: '🎯', name: 'قارئ سوق', desc: '', earned: true },
        { id: 'streak5', emoji: '🔥', name: 'سلسلة 5 إصابات', desc: '', earned: false },
        { id: 'daily7', emoji: '📅', name: 'أسبوع حضور', desc: '', earned: false },
        { id: 'legend', emoji: '🏆', name: 'أسطورة جولة', desc: '', earned: false },
        { id: 'duelist', emoji: '⚔️', name: 'فاتح مبارزات', desc: '', earned: true },
        { id: 'league_champ', emoji: '👑', name: 'بطل الدوري', desc: '', earned: false },
      ],
      positions: Object.entries(holdings).filter(([, q]) => q > 0).map(([s, q]) => {
        const p = pricesUpdated[s];
        return { symbol: s, name: p.name, market: p.market, quantity: q, avg_cost: p.price * 0.94, current_price: p.price, market_value: q * p.price, pnl_pct: (1 / 0.94 - 1) * 100 };
      }),
    }),
    '/api/predictions': () => [{
      id: 9, symbol: 'NVDA', direction: 'up', result: 'pending',
      resolves_at: new Date(Date.now() + 5 * 3600e3).toISOString(), points: 0,
    }],
    '/api/predict': { ok: true },
    '/api/predictions/history': () => [
      { symbol: 'AAPL', direction: 'up', result: 'win', points: 2.2, resolve_price: 180, entry_price: 176 },
      { symbol: 'BTC-USD', direction: 'flat', result: 'lose', points: 0, resolve_price: 69000, entry_price: 68240 },
    ],
    '/api/daily': () => ({ ok: true, coins: 750, streak: 3 }),
    '/api/leaderboard': [
      { user_id: 9, username: 'أبو سهم', score: 41.2, weekly_value: 41.2, rounds: 12, pred_wins: 5, champion: true },
      { user_id: 3, username: 'المضارب', score: 32.6, weekly_value: 32.6, rounds: 9, pred_wins: 2, champion: false },
      { user_id: 4, username: 'متداول مبتدئ', score: 22.1, weekly_value: 22.1, rounds: 6, pred_wins: 1, champion: false },
      { user_id: 5, username: 'قنديل', score: 15.4, weekly_value: 15.4, rounds: 4, pred_wins: 0, champion: false },
      { user_id: 1, username: 'لاعب تجريبي', score: 9.8, weekly_value: 9.8, rounds: 3, pred_wins: 1, champion: false },
    ],
    '/api/quests': () => ({
      daily: [
        { key: 'round_today', emoji: '🎮', title: 'أنهِ جولة أركيد اليوم', target: 1, current: 0, done: false, reward: 400 },
        { key: 'preds_today', emoji: '🎯', title: 'ضع توقّعين اليوم', target: 2, current: 1, done: false, reward: 400 },
        { key: 'daily_claimed', emoji: '🎁', title: 'استلم مكافأة الحضور', target: 1, current: 1, done: true, reward: 300 },
      ],
      weekly: [
        { key: 'rounds_week', emoji: '📈', title: 'أنهِ 5 جولات أركيد', target: 5, current: 3, done: false, reward: 2000 },
        { key: 'wins_week', emoji: '✅', title: '3 توقعات صحيحة', target: 3, current: 3, done: true, reward: 2000 },
        { key: 'duel_win_week', emoji: '⚔️', title: 'فُز بمبارزة', target: 1, current: 0, done: false, reward: 1500 },
      ],
    }),
    '/api/arcade/active': () => null,
    '/api/arcade/id/resume': () => {
      if (!arcade) return {};
      const hist = Array.from({ length: Math.max(1, arcade.step) }, (_, i) => ({
        ts: '2021-03-0' + ((i % 9) + 1), open: arcade.price * 0.98, close: arcade.price,
        high: arcade.price * 1.01, low: arcade.price * 0.97, volume: 2e6,
      }));
      return { round: { round_id: arcade.round_id, symbol: arcade.symbol, name: arcade.name, capital: 100000, session_len: 40, step_seconds: 4, start_ts: '2021-03-02', kind: 'solo' },
        history: hist, step: hist.length - 1, cash: arcade.cash, holdings: arcade.holdings, avg_cost: arcade.avg };
    },
    '/api/arcade/start': () => {
      const sym = 'NVDA', price = 95;
      arcade = { round_id: 77, symbol: sym, name: 'NVIDIA', capital: 100000, step_seconds: 4, started: Date.now(), cash: 100000, holdings: 0, avg: 0, step: 0, price };
      return { round_id: arcade.round_id, symbol: sym, name: arcade.name, capital: 100000, session_len: 40, step_seconds: 4, start_ts: '2021-03-02' };
    },
    '/api/arcade/id/step': () => {
      if (!arcade) return {};
      const price = arcade.price * (1 + (Math.random() - 0.48) * 0.018);
      const candle = {
        ts: '2021-03-1' + (1 + arcade.step % 9), open: arcade.price, close: price,
        high: Math.max(arcade.price, price) * 1.006, low: Math.min(arcade.price, price) * 0.994,
        volume: Math.round(2e6 + Math.random() * 8e5),
      };
      return { round_id: arcade.round_id, step: arcade.step, total_steps: 40, candle, cash: arcade.cash, holdings: arcade.holdings, portfolio_value: arcade.cash + arcade.holdings * price, is_last: arcade.step >= 39 };
    },
    '/api/arcade/id/trade': () => ({ ok: true, cash: arcade.cash, holdings: arcade.holdings, avg_cost: arcade.avg, executed_price: arcade.price }),
    '/api/arcade/id/finish': () => mockArcadeFinish(),

    /* ─── المبارزات (المرحلة 2) ─── */
    '/api/duels/join': () => {
      const d = myDuels.find(x => x.status === 'open');
      if (d) { d.status = 'active'; d.opponent_name = 'المتحسّب'; d.opponent_id = 7; }
      return { ok: true, duel: d || { error: 'لا تحديات' } };
    },
    '/api/duels/play': () => {
      const sym = 'GOOGL';
      arcade = { round_id: 88, symbol: sym, name: 'Google', capital: 100000, step_seconds: 4, started: Date.now(), cash: 100000, holdings: 0, avg: 0, step: 0, price: 113 };
      duelGame = true;
      return { ok: true, round: { round_id: arcade.round_id, symbol: sym, name: 'Google', capital: 100000, session_len: 30, step_seconds: 4, start_ts: '2022-07-28', kind: 'duel', duel_id: 5 } };
    },
    '/api/duels': () => myDuels,

    /* ─── الدوري الأسبوعي ─── */
    '/api/league': () => ({
      period_start: '2026-10-02T00:00:00+03:00', period_end: '2026-10-09T00:00:00+03:00',
      countdown: '3 أيام و 5 ساعات',
      players: 14,
      standings: [
        { user_id: 9, rank: 1, username: 'المضارب', excess_sum: 24.5, rounds: 8, pred_wins: 4, score: 32.5 },
        { user_id: 1, rank: 2, username: 'لاعب تجريبي', excess_sum: 18.2, rounds: 6, pred_wins: 2, score: 22.2 },
        { user_id: 8, rank: 3, username: 'الصاعد', excess_sum: 9.7, rounds: 5, pred_wins: 1, score: 11.7 },
        { user_id: 7, rank: 4, username: 'قنديل', excess_sum: 4.2, rounds: 3, pred_wins: 0, score: 4.2 },
      ],
      me: { rank: 2, score: 22.2, rounds: 6, pred_wins: 2, gap_text: 'فجوة +10.3 نقطة عن «المضارب»' },
      champion: { username: 'أبو سهم', score: 41.8 },
      prizes: [
        { rank: 1, coins: 50000, xp: 500 }, { rank: 2, coins: 30000, xp: 300 },
        { rank: 3, coins: 20000, xp: 200 }, { rank: '4-10', coins: 10000, xp: 100 },
      ],
      rules: 'عائدك الزائد + 2 لكل توقّع صحيح • 3 جولات على الأقل لجائزة',
    }),
  };

  const realFetch = window.fetch.bind(window);
  window.fetch = async function (url, opts = {}) {
    let path = String(url).replace(/^https?:\/\/[^/]+/, '');
    // توحيد مسارات الأركيد الديناميكية: /api/arcade/<id>/step → /api/arcade/id/step
    path = path.replace(/\/api\/arcade\/\d+\//, '/api/arcade/id/');
    path = path.replace(/\/api\/duels\/\d+\/play/, '/api/duels/play');
    const key = Object.keys(routes).find(k => path === k || path.startsWith(k + '/') || path.startsWith(k + '?'));
    if (!key) return realFetch(url, opts);
    await new Promise(r => setTimeout(r, 350)); // إحساس شبكة واقعي
    const R = routes[key];
    let data = typeof R === 'function' ? R() : R;
    // مسارات أركيد الديناميكية
    if (path.endsWith('/step')) { arcade.step = Math.min(arcade.step + 1, 39); }
    if (path.endsWith('/trade')) {
      const side = JSON.parse((opts.body || '{}')).side;
      const q = JSON.parse((opts.body || '{}')).quantity || 0;
      if (side === 'buy') { const c = arcade.price * q * 1.001; arcade.cash -= c; arcade.holdings += q; arcade.avg = arcade.holdings ? arcade.price : 0; }
      else { arcade.cash += arcade.price * q * 0.999; arcade.holdings -= q; if (arcade.holdings < 0.001) arcade.holdings = 0; }
      data = { ok: true, cash: arcade.cash, holdings: arcade.holdings, avg_cost: arcade.avg, executed_price: arcade.price };
    }
    if (key === '/api/trade') {
      const b = JSON.parse((opts.body || '{}'));
      pricesUpdated[b.symbol] = pricesUpdated[b.symbol];
      if (b.side === 'buy') { const p = pricesUpdated[b.symbol].price; cash -= p * b.quantity * 1.001; }
      else if (holdings[b.symbol]) { const p = pricesUpdated[b.symbol].price; cash += p * Math.min(b.quantity, holdings[b.symbol]) * 0.999; }
      return { ok: true, price: pricesUpdated[b.symbol].price };
    }
    // إنشاء تحدي (POST /api/duels) — غير قائمة العرض
    if (key === '/api/duels' && (opts.method || 'GET') === 'POST') {
      const d = {
        id: 90 + myDuels.length, code: 'N7' + Math.floor(1000 + Math.random() * 8999) + 'P',
        symbol: 'TSLA', symbol_name: 'Tesla', start_ts: '2021-11-08', end_ts: '2021-12-21',
        session_len: 32, status: 'open', challenger_id: 1, challenger_name: 'لاعب تجريبي',
        opponent_id: null, opponent_name: null, challenger_excess: null, opponent_excess: null,
        winner_id: null, expires_at: new Date(Date.now() + 24 * 3600e3).toISOString().slice(0, 19),
      };
      myDuels = [d, ...myDuels];
      return new Response(JSON.stringify({ ok: true, duel: d }), { status: 200, headers: { 'Content-Type': 'application/json' } });
    }
    return new Response(JSON.stringify(data), { status: 200, headers: { 'Content-Type': 'application/json' } });
  };
})();
