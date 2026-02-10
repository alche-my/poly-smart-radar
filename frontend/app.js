const API_BASE = window.location.origin + '/api';

// Telegram WebApp integration
const tg = window.Telegram && window.Telegram.WebApp;
if (tg) {
    tg.ready();
    tg.expand();
}

// --- Strategy filter constants (must match config.py) ---
const STRATEGY_MIN_PRICE = 0.10;
const STRATEGY_MAX_PRICE = 0.85;
const STRATEGY_BAD_CATEGORIES = new Set(['CRYPTO', 'CULTURE', 'FINANCE']);
const STRATEGY_MAX_TIER = 2;

// --- State ---
let currentTab = 'signals';
let signalsCache = [];

// --- DOM helpers ---
function $(sel) { return document.querySelector(sel); }
function $$(sel) { return document.querySelectorAll(sel); }
function show(el) { el.classList.remove('hidden'); }
function hide(el) { el.classList.add('hidden'); }

// --- API ---
async function apiFetch(path) {
    const resp = await fetch(API_BASE + path);
    if (!resp.ok) throw new Error(`API ${resp.status}: ${resp.statusText}`);
    return resp.json();
}

// Safe render helper — one bad item won't kill the whole list
function safeMap(arr, renderFn) {
    return arr.map(item => {
        try {
            if (!item || typeof item !== 'object') return '';
            return renderFn(item);
        } catch (e) {
            console.error('Render error:', e, item);
            return '';
        }
    }).join('');
}

// --- Tabs ---
$$('.tab').forEach(btn => {
    btn.addEventListener('click', () => {
        $$('.tab').forEach(b => b.classList.remove('active'));
        $$('.tab-content').forEach(c => c.classList.remove('active'));
        btn.classList.add('active');
        const tab = btn.dataset.tab;
        $(`#${tab}-tab`).classList.add('active');
        currentTab = tab;
        // Reset signal detail view when switching tabs
        if (tab === 'signals') {
            hide($('#signal-detail-view'));
            show($('#signals-list-view'));
        }
        loadTab(tab);
    });
});

// --- Load tab data ---
async function loadTab(tab) {
    hide($('#error-banner'));
    show($('#loading'));
    try {
        if (tab === 'signals') await loadSignals();
        else if (tab === 'traders') await loadTraders();
        else if (tab === 'dashboard') await loadDashboard();
    } catch (err) {
        console.error('loadTab error:', err);
        showError(err.message);
    } finally {
        hide($('#loading'));
    }
}

function showError(msg) {
    const el = $('#error-banner');
    el.textContent = msg;
    show(el);
}

// =====================
// HELPER FUNCTIONS
// =====================

function passesStrategyFilter(s) {
    const tier = s.tier || 3;
    if (tier > STRATEGY_MAX_TIER) return false;
    const price = s.current_price != null ? Number(s.current_price) : null;
    if (price != null && (price < STRATEGY_MIN_PRICE || price > STRATEGY_MAX_PRICE)) return false;
    const cat = (s.market_category || '').toUpperCase();
    if (cat && STRATEGY_BAD_CATEGORIES.has(cat)) return false;
    return true;
}

function getAvgConviction(traders) {
    if (!Array.isArray(traders) || traders.length === 0) return 0;
    const sum = traders.reduce((acc, t) => acc + Number(t.conviction || 1), 0);
    return sum / traders.length;
}

function getTopTrader(traders) {
    if (!Array.isArray(traders) || traders.length === 0) return null;
    return traders.reduce((best, t) =>
        Number(t.trader_score || 0) > Number(best.trader_score || 0) ? t : best
    , traders[0]);
}

function generateSignalSummary(s) {
    const traders = Array.isArray(s.traders_involved) ? s.traders_involved : [];
    const count = traders.length;
    if (count === 0) return '';

    const dir = (s.direction || '?').toUpperCase();
    const avgConv = getAvgConviction(traders).toFixed(1);
    const top = getTopTrader(traders);
    const topName = top ? escapeHtml(top.username || (top.wallet_address || '').slice(0, 10)) : '?';
    const topScore = Number(top?.trader_score || 0).toFixed(1);
    const topWr = top?.win_rate != null ? (Number(top.win_rate) * 100).toFixed(0) + '%' : '?';
    const topRoi = top?.roi != null ? (Number(top.roi) >= 0 ? '+' : '') + (Number(top.roi) * 100).toFixed(0) + '%' : '?';

    let line1 = `<strong>${count} trader${count > 1 ? 's' : ''}</strong> entered <strong>${dir}</strong> with avg conviction <strong>${avgConv}x</strong>.`;
    let line2 = `Top: <strong>${topName}</strong> (score ${topScore}, WR ${topWr}, ROI ${topRoi})`;
    return `${line1}<br>${line2}`;
}

