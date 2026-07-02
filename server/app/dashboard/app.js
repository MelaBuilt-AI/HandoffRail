/* HandoffRail Dashboard — Application Logic */

const API_BASE = '/api/v1';
let ws = null;
let currentView = 'packets';
let currentPacketId = null;
let allPackets = [];
let offset = 0;
const LIMIT = 50;

// ── View Switching ────────────────────────────────────────────────────────────

document.querySelectorAll('.nav-link').forEach(link => {
    link.addEventListener('click', (e) => {
        e.preventDefault();
        const view = link.dataset.view;
        switchView(view);
    });
});

function switchView(view) {
    currentView = view;
    document.querySelectorAll('.nav-link').forEach(l => l.classList.remove('active'));
    document.querySelector(`.nav-link[data-view="${view}"]`)?.classList.add('active');
    document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
    document.getElementById(`view-${view}`)?.classList.add('active');

    if (view === 'packets') loadPackets();
    if (view === 'hitl') loadHITL();
    if (view === 'stats') loadStats();
    if (view === 'health') {
        loadHealth();
        startHealthRefresh();
    } else {
        stopHealthRefresh();
    }
}

// ── WebSocket ──────────────────────────────────────────────────────────────────

let wsReconnectDelay = 1000;
const WS_MAX_RECONNECT_DELAY = 30000;
const WS_RECONNECT_MULTIPLIER = 1.5;

function connectWS() {
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const url = `${protocol}//${location.host}/ws`;
    ws = new WebSocket(url);

    ws.onopen = () => {
        document.getElementById('ws-status').className = 'status-dot connected';
        document.getElementById('ws-label').textContent = 'Connected';
        wsReconnectDelay = 1000; // Reset on successful connection
    };

    ws.onclose = () => {
        document.getElementById('ws-status').className = 'status-dot disconnected';
        document.getElementById('ws-label').textContent = 'Disconnected';
        setTimeout(connectWS, wsReconnectDelay);
        wsReconnectDelay = Math.min(wsReconnectDelay * WS_RECONNECT_MULTIPLIER, WS_MAX_RECONNECT_DELAY);
    };

    ws.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            handleWSEvent(data);
        } catch (e) {
            console.error('WS parse error:', e);
        }
    };

    ws.onerror = () => {
        ws.close();
    };
}

function handleWSEvent(event) {
    if (event.type === 'ping') return; // heartbeat
    if (event.type === 'connected') return;
    if (event.type === 'subscribed') return;
    if (event.type === 'unsubscribed') return;

    // Add to live feed
    addToFeed(event);

    // Auto-refresh current view
    if (currentView === 'packets' || currentView === 'hitl') {
        debounceRefresh();
    }
    if (currentView === 'stats') {
        loadStats();
    }
    if (currentView === 'health') {
        debounceHealthRefresh();
    }
}

let refreshTimer = null;
function debounceRefresh() {
    clearTimeout(refreshTimer);
    refreshTimer = setTimeout(() => {
        if (currentView === 'packets') loadPackets();
        if (currentView === 'hitl') loadHITL();
    }, 500);
}

// ── Live Feed ──────────────────────────────────────────────────────────────────

function addToFeed(event) {
    const feed = document.getElementById('live-feed');
    const emptyMsg = feed.querySelector('.feed-empty');
    if (emptyMsg) emptyMsg.remove();

    const time = event.timestamp ? new Date(event.timestamp).toLocaleTimeString() : new Date().toLocaleTimeString();
    const typeColor = getTypeColor(event.type);

    const el = document.createElement('div');
    el.className = 'feed-event';
    el.innerHTML = `
        <span class="feed-time">${time}</span>
        <span class="feed-type" style="color:${typeColor}">${event.type}</span>
        <span class="feed-detail">${event.packet_id?.substring(0, 8) || ''}… ${event.data?.status || ''}</span>
    `;

    feed.insertBefore(el, feed.firstChild);

    // Keep max 100 events
    while (feed.children.length > 100) {
        feed.removeChild(feed.lastChild);
    }
}

