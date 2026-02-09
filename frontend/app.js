const API_BASE = window.location.origin + '/api';

// Telegram WebApp integration
const tg = window.Telegram && window.Telegram.WebApp;
if (tg) {
    tg.ready();
    tg.expand();
}

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

// --- Signals ---
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
    const tierClass = `tier-${s.tier || 3}`;
    const tierLabel = `Tier ${s.tier || '?'}`;
    const status = s.status || 'ACTIVE';
    const statusClass = `status-${status.toLowerCase()}`;
    const dirClass = (s.direction || '').toUpperCase() === 'YES' ? 'direction-yes' : 'direction-no';
    const traders = Array.isArray(s.traders_involved) ? s.traders_involved : [];
    const tradersCount = traders.length;
    const timeAgo = formatTimeAgo(s.created_at);
    const price = s.current_price != null ? `$${Number(s.current_price).toFixed(2)}` : '';

    return `
        <div class="card signal-card" role="button">
            <div class="header">
                <div class="header-left">
                    <span class="tier-badge ${tierClass}">${tierLabel}</span>
                    <span class="status-badge ${statusClass}">${status}</span>
                </div>
                <span class="score">Score: ${Number(s.signal_score || 0).toFixed(1)}</span>
            </div>
            <div class="market-title">${escapeHtml(s.market_title || 'Unknown market')}</div>
            <div class="meta">
                <span class="direction ${dirClass}">${(s.direction || '?').toUpperCase()} @ ${price}</span>
                <span>${tradersCount > 0 ? tradersCount + ' traders' : ''} ${timeAgo}</span>
            </div>
        </div>
    `;
}

// --- Signal Detail ---
function openSignalDetail(s) {
    hide($('#signals-list-view'));
    show($('#signal-detail-view'));

    const tierClass = `tier-${s.tier || 3}`;
    const status = s.status || 'ACTIVE';
    const statusClass = `status-${status.toLowerCase()}`;
    const dirClass = (s.direction || '').toUpperCase() === 'YES' ? 'direction-yes' : 'direction-no';
    const price = s.current_price != null ? `$${Number(s.current_price).toFixed(2)}` : '';
    const traders = Array.isArray(s.traders_involved) ? s.traders_involved : [];
    const slug = s.market_slug || '';
    const eventSlug = s.event_slug || slug;
    const peakScore = Number(s.peak_score || s.signal_score || 0);
    const currentScore = Number(s.signal_score || 0);
    const timeAgo = formatTimeAgo(s.created_at);
    const updatedAgo = formatTimeAgo(s.updated_at);

    let tradersHtml = '';
    if (traders.length > 0) {
        tradersHtml = `
            <div class="detail-section">
                <div class="detail-section-title">Traders (${traders.length})</div>
                ${safeMap(traders, renderTraderInSignal)}
            </div>
        `;
    }

    const polymarketUrl = eventSlug
        ? `https://polymarket.com/event/${eventSlug}`
        : '';

    $('#signal-detail-content').innerHTML = `
        <div class="card detail-card">
            <div class="header">
                <div class="header-left">
                    <span class="tier-badge ${tierClass}">Tier ${s.tier || '?'}</span>
                    <span class="status-badge ${statusClass}">${status}</span>
                </div>
                <span class="score">Score: ${currentScore.toFixed(1)}</span>
            </div>
            <div class="market-title">${escapeHtml(s.market_title || 'Unknown market')}</div>
            <div class="detail-meta">
                <div class="detail-row">
                    <span class="detail-label">Direction</span>
                    <span class="direction ${dirClass}">${(s.direction || '?').toUpperCase()} @ ${price}</span>
                </div>
                ${peakScore !== currentScore ? `
                <div class="detail-row">
                    <span class="detail-label">Peak score</span>
                    <span>${peakScore.toFixed(1)}</span>
                </div>` : ''}
                <div class="detail-row">
                    <span class="detail-label">Created</span>
                    <span>${timeAgo}</span>
                </div>
                ${s.updated_at ? `
                <div class="detail-row">
                    <span class="detail-label">Updated</span>
                    <span>${updatedAgo}</span>
                </div>` : ''}
            </div>

            ${tradersHtml}

            ${polymarketUrl ? `
            <a class="polymarket-btn" href="${polymarketUrl}" target="_blank">
                Open on Polymarket &rarr;
            </a>` : ''}
        </div>
    `;
}

function renderTraderInSignal(t) {
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
    const conviction = t.conviction != null ? Number(t.conviction).toFixed(1) + 'x' : '?';
    const ago = formatTimeAgo(t.detected_at);
    const profileUrl = t.wallet_address
        ? `https://polymarket.com/profile/${t.wallet_address}`
        : '';

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
                <span class="change-badge ${changeClass}">${changeType}</span>
            </div>
            <div class="trader-stats-row">
                <span>Score: <b>${score}</b></span>
                <span>WR: <b>${wr}</b></span>
                <span>ROI: <b class="${roiClass}">${roi}%</b></span>
            </div>
            <div class="trader-stats-row">
                <span>Size: <b>${size}</b></span>
                <span>Conv: <b>${conviction}</b></span>
                <span>Closed: <b>${totalClosed}</b></span>
            </div>
            ${catBadges ? `<div class="trader-categories">${catBadges}</div>` : ''}
            <div class="trader-stats-row">
                ${profileUrl ? `<a class="profile-link" href="${profileUrl}" target="_blank">Profile &rarr;</a>` : ''}
                <span class="trader-time">${ago}</span>
            </div>
        </div>
    `;
}

// Signal detail back button
$('#signal-back-btn').addEventListener('click', () => {
    hide($('#signal-detail-view'));
    show($('#signals-list-view'));
});

// --- Traders ---
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

// --- Dashboard ---
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

// --- Helpers ---
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

// --- Filter listeners ---
$('#tier-filter').addEventListener('change', () => loadSignals());
$('#status-filter').addEventListener('change', () => loadSignals());

// --- Init ---
loadTab('signals');