function renderPriceBar(entry, market) {
    const entryPct = Math.max(0, Math.min(100, (entry || 0) * 100));
    const marketPct = Math.max(0, Math.min(100, (market || 0) * 100));
    const minPct = Math.min(entryPct, marketPct);
    const maxPct = Math.max(entryPct, marketPct);

    return `
        <div class="price-bar-container">
            <div class="price-bar-track">
                <div class="price-bar-fill" style="left:${minPct}%;width:${maxPct - minPct}%;background:var(--accent-blue)"></div>
            </div>
            <div class="price-bar-marker" style="left:${entryPct}%;background:var(--accent-yellow)"></div>
            <div class="price-bar-label" style="left:${entryPct}%;color:var(--accent-yellow)">entry</div>
            ${market != null ? `
                <div class="price-bar-marker" style="left:${marketPct}%;background:var(--accent-green)"></div>
                <div class="price-bar-label" style="left:${marketPct}%;color:var(--accent-green)">market</div>
            ` : ''}
            <div class="price-bar-ends"><span>$0</span><span>$1</span></div>
        </div>
    `;
}

function renderConvictionBar(conviction) {
    const conv = Number(conviction || 1);
    // Cap visual at 3x (100% width)
    const pct = Math.min(100, (conv / 3) * 100);
    const levelClass = conv >= 2.5 ? 'conviction-extreme' : conv >= 1.5 ? 'conviction-high' : '';
    return `
        <div class="conviction-row ${levelClass}">
            <span>Conviction</span>
            <div class="conviction-bar-track">
                <div class="conviction-bar-fill" style="width:${pct}%"></div>
            </div>
            <span class="conviction-value">${conv.toFixed(1)}x</span>
        </div>
    `;
}

function formatTimeAgo(isoStr) {
    if (!isoStr) return '';
    const diff = Date.now() - new Date(isoStr).getTime();
    const mins = Math.floor(diff / 60000);
    if (mins < 1) return 'just now';
    if (mins < 60) return `${mins}m ago`;
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return `${hrs}h ago`;
    const days = Math.floor(hrs / 24);
    return `${days}d ago`;
}

function escapeHtml(str) {
    const d = document.createElement('div');
    d.textContent = str;
    return d.innerHTML;
}

// =====================
// SIGNALS LIST
// =====================

async function loadSignals() {
    // Ensure list view is shown
    hide($('#signal-detail-view'));
    show($('#signals-list-view'));

    const tier = $('#tier-filter').value;
    const status = $('#status-filter').value;
    let url = '/signals?limit=50';
    if (tier) url += `&tier=${tier}`;
    if (status) url += `&status=${status}`;

    const data = await apiFetch(url);
    const list = $('#signals-list');
    const empty = $('#signals-empty');

    if (!data.signals || data.signals.length === 0) {
        list.innerHTML = '';
        signalsCache = [];
        show(empty);
        return;
    }

    hide(empty);
    signalsCache = data.signals;
    list.innerHTML = safeMap(data.signals, renderSignalCard);

    // Attach click handlers
    list.querySelectorAll('.signal-card').forEach((card, i) => {
        card.addEventListener('click', (e) => {
            // Don't navigate if clicking a link
            if (e.target.closest('a')) return;
            openSignalDetail(signalsCache[i]);
        });
    });
}

