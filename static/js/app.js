// ── State ─────────────────────────────────────────────────────────────────────
let selectedDate = new Date();
let calYear, calMonth;
const today = new Date();
calYear = today.getFullYear();
calMonth = today.getMonth();

// ── Navigation ───────────────────────────────────────────────────────────────
document.querySelectorAll('.nav-link').forEach(link => {
    link.addEventListener('click', e => {
        e.preventDefault();
        const page = link.dataset.page;
        document.querySelectorAll('.nav-link').forEach(l => l.classList.remove('active'));
        link.classList.add('active');
        document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
        document.getElementById('page-' + page).classList.add('active');
        if (page === 'recently-played') loadRecentlyPlayed();
        if (page === 'schedule') loadSchedule();
        if (page === 'settings') loadSettings();
        if (page === 'console') loadConsole();
        if (page === 'import-export') loadPlaylistsForExport();
    });
});

// ── API Helper ───────────────────────────────────────────────────────────────
async function api(url, opts = {}) {
    try {
        if (opts.body && typeof opts.body === 'object') {
            opts.headers = { 'Content-Type': 'application/json', ...(opts.headers || {}) };
            opts.body = JSON.stringify(opts.body);
        }
        const r = await fetch(url, opts);
        return await r.json();
    } catch (e) { console.error(e); return { error: e.message }; }
}

// ── Status Polling ───────────────────────────────────────────────────────────
async function updateStatus() {
    const d = await api('/api/status');
    if (d.error) return;
    document.getElementById('status-text').textContent = d.schedule_status || '';
    document.getElementById('status-user').textContent = d.username || '';
    document.getElementById('status-time').textContent = new Date().toLocaleTimeString();
    const btn = document.getElementById('btn-toggle-pause');
    btn.textContent = d.paused ? '▶ Resume' : '⏸ Pause';
    btn.className = d.paused ? 'btn btn-accent' : 'btn';
}

async function togglePause() {
    await api('/api/toggle-pause', { method: 'POST' });
    updateStatus();
}

// ── Now Playing ──────────────────────────────────────────────────────────────
async function loadNowPlaying() {
    const d = await api('/api/now-playing');
    const cover = document.getElementById('np-cover');
    const noCover = document.getElementById('np-no-cover');
    if (d.playing) {
        document.getElementById('np-title').textContent = d.title || '';
        document.getElementById('np-artist').textContent = d.artist || '';
        document.getElementById('np-playlist').textContent = d.playlist ? `Playlist: ${d.playlist}` : '';
        document.getElementById('np-device').textContent = d.device ? `Device: ${d.device}` : '';
        document.getElementById('np-slot').textContent = d.time_slot ? `Time slot: ${d.time_slot}` : '';
        const badge = document.getElementById('np-state');
        badge.textContent = d.state || '';
        badge.className = 'np-state-badge ' + (d.is_playing ? 'playing' : 'paused');
        if (d.album_image) { cover.src = d.album_image; cover.style.display = 'block'; noCover.style.display = 'none'; }
        else { cover.style.display = 'none'; noCover.style.display = 'flex'; }
        // Checklist
        let cl = '';
        if (d.devices && d.devices.length > 0) {
            cl += d.devices.map(dev => `${dev.active ? '✅' : '•'} ${dev.name}`).join('<br>');
        }
        document.getElementById('checklist-content').innerHTML = cl;
    } else {
        document.getElementById('np-title').textContent = d.message || 'Nothing is playing';
        document.getElementById('np-artist').textContent = '';
        document.getElementById('np-playlist').textContent = '';
        document.getElementById('np-device').textContent = '';
        document.getElementById('np-slot').textContent = '';
        document.getElementById('np-state').textContent = '';
        document.getElementById('np-state').className = 'np-state-badge';
        cover.style.display = 'none'; noCover.style.display = 'flex';
        let cl = '';
        if (d.devices && d.devices.length > 0) {
            cl += d.devices.map(dev => `${dev.active ? '✅' : '•'} ${dev.name}`).join('<br>');
        }
        document.getElementById('checklist-content').innerHTML = cl || 'No devices found';
    }
}

// ── Calendar ─────────────────────────────────────────────────────────────────
let scheduledDates = [];

