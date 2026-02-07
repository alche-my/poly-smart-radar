const API_BASE = window.location.origin + '/api';

// Telegram WebApp integration
const tg = window.Telegram && window.Telegram.WebApp;
if (tg) {
    tg.ready();
    tg.expand();
}

// --- State ---
let currentTab = 'signals';

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

// --- Tabs ---
$$('.tab').forEach(btn => {
    btn.addEventListener('click', () => {
        $$('.tab').forEach(b => b.classList.remove('active'));
        $$('.tab-content').forEach(c => c.classList.remove('active'));
        btn.classList.add('active');
        const tab = btn.dataset.tab;
        $(`#${tab}-tab`).classList.add('active');
        currentTab = tab;
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
        show(empty);
        return;
    }

    hide(empty);
    list.innerHTML = data.signals.map(renderSignalCard).join('');
}

function renderSignalCard(s) {
    const tierClass = `tier-${s.tier || 3}`;
    const tierLabel = `Tier ${s.tier || '?'}`;
    const dirClass = (s.direction || '').toUpperCase() === 'YES' ? 'direction-yes' : 'direction-no';
    const traders = Array.isArray(s.traders_involved) ? s.traders_involved : [];
    const tradersCount = traders.length;
    const timeAgo = formatTimeAgo(s.created_at);
    const slug = s.market_slug || '';
    const price = s.current_price != null ? `$${Number(s.current_price).toFixed(2)}` : '';

    return `
        <div class="card signal-card">
            <div class="header">
                <span class="tier-badge ${tierClass}">${tierLabel}</span>
                <span class="score">${Number(s.signal_score || 0).toFixed(1)}</span>
            </div>
            <div class="market-title">${escapeHtml(s.market_title || 'Unknown market')}</div>
            <div class="meta">
                <span class="direction ${dirClass}">${(s.direction || '?').toUpperCase()} ${price}</span>
                <span>${timeAgo}</span>
            </div>
            <div class="traders-count">${tradersCount} trader${tradersCount !== 1 ? 's' : ''} involved</div>
            ${slug ? `<a class="market-link" href="https://polymarket.com/event/${slug}" target="_blank">View on Polymarket</a>` : ''}
        </div>
    `;
}

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
    list.innerHTML = data.traders.map(renderTraderCard).join('');
}

function renderTraderCard(t) {
    const name = t.username || (t.wallet_address ? t.wallet_address.slice(0, 10) + '...' : 'Unknown');
    const wr = t.win_rate != null ? (t.win_rate * 100).toFixed(0) : '?';
    const roi = t.roi != null ? (t.roi * 100).toFixed(1) : '?';
    const closed = t.total_closed || 0;

    return `
        <div class="card trader-card">
            <div class="header">
                <span class="name">${escapeHtml(name)}</span>
                <span class="score">${Number(t.trader_score || 0).toFixed(2)}</span>
            </div>
            <div class="stats">
                <span>WR: <span class="stat-value">${wr}%</span></span>
                <span>ROI: <span class="stat-value">${roi}%</span></span>
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
        ${(data.top_signals || []).map(renderSignalCard).join('') || '<div class="empty-state">No active signals</div>'}
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