function renderSignalCard(s) {
    const tier = s.tier || 3;
    const tierLabel = `T${tier}`;
    const status = s.status || 'ACTIVE';
    const statusClass = `status-${status.toLowerCase()}`;
    const dirClass = (s.direction || '').toUpperCase() === 'YES' ? 'direction-yes' : 'direction-no';
    const dirLabel = (s.direction || '?').toUpperCase();
    const traders = Array.isArray(s.traders_involved) ? s.traders_involved : [];
    const tradersCount = traders.length;
    const timeAgo = formatTimeAgo(s.created_at);
    const price = s.current_price != null ? `$${Number(s.current_price).toFixed(2)}` : '';
    const category = (s.market_category || '').toUpperCase();
    const isStrategy = passesStrategyFilter(s);
    const avgConv = getAvgConviction(traders);

    // P&L badge for resolved signals
    let pnlHtml = '';
    if (status === 'RESOLVED' && s.pnl_percent != null) {
        const pnl = Number(s.pnl_percent) * 100;
        const pnlClass = pnl >= 0 ? 'pnl-positive' : 'pnl-negative';
        pnlHtml = `<span class="pnl-badge ${pnlClass}">${pnl >= 0 ? '+' : ''}${pnl.toFixed(0)}%</span>`;
    }

    return `
        <div class="card signal-card tier-border-${tier} ${isStrategy ? '' : 'non-strategy'}" role="button">
            <div class="identity-strip">
                <span class="tier-badge tier-${tier}">${tierLabel}</span>
                ${category ? `<span class="category-badge">${category}</span>` : ''}
                ${!isStrategy ? '<span class="non-strategy-label">non-strategy</span>' : ''}
                ${pnlHtml}
                <div class="identity-right">
                    <span class="status-badge ${statusClass}">${status}</span>
                    <span class="time-ago">${timeAgo}</span>
                </div>
            </div>
            <div class="market-title">${escapeHtml(s.market_title || 'Unknown market')}</div>
            <div class="action-strip">
                <span class="direction-price direction ${dirClass}">${dirLabel} ${price}</span>
                <span class="separator">|</span>
                <span>${tradersCount} trader${tradersCount !== 1 ? 's' : ''}</span>
                ${avgConv > 0 ? `<span class="separator">|</span><span>conv ${avgConv.toFixed(1)}x</span>` : ''}
            </div>
        </div>
    `;
}

// =====================
// SIGNAL DETAIL
// =====================

function openSignalDetail(s) {
    hide($('#signals-list-view'));
    show($('#signal-detail-view'));

    const tier = s.tier || 3;
    const status = s.status || 'ACTIVE';
    const statusClass = `status-${status.toLowerCase()}`;
    const dirClass = (s.direction || '').toUpperCase() === 'YES' ? 'direction-yes' : 'direction-no';
    const dirLabel = (s.direction || '?').toUpperCase();
    const entryPrice = s.current_price != null ? Number(s.current_price) : null;
    const marketPrice = s.market_price_at_signal != null ? Number(s.market_price_at_signal) : null;
    const traders = Array.isArray(s.traders_involved) ? s.traders_involved : [];
    const slug = s.market_slug || '';
    const eventSlug = s.event_slug || slug;
    const peakScore = Number(s.peak_score || s.signal_score || 0);
    const currentScore = Number(s.signal_score || 0);
    const timeAgo = formatTimeAgo(s.created_at);
    const updatedAgo = formatTimeAgo(s.updated_at);
    const category = (s.market_category || '').toUpperCase();
    const isStrategy = passesStrategyFilter(s);

    // Section A: Identity strip
    const identityHtml = `
        <div class="identity-strip">
            <span class="tier-badge tier-${tier}">T${tier}</span>
            ${category ? `<span class="category-badge">${category}</span>` : ''}
            ${!isStrategy ? '<span class="non-strategy-label">non-strategy</span>' : ''}
            <div class="identity-right">
                <span class="status-badge ${statusClass}">${status}</span>
            </div>
        </div>
    `;

    // Section B: Price Action Block
    let spreadHtml = '';
    if (entryPrice != null && marketPrice != null && entryPrice > 0) {
        const spread = ((marketPrice - entryPrice) / entryPrice) * 100;
        const spreadClass = spread >= 0 ? 'spread-positive' : 'spread-negative';
        spreadHtml = `
            <div class="spread-row">
                Spread since signal: <span class="spread-value ${spreadClass}">${spread >= 0 ? '+' : ''}${spread.toFixed(1)}%</span>
            </div>
        `;
    }

    const priceBlockHtml = `
        <div class="price-action-block">
            <div class="direction-label direction ${dirClass}">${dirLabel}</div>
            <div class="prices-row">
                <div class="price-item">
                    <div class="price-label">Entry price</div>
                    <div class="price-value">${entryPrice != null ? '$' + entryPrice.toFixed(2) : '—'}</div>
                </div>
                <div class="price-item">
                    <div class="price-label">Market price</div>
                    <div class="price-value">${marketPrice != null ? '$' + marketPrice.toFixed(2) : '—'}</div>
                </div>
            </div>
            ${spreadHtml}
            ${entryPrice != null ? renderPriceBar(entryPrice, marketPrice) : ''}
        </div>
    `;

    // Section C: Signal Summary
    const summaryText = generateSignalSummary(s);
    const summaryHtml = summaryText ? `<div class="signal-summary">${summaryText}</div>` : '';

    // Section D: Traders
    let tradersHtml = '';
    if (traders.length > 0) {
        tradersHtml = `
            <div class="detail-section">
                <div class="detail-section-title">Traders (${traders.length})</div>
                ${safeMap(traders, t => renderTraderInSignal(t, s))}
            </div>
        `;
    }

    // Section E: Collapsible metadata
    let metaRows = '';
    metaRows += `
        <div class="detail-row">
            <span class="detail-label">Signal score</span>
            <span>${currentScore.toFixed(1)}</span>
        </div>
    `;
    if (peakScore !== currentScore) {
        metaRows += `
            <div class="detail-row">
                <span class="detail-label">Peak score</span>
                <span>${peakScore.toFixed(1)}</span>
            </div>
        `;
    }
    if (status === 'RESOLVED' && s.resolution_outcome) {
        metaRows += `
            <div class="detail-row">
                <span class="detail-label">Resolution</span>
                <span class="resolution-badge">${s.resolution_outcome}</span>
            </div>
        `;
    }
    if (status === 'RESOLVED' && s.pnl_percent != null) {
        const pnlVal = Number(s.pnl_percent) * 100;
        metaRows += `
            <div class="detail-row">
                <span class="detail-label">P&L</span>
                <span class="pnl-badge ${pnlVal >= 0 ? 'pnl-positive' : 'pnl-negative'}">${pnlVal >= 0 ? '+' : ''}${pnlVal.toFixed(1)}%</span>
            </div>
        `;
    }
    metaRows += `
        <div class="detail-row">
            <span class="detail-label">Strategy signal</span>
            <span>${isStrategy ? 'Yes' : 'No'}</span>
        </div>
    `;

    const metaHtml = `
        <details class="meta-collapsible">
            <summary>Details</summary>
            ${metaRows}
        </details>
    `;

    // Section F: Polymarket link
    const polymarketUrl = eventSlug
        ? `https://polymarket.com/event/${eventSlug}`
        : '';
    const polyBtnHtml = polymarketUrl ? `
        <a class="polymarket-btn" href="${polymarketUrl}" target="_blank">
            Open on Polymarket &rarr;
        </a>
    ` : '';

    $('#signal-detail-content').innerHTML = `
        <div class="card detail-card">
            ${identityHtml}
            <div class="market-title">${escapeHtml(s.market_title || 'Unknown market')}</div>
            <div class="detail-timestamps">
                Created ${timeAgo}${s.updated_at ? ` · Updated ${updatedAgo}` : ''}
            </div>
            ${priceBlockHtml}
            ${summaryHtml}
            ${tradersHtml}
            ${metaHtml}
            ${polyBtnHtml}
        </div>
    `;
}