function renderCalendar() {
    const widget = document.getElementById('calendar-widget');
    const first = new Date(calYear, calMonth, 1);
    const daysInMonth = new Date(calYear, calMonth + 1, 0).getDate();
    const startDay = (first.getDay() + 6) % 7; // Monday-based
    const monthNames = ['January','February','March','April','May','June','July','August','September','October','November','December'];
    const dayNames = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'];
    const todayStr = `${today.getFullYear()}-${String(today.getMonth()+1).padStart(2,'0')}-${String(today.getDate()).padStart(2,'0')}`;
    const selStr = `${selectedDate.getFullYear()}-${String(selectedDate.getMonth()+1).padStart(2,'0')}-${String(selectedDate.getDate()).padStart(2,'0')}`;

    let html = `<div class="cal-header">
        <button onclick="calPrev()">◀</button>
        <span class="cal-month">${monthNames[calMonth]} ${calYear}</span>
        <button onclick="calNext()">▶</button>
    </div><div class="cal-grid">`;
    dayNames.forEach(d => html += `<div class="cal-day-name">${d}</div>`);
    for (let i = 0; i < startDay; i++) html += `<div class="cal-day empty"></div>`;
    for (let d = 1; d <= daysInMonth; d++) {
        const ds = `${calYear}-${String(calMonth+1).padStart(2,'0')}-${String(d).padStart(2,'0')}`;
        let cls = 'cal-day';
        if (ds === todayStr) cls += ' today';
        if (ds === selStr) cls += ' selected';
        else if (scheduledDates.includes(ds)) cls += ' has-schedule';
        html += `<div class="${cls}" onclick="selectDate(${calYear},${calMonth},${d})">${d}</div>`;
    }
    html += '</div>';
    widget.innerHTML = html;
}

function calPrev() { calMonth--; if (calMonth < 0) { calMonth = 11; calYear--; } renderCalendar(); }
function calNext() { calMonth++; if (calMonth > 11) { calMonth = 0; calYear++; } renderCalendar(); }
function selectDate(y, m, d) { selectedDate = new Date(y, m, d); renderCalendar(); loadSchedule(); }
function getDateStr() {
    return `${selectedDate.getFullYear()}-${String(selectedDate.getMonth()+1).padStart(2,'0')}-${String(selectedDate.getDate()).padStart(2,'0')}`;
}

// ── Schedule ─────────────────────────────────────────────────────────────────
async function loadSchedule() {
    const d = await api(`/api/schedule/${getDateStr()}`);
    if (d.scheduled_dates) scheduledDates = d.scheduled_dates;
    renderCalendar();
    const el = document.getElementById('schedule-entries');
    if (!d.entries || d.entries.length === 0) {
        el.innerHTML = '<div class="sched-empty">No entries for this day. Add one below.</div>';
        return;
    }
    el.innerHTML = d.entries.map(e => `
        <div class="sched-row" id="sched-row-${e.time_range.replace(':','')}">
            <span class="sr-start">${e.start}</span>
            <span class="sr-end">${e.end}</span>
            <div class="sr-edit">
                <button class="sr-edit-btn" title="Quick edit times" onclick="editEntryTime('${getDateStr()}','${e.time_range}','${e.start}','${e.end}')">✎</button>
            </div>
            <div class="sr-playlist">
                <button class="sr-playlist-btn" onclick="openPlaylistModal('${getDateStr()}','${e.time_range}')">${escHtml(e.playlist_name || '--- Click to set ---')}</button>
            </div>
            <div class="sr-rq">
                <input type="checkbox" ${e.randomqueue ? 'checked' : ''} ${e.playlist_id && e.playlist_id.includes('37i9dQ') ? 'disabled' : ''}
                    onchange="updateEntry('${getDateStr()}','${e.time_range}',{randomqueue:this.checked})">
            </div>
            <div class="sr-del">
                <button onclick="deleteEntry('${getDateStr()}','${e.time_range}')">✕</button>
            </div>
        </div>
    `).join('');
}

function escHtml(s) { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }

async function addEntry() {
    const st = document.getElementById('add-start').value.replace(';',':');
    const et = document.getElementById('add-end').value.replace(';',':');
    const d = await api(`/api/schedule/${getDateStr()}`, { method: 'POST', body: { start: st, end: et } });
    document.getElementById('schedule-status').textContent = d.error || 'Entry added';
    if (!d.error) { document.getElementById('add-start').value = ''; document.getElementById('add-end').value = ''; }
    loadSchedule();
}

async function deleteEntry(date, tr) {
    await api(`/api/schedule/${date}/${tr}`, { method: 'DELETE' });
    loadSchedule();
}