function getTypeColor(type) {
    if (type.includes('created')) return '#60a5fa';
    if (type.includes('claimed')) return '#3b82f6';
    if (type.includes('completed')) return '#22c55e';
    if (type.includes('failed')) return '#ef4444';
    if (type.includes('expired')) return '#6b7280';
    if (type.includes('hitl')) return '#e879f9';
    if (type.includes('chained')) return '#f59e0b';
    return '#94a3b8';
}

document.getElementById('btn-clear-feed')?.addEventListener('click', () => {
    const feed = document.getElementById('live-feed');
    feed.innerHTML = '<div class="feed-empty">Waiting for events...</div>';
});

// ── Packets List ───────────────────────────────────────────────────────────────

async function loadPackets() {
    const status = document.getElementById('filter-status')?.value || '';
    const search = document.getElementById('filter-search')?.value || '';
    let url = `${API_BASE}/packets?limit=${LIMIT}&offset=${offset}`;
    if (status) url += `&status=${status}`;

    showLoading('packets-tbody');
    try {
        const res = await fetch(url);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        allPackets = data.packets || [];
        renderPackets(allPackets, search);
        renderPagination(data.total || 0);
    } catch (e) {
        showError('packets-tbody', `Failed to load packets: ${e.message}`);
    }
}

function renderPackets(packets, search = '') {
    const tbody = document.getElementById('packets-tbody');
    if (!packets.length) {
        tbody.innerHTML = '<tr><td colspan="6" class="empty-state">No packets found</td></tr>';
        return;
    }

    let filtered = packets;
    if (search) {
        const q = search.toLowerCase();
        filtered = packets.filter(p =>
            p.id.toLowerCase().includes(q) ||
            (p.metadata?.source_agent?.name || '').toLowerCase().includes(q) ||
            (p.metadata?.target_agent?.name || '').toLowerCase().includes(q)
        );
    }

    tbody.innerHTML = filtered.map(p => {
        const src = p.metadata?.source_agent?.name || p.metadata?.source_agent?.id || '—';
        const tgt = p.metadata?.target_agent?.name || p.metadata?.target_agent?.id || '—';
        const created = new Date(p.created_at).toLocaleString();
        const priorityClass = `priority-${p.metadata?.priority || 'normal'}`;
        return `<tr>
            <td><code title="${p.id}">${p.id.substring(0, 8)}…</code></td>
            <td><span class="status-badge status-${p.status}">${p.status.replace('_', ' ')}</span></td>
            <td>${src} → ${tgt}</td>
            <td><span class="${priorityClass}">${p.metadata?.priority || 'normal'}</span></td>
            <td>${created}</td>
            <td><button class="btn btn-sm btn-primary" onclick="viewDetail('${p.id}')">View</button></td>
        </tr>`;
    }).join('');
}

function renderPagination(total) {
    const el = document.getElementById('packets-pagination');
    if (!el) return;
    const pages = Math.ceil(total / LIMIT);
    if (pages <= 1) { el.innerHTML = ''; return; }

    let html = '';
    if (offset > 0) html += `<button class="btn btn-sm btn-secondary" onclick="goPage(${offset - LIMIT})">← Prev</button>`;
    html += `<span style="color:var(--text-muted)">Page ${Math.floor(offset / LIMIT) + 1} of ${pages}</span>`;
    if (offset + LIMIT < total) html += `<button class="btn btn-sm btn-secondary" onclick="goPage(${offset + LIMIT})">Next →</button>`;
    el.innerHTML = html;
}

function goPage(newOffset) {
    offset = newOffset;
    loadPackets();
}

document.getElementById('btn-refresh')?.addEventListener('click', loadPackets);
document.getElementById('filter-status')?.addEventListener('change', () => { offset = 0; loadPackets(); });
document.getElementById('filter-search')?.addEventListener('input', () => {
    renderPackets(allPackets, document.getElementById('filter-search')?.value || '');
});

// ── Packet Detail ──────────────────────────────────────────────────────────────