// =====================
// TRADER IN SIGNAL DETAIL
// =====================

function renderTraderInSignal(t, signal) {
    const name = t.username || (t.wallet_address ? t.wallet_address.slice(0, 10) + '...' : '?');
    const score = Number(t.trader_score || 0).toFixed(1);
    const wr = t.win_rate != null ? (t.win_rate * 100).toFixed(0) + '%' : '?';
    const roi = t.roi != null ? (Number(t.roi) * 100).toFixed(1) : '?';
    const roiNum = t.roi != null ? Number(t.roi) : 0;
    const roiClass = roiNum >= 0 ? 'positive' : 'negative';
    const totalClosed = t.total_closed || 0;
    const changeType = t.change_type || '?';
    const changeClass = `change-${changeType.toLowerCase()}`;
    const size = t.size != null ? `$${Number(t.size).toFixed(0)}` : '?';
    const conviction = Number(t.conviction || 1);
    const ago = formatTimeAgo(t.detected_at);
    const profileUrl = t.wallet_address
        ? `https://polymarket.com/profile/${t.wallet_address}`
        : '';

    // Direction from signal
    const dir = signal ? (signal.direction || '?').toUpperCase() : '?';

    // Entry price per trader (use signal entry price as fallback)
    const traderEntryPrice = t.entry_price != null
        ? `$${Number(t.entry_price).toFixed(2)}`
        : (signal && signal.current_price != null ? `$${Number(signal.current_price).toFixed(2)}` : '?');

    // Category experience badges
    const catScores = t.category_scores || {};
    const catBadges = Object.entries(catScores)
        .filter(([, wr]) => wr > 0)
        .sort((a, b) => b[1] - a[1])
        .slice(0, 3)
        .map(([cat, wr]) => `<span class="cat-badge">${escapeHtml(cat)} ${(wr * 100).toFixed(0)}%</span>`)
        .join('');

    return `
        <div class="trader-in-signal">
            <div class="trader-header">
                ${profileUrl
                    ? `<a class="trader-name trader-link" href="${profileUrl}" target="_blank">${escapeHtml(name)}</a>`
                    : `<span class="trader-name">${escapeHtml(name)}</span>`
                }
                <div class="trader-header-right">
                    <span class="change-badge ${changeClass}">${changeType}</span>
                    <span>${ago}</span>
                </div>
            </div>
            <div class="trader-stats-row">
                <span>Score: <b>${score}</b></span>
                <span>WR: <b>${wr}</b></span>
                <span>ROI: <b class="${roiClass}">${roi}%</b></span>
                <span>Closed: <b>${totalClosed}</b></span>
            </div>
            <div class="trader-position">
                Position: <b>${size}</b> ${dir} @ <b>${traderEntryPrice}</b>
            </div>
            ${renderConvictionBar(conviction)}
            ${catBadges ? `<div class="trader-categories">${catBadges}</div>` : ''}
            ${profileUrl ? `
                <div class="trader-footer">
                    <a class="profile-link" href="${profileUrl}" target="_blank">Profile &rarr;</a>
                </div>
            ` : ''}
        </div>
    `;
}