async function updateEntry(date, tr, data) {
    await api(`/api/schedule/${date}/${tr}`, { method: 'PUT', body: data });
    loadSchedule();
}

function editEntryTime(date, timeRange, startVal, endVal) {
    // Find all sched-rows and match by looking at the edit button's onclick
    const rows = document.querySelectorAll('.sched-row');
    let row = null;
    rows.forEach(r => {
        const btn = r.querySelector('.sr-edit-btn');
        if (btn && btn.getAttribute('onclick').includes(timeRange)) row = r;
    });
    if (!row) return;

    const startEl = row.querySelector('.sr-start');
    const endEl = row.querySelector('.sr-end');
    const editDiv = row.querySelector('.sr-edit');

    // Replace text with inputs
    startEl.outerHTML = `<input type="text" class="input-sm sr-start-input" value="${startVal}" placeholder="HH:MM" style="width:70px">`;
    endEl.outerHTML = `<input type="text" class="input-sm sr-end-input" value="${endVal}" placeholder="HH:MM" style="width:70px">`;

    // Replace edit button with save/cancel
    editDiv.innerHTML = `
        <button class="sr-save-btn" title="Save" onclick="saveEditEntry('${date}','${timeRange}',this.closest('.sched-row'))">✓</button>
        <button class="sr-cancel-btn" title="Cancel" onclick="loadSchedule()">✗</button>
    `;

    // Focus the start input and handle Enter key
    const startInput = row.querySelector('.sr-start-input');
    const endInput = row.querySelector('.sr-end-input');
    startInput.focus();
    startInput.select();
    const handleEnter = (e) => { if (e.key === 'Enter') saveEditEntry(date, timeRange, row); };
    startInput.addEventListener('keydown', handleEnter);
    endInput.addEventListener('keydown', handleEnter);
}

async function saveEditEntry(date, oldTimeRange, row) {
    const newStart = row.querySelector('.sr-start-input').value.trim().replace(';', ':');
    const newEnd = row.querySelector('.sr-end-input').value.trim().replace(';', ':');
    if (!newStart || !newEnd) return;
    const d = await api(`/api/schedule/${date}/${oldTimeRange}/time`, {
        method: 'PUT', body: { start: newStart, end: newEnd }
    });
    if (d.error) {
        document.getElementById('schedule-status').textContent = d.error;
    } else {
        document.getElementById('schedule-status').textContent = 'Time updated';
    }
    loadSchedule();
}

// ── Playlist Selection Modal ─────────────────────────────────────────────────
let modalCallback = null;

async function openPlaylistModal(date, timeRange) {
    const overlay = document.getElementById('modal-overlay');
    const list = document.getElementById('modal-playlist-list');
    const input = document.getElementById('modal-playlist-input');
    input.value = '';
    list.innerHTML = '<div style="padding:20px;text-align:center;color:var(--fg3)">Loading...</div>';
    overlay.style.display = 'flex';
    const d = await api('/api/playlists');
    if (d.playlists) {
        list.innerHTML = d.playlists.map(p =>
            `<div class="modal-list-item" onclick="selectPlaylistItem(this,'${p.id}')">${escHtml(p.name)} <span style="color:var(--fg3);font-size:11px">${escHtml(p.owner)}</span></div>`
        ).join('');
    } else {
        list.innerHTML = '<div style="padding:20px;text-align:center;color:var(--fg3)">Could not load playlists</div>';
    }
    document.getElementById('modal-select-btn').onclick = () => {
        const val = input.value.trim();
        if (val) { updateEntry(date, timeRange, { playlist: val }); closeModal(); }
    };
    modalCallback = (pid) => { updateEntry(date, timeRange, { playlist: pid }); closeModal(); };
}

function selectPlaylistItem(el, pid) {
    document.querySelectorAll('.modal-list-item').forEach(i => i.classList.remove('selected'));
    el.classList.add('selected');
    document.getElementById('modal-playlist-input').value = pid;
}

function closeModal() {
    document.getElementById('modal-overlay').style.display = 'none';
    modalCallback = null;
}

// ── Copy Schedule Dialogs ────────────────────────────────────────────────────
let copyMode = 'days';