async function viewDetail(id) {
    currentPacketId = id;
    // Show loading in detail sections
    ['detail-meta', 'detail-context', 'detail-decisions', 'detail-actions', 'detail-history', 'detail-json'].forEach(cid => showLoading(cid));

    try {
        const [packetRes, historyRes] = await Promise.all([
            fetch(`${API_BASE}/packets/${id}`),
            fetch(`${API_BASE}/packets/${id}/history`),
        ]);
        if (!packetRes.ok) throw new Error(`Packet fetch failed: HTTP ${packetRes.status}`);
        if (!historyRes.ok) throw new Error(`History fetch failed: HTTP ${historyRes.status}`);
        const packet = await packetRes.json();
        const history = await historyRes.json();

        document.getElementById('detail-title').textContent = `Packet ${id.substring(0, 8)}…`;

        // Metadata
        const meta = packet.metadata || {};
        document.getElementById('detail-meta').innerHTML = fields([
            ['ID', packet.id],
            ['Status', packet.status],
            ['Version', packet.version],
            ['Source', `${meta.source_agent?.name || '—'} (${meta.source_agent?.id || '—'})`],
            ['Target', `${meta.target_agent?.name || '—'} (${meta.target_agent?.id || '—'})`],
            ['Priority', meta.priority || 'normal'],
            ['Tags', (meta.tags || []).join(', ') || '—'],
            ['Created', new Date(packet.created_at).toLocaleString()],
            ['Updated', new Date(packet.updated_at).toLocaleString()],
        ]);

        // Context
        const ctx = packet.context || {};
        document.getElementById('detail-context').innerHTML = `
            <div class="field"><span class="field-label">Summary</span><span class="field-value">${ctx.summary || '—'}</span></div>
            <div class="field"><span class="field-label">Messages</span><span class="field-value">${(ctx.conversation_state || []).length}</span></div>
            <div class="field"><span class="field-label">Artifacts</span><span class="field-value">${(ctx.artifacts || []).length}</span></div>
        `;

        // Decisions
        const decisions = packet.decisions || [];
        document.getElementById('detail-decisions').innerHTML = decisions.length
            ? decisions.map(d => `<div class="field"><span class="field-label">${d.decision}</span><span class="field-value">${d.rationale || '—'}</span></div>`).join('')
            : '<div class="empty-state">No decisions</div>';

        // Actions
        const actions = packet.actions || {};
        const pendingCount = (actions.pending || []).length;
        const completedCount = (actions.completed || []).length;
        const failedCount = (actions.failed || []).length;
        document.getElementById('detail-actions').innerHTML = `
            <div class="field"><span class="field-label">Pending</span><span class="field-value">${pendingCount}</span></div>
            <div class="field"><span class="field-label">Completed</span><span class="field-value">${completedCount}</span></div>
            <div class="field"><span class="field-label">Failed</span><span class="field-value">${failedCount}</span></div>
        `;

        // History timeline
        const events = history.events || [];
        document.getElementById('detail-history').innerHTML = events.length
            ? events.map(e => `
                <div class="timeline-event">
                    <div class="timeline-time">${new Date(e.timestamp).toLocaleString()}</div>
                    <div>
                        <div class="timeline-type">${e.event_type}</div>
                        <div class="timeline-actor">${e.actor || '—'}</div>
                    </div>
                </div>
            `).join('')
            : '<div class="empty-state">No events</div>';

        // Raw JSON
        document.getElementById('detail-json').textContent = JSON.stringify(packet, null, 2);

        switchView('detail');
    } catch (e) {
        showError('detail-meta', `Failed to load packet: ${e.message}`);
        ['detail-context', 'detail-decisions', 'detail-actions', 'detail-history', 'detail-json'].forEach(cid => {
            document.getElementById(cid).innerHTML = '';
        });
    }
}

function fields(pairs) {
    return pairs.map(([k, v]) => `<div class="field"><span class="field-label">${k}</span><span class="field-value">${v}</span></div>`).join('');
}

// ── HITL Queue ─────────────────────────────────────────────────────────────────