// Signal detail back button
$('#signal-back-btn').addEventListener('click', () => {
    hide($('#signal-detail-view'));
    show($('#signals-list-view'));
});

// =====================
// TRADERS LIST
// =====================

async function loadTraders() {
    const data = await apiFetch('/traders?limit=50');
    const list = $('#traders-list');
    const empty = $('#traders-empty');

    if (!data.traders || data.traders.length === 0) {
        list.innerHTML = '';
        show(empty);
        return;
    }

    hide(empty);
    list.innerHTML = safeMap(data.traders, renderTraderCard);
}

function renderTraderCard(t) {
    const name = t.username || (t.wallet_address ? t.wallet_address.slice(0, 10) + '...' : 'Unknown');
    const score = Number(t.trader_score || 0);
    const wr = t.win_rate != null ? (Number(t.win_rate) * 100).toFixed(0) : '?';
    const roi = t.roi != null ? (Number(t.roi) * 100).toFixed(1) : '?';
    const roiNum = t.roi != null ? Number(t.roi) : 0;
    const roiClass = roiNum >= 0 ? 'positive' : 'negative';
    const closed = t.total_closed || 0;
    const avgSize = t.avg_position_size != null ? `$${Number(t.avg_position_size).toFixed(0)}` : '?';

    return `
        <div class="card trader-card">
            <div class="header">
                <span class="name">${escapeHtml(name)}</span>
                <span class="score">${score.toFixed(1)}</span>
            </div>
            <div class="stats">
                <span>WR: <span class="stat-value">${wr}%</span></span>
                <span>ROI: <span class="stat-value ${roiClass}">${roi}%</span></span>
                <span>Avg: <span class="stat-value">${avgSize}</span></span>
            </div>
            <div class="stats">
                <span>Closed: <span class="stat-value">${closed}</span></span>
            </div>
        </div>
    `;
}

// =====================
// DASHBOARD
// =====================

async function loadDashboard() {
    const data = await apiFetch('/dashboard');
    const el = $('#dashboard-content');

    el.innerHTML = `
        <div class="stat-grid">
            <div class="stat-box">
                <div class="value">${data.traders_count || 0}</div>
                <div class="label">Traders</div>
            </div>
            <div class="stat-box">
                <div class="value">${data.active_signals || 0}</div>
                <div class="label">Active Signals</div>
            </div>
            <div class="stat-box">
                <div class="value">${data.total_signals || 0}</div>
                <div class="label">Total Signals</div>
            </div>
            <div class="stat-box">
                <div class="value">${data.recent_changes_24h || 0}</div>
                <div class="label">Changes (24h)</div>
            </div>
        </div>
        <h3>Top Active Signals</h3>
        ${safeMap(data.top_signals || [], renderSignalCard) || '<div class="empty-state">No active signals</div>'}
    `;
}

// --- Filter listeners ---
$('#tier-filter').addEventListener('change', () => loadSignals());
$('#status-filter').addEventListener('change', () => loadSignals());

// --- Init ---
loadTab('signals');