function copyDaysDialog() {
    copyMode = 'days';
    document.getElementById('copy-title').textContent = 'Copy Schedule';
    document.getElementById('copy-desc').textContent = `Copy schedule from ${getDateStr()}`;
    document.getElementById('copy-label').textContent = 'days ahead';
    document.getElementById('copy-count').value = '';
    document.getElementById('copy-preview').textContent = '';
    document.getElementById('copy-confirm-btn').onclick = doCopy;
    document.getElementById('modal-copy').style.display = 'flex';
}

function copyWeekdaysDialog() {
    copyMode = 'weekdays';
    document.getElementById('copy-title').textContent = 'Copy to Weekdays';
    document.getElementById('copy-desc').textContent = `Copy schedule from ${getDateStr()}`;
    document.getElementById('copy-label').textContent = 'same weekdays ahead';
    document.getElementById('copy-count').value = '';
    document.getElementById('copy-preview').textContent = '';
    document.getElementById('copy-confirm-btn').onclick = doCopy;
    document.getElementById('modal-copy').style.display = 'flex';
}

async function doCopy() {
    const count = parseInt(document.getElementById('copy-count').value);
    if (!count || count < 1) return;
    const d = await api(`/api/schedule/${getDateStr()}/copy`, {
        method: 'POST', body: { days: count, mode: copyMode }
    });
    document.getElementById('copy-preview').textContent = d.error || `Copied to ${d.copied} days`;
    if (!d.error) { setTimeout(() => closeCopyModal(), 800); loadSchedule(); }
}

function closeCopyModal() { document.getElementById('modal-copy').style.display = 'none'; }

// ── Recently Played ──────────────────────────────────────────────────────────
async function loadRecentlyPlayed() {
    const d = await api('/api/recently-played');
    const body = document.getElementById('rp-body');
    const status = document.getElementById('rp-status');
    if (d.error) { status.textContent = 'Error loading data'; body.innerHTML = ''; return; }
    status.textContent = `Last refreshed at ${d.refreshed || ''}`;
    body.innerHTML = (d.tracks || []).map(t =>
        `<tr><td>${escHtml(t.time)}</td><td>${escHtml(t.title)}</td><td>${escHtml(t.artist)}</td></tr>`
    ).join('');
}

// ── Import/Export ────────────────────────────────────────────────────────────
async function loadPlaylistsForExport() {
    const sel = document.getElementById('export-playlist-select');
    const d = await api('/api/playlists');
    if (d.playlists) {
        sel.innerHTML = '<option value="">-- Select playlist --</option>' +
            d.playlists.map(p => `<option value="${p.id}">${escHtml(p.name)}</option>`).join('');
    }
}