async function loadHITL() {
    const container = document.getElementById('hitl-list');
    showLoading('hitl-list');
    try {
        const res = await fetch(`${API_BASE}/packets/awaiting`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        const packets = data.packets || [];

        if (!packets.length) {
            container.innerHTML = '<div class="empty-state">No packets awaiting human review</div>';
            return;
        }

        container.innerHTML = packets.map(p => {
            const hitl = p.hitl || {};
            const meta = p.metadata || {};
            const options = hitl.options || [];
            return `<div class="hitl-card">
                <h4>Packet ${p.id.substring(0, 8)}…</h4>
                <div class="hitl-meta">From: ${meta.source_agent?.name || '—'} → Human • Priority: ${meta.priority || 'normal'}</div>
                <div class="hitl-question">${hitl.question || 'No question specified'}</div>
                <div class="hitl-meta">Reason: ${hitl.reason || '—'}</div>
                <div class="hitl-options">
                    ${options.map(opt => `<button class="btn btn-sm btn-primary" onclick="respondHITL('${p.id}', '${opt.replace(/'/g, "\\'")}')">${opt}</button>`).join('')}
                    <button class="btn btn-sm btn-secondary" onclick="showHITLModal('${p.id}')">Custom Response</button>
                </div>
            </div>`;
        }).join('');
    } catch (e) {
        showError('hitl-list', `Failed to load HITL queue: ${e.message}`);
    }
}

async function respondHITL(packetId, response) {
    const respondedBy = prompt('Your name:', 'dashboard-user') || 'dashboard-user';
    try {
        await fetch(`${API_BASE}/packets/${packetId}/respond`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ response, responded_by: respondedBy }),
        });
        loadHITL();
    } catch (e) {
        console.error('HITL response failed:', e);
    }
}

function showHITLModal(packetId) {
    const modal = document.getElementById('hitl-modal');
    modal.classList.remove('hidden');
    document.getElementById('hitl-modal-question').textContent = `Respond to packet ${packetId.substring(0, 8)}…`;
    document.getElementById('hitl-modal-response').value = '';
    document.getElementById('hitl-modal-responded-by').value = '';

    document.getElementById('hitl-modal-submit').onclick = async () => {
        const response = document.getElementById('hitl-modal-response').value;
        const respondedBy = document.getElementById('hitl-modal-responded-by').value || 'dashboard-user';
        if (!response) return;
        try {
            await fetch(`${API_BASE}/packets/${packetId}/respond`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ response, responded_by: respondedBy }),
            });
            modal.classList.add('hidden');
            loadHITL();
        } catch (e) {
            console.error('HITL response failed:', e);
        }
    };

    document.getElementById('hitl-modal-cancel').onclick = () => modal.classList.add('hidden');
}

// ── Stats ──────────────────────────────────────────────────────────────────────

async function loadStats() {
    const bars = document.getElementById('status-bars');
    showLoading('status-bars');
    try {
        const res = await fetch(`${API_BASE}/stats`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();

        document.getElementById('stat-total').textContent = data.total_packets ?? '—';
        document.getElementById('stat-24h').textContent = data.packets_last_24h ?? '—';
        document.getElementById('stat-hitl').textContent = data.hitl_queue_depth ?? '—';
        document.getElementById('stat-ws').textContent = data.active_ws_connections ?? '—';
        document.getElementById('stat-claim-time').textContent = data.avg_claim_time_seconds != null
            ? formatDuration(data.avg_claim_time_seconds)
            : '—';

        // Status bars
        const bars = document.getElementById('status-bars');
        const statuses = data.packets_by_status || {};
        const total = data.total_packets || 1;
        const colors = {
            created: '#60a5fa', claimed: '#3b82f6', in_progress: '#f59e0b',
            awaiting_human: '#e879f9', completed: '#22c55e', failed: '#ef4444', expired: '#6b7280',
        };

        bars.innerHTML = Object.entries(statuses).map(([status, count]) => `
            <div class="status-bar-row">
                <span class="status-bar-label">${status.replace('_', ' ')}</span>
                <div class="status-bar-fill">
                    <div class="status-bar-inner" style="width:${(count / total * 100).toFixed(1)}%; background:${colors[status] || '#94a3b8'}"></div>
                </div>
                <span class="status-bar-count">${count}</span>
            </div>
        `).join('');
    } catch (e) {
        showError('status-bars', `Failed to load stats: ${e.message}`);
    }
}

function formatDuration(seconds) {
    if (seconds < 60) return `${seconds.toFixed(1)}s`;
    if (seconds < 3600) return `${(seconds / 60).toFixed(1)}m`;
    return `${(seconds / 3600).toFixed(1)}h`;
}

// ── Health / Observability Panel ─────────────────────────────────────────────────

async function loadHealth() {
    // Fetch health endpoints
    const healthPromises = [
        fetch('/health').then(r => r.ok ? r.json() : {status: 'error'}),
        fetch('/ready').then(r => r.ok ? r.json() : {status: 'error', db: false}),
        fetch(`${API_BASE}/stats`).then(r => r.ok ? r.json() : {}),
        fetch('/metrics').then(r => r.ok ? r.text() : ''),
    ];

    try {
        const [health, ready, stats, metricsText] = await Promise.all(healthPromises);
        renderHealthStatus(health, ready);
        renderHealthMetrics(stats);
        renderLatencyTable(metricsText);
        renderPrometheusCard(metricsText);
    } catch (e) {
        console.error('Health load failed:', e);
        showError('health-service-card', `Failed to load health data: ${e.message}`);
    }
}

function renderHealthStatus(health, ready) {
    // Service status
    const dot = document.getElementById('health-dot');
    const statusText = document.getElementById('health-status-text');
    const detail = document.getElementById('health-detail');

    const serviceOk = health.status === 'ok';
    dot.className = 'health-indicator ' + (serviceOk ? 'status-ok' : 'status-err');
    statusText.textContent = serviceOk ? 'Healthy' : 'Unhealthy';
    statusText.style.color = serviceOk ? 'var(--green)' : 'var(--red)';
    detail.textContent = 'handoffrail v0.2.0 • ' + (health.service || 'API');

    // DB status
    const dbDot = document.getElementById('health-db-dot');
    const dbStatus = document.getElementById('health-db-status');
    const dbOk = ready.db === true;
    dbDot.className = 'health-indicator ' + (dbOk ? 'status-ok' : 'status-err');
    dbStatus.textContent = dbOk ? 'Connected' : 'Disconnected';
    dbStatus.style.color = dbOk ? 'var(--green)' : 'var(--red)';
}

function renderHealthMetrics(stats) {
    if (!stats || Object.keys(stats).length === 0) return;

    document.getElementById('health-metric-active-ws').textContent = stats.active_ws_connections ?? '—';
    document.getElementById('health-metric-total-packets').textContent = stats.total_packets ?? '—';
    document.getElementById('health-metric-packets-24h').textContent = stats.packets_last_24h ?? '—';
    document.getElementById('health-metric-hitl').textContent = stats.hitl_queue_depth ?? '—';

    // Estimate handoffs from status counts
    const statuses = stats.packets_by_status || {};
    const totalHandoffs = Object.values(statuses).reduce((a, b) => a + b, 0);
    document.getElementById('health-metric-handoffs').textContent = totalHandoffs || stats.total_packets || '—';
}

function parsePrometheusMetrics(text) {
    if (!text) return { counters: {}, histograms: {}, gauges: {} };
    const lines = text.split('\n');
    const counters = {};
    const histograms = {};
    const gauges = {};

    for (const line of lines) {
        if (line.startsWith('#') || line.trim() === '') continue;

        // Parse metric lines: name{labels} value
        const match = line.match(/^(\w+)(\{[^}]*\})?\s+([\d.e+]+)/);
        if (!match) continue;

        const name = match[1];
        const labels = match[2] || '';
        const value = parseFloat(match[3]);

        if (isNaN(value)) continue;

        if (name.endsWith('_total') || name.endsWith('_count')) {
            counters[name] = (counters[name] || 0) + value;
        } else if (name.includes('_bucket') || name.endsWith('_seconds')) {
            if (!histograms[name]) histograms[name] = [];
            histograms[name].push({ labels, value });
        } else if (name.startsWith('handoffrail_')) {
            gauges[name] = value;
        }
    }

    return { counters, histograms, gauges };
}

function renderLatencyTable(metricsText) {
    const container = document.getElementById('health-latency-table');

    if (!metricsText) {
        container.innerHTML = '<div class="empty-state">No metrics data available — start the server with Prometheus metrics enabled</div>';
        return;
    }

    const parsed = parsePrometheusMetrics(metricsText);

    // Look for request latency histogram
    const latencies = parsed.histograms['handoffrail_request_latency_seconds_bucket'] || [];

    if (latencies.length === 0) {
        // Show gauges as latency info when no histogram
        const latGauge = parsed.gauges['handoffrail_request_latency_seconds'];
        container.innerHTML = `
            <div class="health-latency-grid">
                <div class="empty-state">Waiting for Prometheus histogram data to populate...</div>
            </div>
        `;
        return;
    }

    // Build a latency distribution table
    const buckets = latencies.map(l => ({
        le: parseFloat(l.labels.match(/le="([^"]+)"/)?.[1] || '0'),
        count: l.value,
    })).filter(b => !isNaN(b.le)).sort((a, b) => a.le - b.le);

    const totalCount = buckets.length > 0 ? buckets[buckets.length - 1].count : 0;

    let rows = buckets.map(b => {
        const pct = totalCount > 0 ? ((b.count / totalCount) * 100).toFixed(1) : '0.0';
        const leLabel = b.le < 0.1 ? `${(b.le * 1000).toFixed(0)}ms` :
                        b.le < 1 ? `${(b.le * 1000).toFixed(0)}ms` :
                        `${b.le.toFixed(2)}s`;
        const barWidth = Math.max(1, parseFloat(pct));
        return `<div class="latency-row">
            <span class="latency-label">≤ ${leLabel}</span>
            <div class="latency-bar-fill">
                <div class="latency-bar-inner" style="width:${barWidth}%"></div>
            </div>
            <span class="latency-count">${b.count.toLocaleString()}</span>
            <span class="latency-pct">${pct}%</span>
        </div>`;
    }).join('');

    container.innerHTML = `
        <div class="latency-table">
            <div class="latency-header">
                <span class="latency-label">Bucket</span>
                <span class="latency-bar-fill">Distribution</span>
                <span class="latency-count">Count</span>
                <span class="latency-pct">%</span>
            </div>
            ${rows}
            <div class="latency-total">
                <span class="latency-label">Total</span>
                <span></span>
                <span class="latency-count">${totalCount.toLocaleString()}</span>
                <span class="latency-pct">100%</span>
            </div>
        </div>
    `;
}

function renderPrometheusCard(metricsText) {
    const container = document.getElementById('prometheus-content');
    if (!metricsText) {
        container.textContent = 'No metrics available — ensure server is running with Prometheus endpoint.';
        return;
    }

    // Extract key metrics for a clean summary
    const lines = metricsText.split('\n');
    const summaryLines = [];

    for (const line of lines) {
        if (line.startsWith('# HELP') || line.startsWith('# TYPE')) {
            summaryLines.push(line);
        } else if (line.startsWith('handoffrail_')) {
            summaryLines.push(line);
        }
    }

    // If too many lines, show a concise subset
    const display = summaryLines.length > 60
        ? summaryLines.filter(l => !l.includes('_bucket') && !l.includes('_created'))
        : summaryLines;

    container.textContent = display.join('\n') || 'No handoffrail_ metrics found.';
}

// Refresh health on timer when health view is active
let healthRefreshTimer = null;
function startHealthRefresh() {
    stopHealthRefresh();
    healthRefreshTimer = setInterval(() => {
        if (currentView === 'health') loadHealth();
    }, 15000);
}
function stopHealthRefresh() {
    if (healthRefreshTimer) {
        clearInterval(healthRefreshTimer);
        healthRefreshTimer = null;
    }
}

let healthRefreshDebounceTimer = null;
function debounceHealthRefresh() {
    clearTimeout(healthRefreshDebounceTimer);
    healthRefreshDebounceTimer = setTimeout(() => {
        if (currentView === 'health') loadHealth();
    }, 1000);
}

document.getElementById('btn-refresh-health')?.addEventListener('click', () => {
    loadHealth();
    if (currentView === 'health') startHealthRefresh();
});

// ── Back button ────────────────────────────────────────────────────────────────

document.getElementById('btn-back')?.addEventListener('click', () => switchView('packets'));

// ── Loading & Error UI ───────────────────────────────────────────────────────

function showLoading(containerId) {
    const el = document.getElementById(containerId);
    if (!el) return;
    el.innerHTML = `<div class="loading-state"><div class="spinner"></div><span>Loading...</span></div>`;
}

function showError(containerId, message) {
    const el = document.getElementById(containerId);
    if (!el) return;
    el.innerHTML = `<div class="error-state"><span class="error-icon">⚠</span> ${message}<br><button class="btn btn-sm btn-primary" onclick="location.reload()">Retry</button></div>`;
}

// ── Init ───────────────────────────────────────────────────────────────────────

loadPackets();
connectWS();