async function exportPlaylist() {
    const pid = document.getElementById('export-playlist-id').value.trim() || document.getElementById('export-playlist-select').value;
    if (!pid) { document.getElementById('export-status').textContent = 'Select a playlist first'; return; }
    document.getElementById('export-status').textContent = 'Exporting...';
    const d = await api('/api/export-playlist', { method: 'POST', body: { playlist_id: pid } });
    if (d.error) { document.getElementById('export-status').textContent = d.error; return; }
    // Download as JSON
    const blob = new Blob([JSON.stringify(d, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    const name = (d.metadata?.original_name || 'playlist').replace(/[\\/*?:"<>|]/g, '_');
    a.download = `${name}_${new Date().toISOString().slice(0,10)}.json`;
    a.click(); URL.revokeObjectURL(url);
    document.getElementById('export-status').textContent = `Exported ${d.tracks?.length || 0} tracks`;
}

async function importPlaylist() {
    const fileInput = document.getElementById('import-file');
    if (!fileInput.files.length) { document.getElementById('import-status').textContent = 'Select a file'; return; }
    document.getElementById('import-status').textContent = 'Importing...';
    const text = await fileInput.files[0].text();
    let data;
    try { data = JSON.parse(text); } catch { document.getElementById('import-status').textContent = 'Invalid JSON'; return; }
    const name = document.getElementById('import-name').value.trim();
    if (name) data.name = name;
    const d = await api('/api/import-playlist', { method: 'POST', body: data });
    document.getElementById('import-status').textContent = d.error || d.message || 'Done';
}

// ── Settings ─────────────────────────────────────────────────────────────────
async function loadSettings() {
    const d = await api('/api/settings');
    if (d.error) return;
    document.getElementById('set-lang').value = d.LANG || 'en';
    document.getElementById('set-client-id').value = d.CLIENT_ID || '';
    document.getElementById('set-client-secret').value = d.CLIENT_SECRET || '';
    document.getElementById('set-device').value = d.DEVICE_NAME || '';
    document.getElementById('set-weekdays').checked = !!d.WEEKDAYS_ONLY;
    document.getElementById('set-skip-explicit').checked = !!d.SKIP_EXPLICIT;
}

async function saveSettings() {
    const body = {
        LANG: document.getElementById('set-lang').value,
        CLIENT_ID: document.getElementById('set-client-id').value,
        CLIENT_SECRET: document.getElementById('set-client-secret').value,
        DEVICE_NAME: document.getElementById('set-device').value,
        WEEKDAYS_ONLY: document.getElementById('set-weekdays').checked,
        SKIP_EXPLICIT: document.getElementById('set-skip-explicit').checked
    };
    const d = await api('/api/settings', { method: 'POST', body });
    document.getElementById('settings-status').textContent = d.error || d.message || 'Saved';
}

async function logoutSpotify() {
    if (!confirm('Are you sure you want to logout?')) return;
    await api('/api/auth/logout', { method: 'POST' });
    document.getElementById('settings-status').textContent = 'Logged out. Restart server to re-authenticate.';
}

// ── Device Selection ─────────────────────────────────────────────────────────
async function chooseDevice() {
    const overlay = document.getElementById('modal-device');
    const list = document.getElementById('device-list');
    list.innerHTML = '<div style="padding:20px;text-align:center;color:var(--fg3)">Loading...</div>';
    overlay.style.display = 'flex';
    const d = await api('/api/devices');
    if (d.devices && d.devices.length > 0) {
        list.innerHTML = d.devices.map(dev =>
            `<div class="modal-list-item" onclick="pickDevice('${escHtml(dev.name)}')">${escHtml(dev.name)}${dev.active ? ' (Active)' : ''}</div>`
        ).join('');
    } else {
        list.innerHTML = '<div style="padding:20px;text-align:center;color:var(--fg3)">No devices found</div>';
    }
}

function pickDevice(name) {
    document.getElementById('set-device').value = name;
    closeDeviceModal();
}

function closeDeviceModal() { document.getElementById('modal-device').style.display = 'none'; }

// ── Setup Logic ──────────────────────────────────────────────────────────────
async function checkCredentials() {
    const d = await api('/api/settings');
    if (d.error) return true; // Should not happen often
    if (!d.CLIENT_ID || !d.CLIENT_SECRET) {
        document.getElementById('modal-setup').style.display = 'flex';
        return false;
    }
    return true;
}

async function saveSetupSettings() {
    const cid = document.getElementById('setup-client-id').value.trim();
    const cs = document.getElementById('setup-client-secret').value.trim();
    if (!cid || !cs) {
        document.getElementById('setup-status').textContent = 'Both Client ID and Secret are required.';
        return;
    }
    document.getElementById('setup-status').textContent = 'Validating...';
    const d = await api('/api/settings', { method: 'POST', body: { CLIENT_ID: cid, CLIENT_SECRET: cs } });
    if (d.error) {
        document.getElementById('setup-status').textContent = d.error;
    } else {
        document.getElementById('setup-status').textContent = 'Saved! Refreshing...';
        setTimeout(() => {
            document.getElementById('modal-setup').style.display = 'none';
            init(); // Re-init everything
        }, 1000);
    }
}

// ── Console ──────────────────────────────────────────────────────────────────
async function loadConsole() {
    const d = await api('/api/console');
    document.getElementById('console-output').textContent = (d.lines || []).join('\n');
    const el = document.getElementById('console-output');
    el.scrollTop = el.scrollHeight;
}

// ── Init & Polling ───────────────────────────────────────────────────────────
function init() {
    checkCredentials().then(ok => {
        if (!ok) return;
        renderCalendar();
        loadSchedule();
        loadNowPlaying();
        updateStatus();
    });
    
    // Polling intervals
    setInterval(updateStatus, 5000);
    setInterval(loadNowPlaying, 10000);
    // Handle Enter key in add-entry inputs
    document.getElementById('add-start').addEventListener('keydown', e => { if (e.key === 'Enter') addEntry(); });
    document.getElementById('add-end').addEventListener('keydown', e => { if (e.key === 'Enter') addEntry(); });
    // Handle Enter in modal input
    document.getElementById('modal-playlist-input').addEventListener('keydown', e => {
        if (e.key === 'Enter') document.getElementById('modal-select-btn').click();
    });
}

document.addEventListener('DOMContentLoaded', init);
