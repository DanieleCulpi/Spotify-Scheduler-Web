import os, sys, json, re, time, random, threading, platform, locale, base64, logging, webbrowser
import pystray
from pystray import MenuItem as item
from PIL import Image
from datetime import datetime, timezone, timedelta
from io import BytesIO
from flask import Flask, render_template, jsonify, request, redirect, send_file
import spotipy
from spotipy.oauth2 import SpotifyOAuth
import requests as http_requests
from translations import translations
from packaging import version

# ── Config ────────────────────────────────────────────────────────────────────
VER = "4.0"
CONFIG_FILE = "config.json"
SCHEDULE_FILE = "schedule.json"

# When running as PyInstaller bundle, bundled assets are in sys._MEIPASS
# but config/schedule files should live next to the .exe
if getattr(sys, 'frozen', False):
    BUNDLE_DIR = sys._MEIPASS
    DATA_DIR = os.path.dirname(sys.executable)
else:
    BUNDLE_DIR = os.path.dirname(os.path.abspath(__file__))
    DATA_DIR = BUNDLE_DIR
os.chdir(DATA_DIR)

app = Flask(__name__,
            template_folder=os.path.join(BUNDLE_DIR, 'templates'),
            static_folder=os.path.join(BUNDLE_DIR, 'static'))
app.secret_key = os.urandom(24)
log = logging.getLogger('werkzeug')
log.setLevel(logging.WARNING)

# ── Tray Icon Logic ───────────────────────────────────────────────────────────
tray_icon = None

def quit_app(icon, item):
    icon.stop()
    os._exit(0)

def open_dashboard(icon, item):
    webbrowser.open("http://127.0.0.1:5000")

def setup_tray():
    global tray_icon
    try:
        icon_path = os.path.join(BUNDLE_DIR, "icon.ico")
        img = Image.open(icon_path)
    except Exception:
        img = Image.new('RGB', (64, 64), color=(29, 185, 84))
    
    menu = (item('Open Dashboard', open_dashboard), item('Quit', quit_app))
    tray_icon = pystray.Icon("SpotifyScheduler", img, f"Spotify Scheduler v{VER}", menu)
    tray_icon.run()

# ── State ─────────────────────────────────────────────────────────────────────
sp = None
sp_ready = False
is_paused = False
username = ""
user_id = None
last_playlist = ""
last_randomqueue = None
last_spotify_run = False
target_device = None
console_lines = []
_playlist_name_cache = {}
randomqueuefix_playlist = None
randomqueuefix_run = False
cache = {"current_playback": {"data": None, "timestamp": 0}, "devices": {"data": None, "timestamp": 0}}

def clog(msg):
    ts = datetime.now().isoformat(sep=" ", timespec="seconds")
    line = f"{ts} | {msg}"
    console_lines.append(line)
    if len(console_lines) > 200:
        console_lines.pop(0)
    print(line)

def get_default_language():
    try:
        locale.setlocale(locale.LC_TIME, '')
        sl = locale.getlocale()[0]
        if sl and sl.startswith('Polish'): return 'pl'
    except Exception: pass
    return 'en'

def load_config():
    default = {"LANG": get_default_language(), "CLIENT_ID": "", "CLIENT_SECRET": "",
               "DEVICE_NAME": platform.node(), "KILLSWITCH_ON": True, "WEEKDAYS_ONLY": False,
               "AUTO_SPOTIFY": True, "SKIP_EXPLICIT": False}
    try:
        with open(CONFIG_FILE, "r") as f: cfg = json.load(f)
    except FileNotFoundError: cfg = default.copy()
    for k, v in default.items():
        if k not in cfg: cfg[k] = v
    with open(CONFIG_FILE, "w") as f: json.dump(cfg, f, indent=4)
    return cfg

config = load_config()

def _(key, **kw):
    t = translations.get(config['LANG'], {}).get(key, key)
    try: return t.format(**kw)
    except Exception: return t

def save_config(cfg):
    with open(CONFIG_FILE, "w") as f: json.dump(cfg, f, indent=4)
    clog("Configuration saved.")

def validate_credentials(cid=None, cs=None):
    cid = cid or config['CLIENT_ID']
    cs = cs or config['CLIENT_SECRET']
    try:
        r = http_requests.post("https://accounts.spotify.com/api/token",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={"grant_type": "client_credentials", "client_id": cid, "client_secret": cs}, timeout=5)
        return r.status_code == 200
    except: return False

# ── Spotify Init ──────────────────────────────────────────────────────────────
REDIRECT_URI = "http://127.0.0.1:5000/callback"
SCOPE = "user-modify-playback-state user-read-playback-state playlist-modify-public playlist-modify-private playlist-read-private playlist-read-collaborative user-read-playback-position user-top-read user-read-recently-played user-read-email ugc-image-upload user-read-currently-playing app-remote-control streaming user-library-read user-library-modify user-follow-read user-follow-modify user-read-private"

def initialize_sp():
    global sp, sp_ready, username, user_id
    sp = None; sp_ready = False
    if config['CLIENT_ID'] and config['CLIENT_SECRET']:
        try:
            if validate_credentials():
                sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
                    client_id=config['CLIENT_ID'], client_secret=config['CLIENT_SECRET'],
                    redirect_uri=REDIRECT_URI, scope=SCOPE, requests_timeout=5), retries=0, requests_timeout=5)
                sp_ready = True
                try:
                    u = sp.current_user()
                    username = u.get('display_name', '')
                    user_id = u.get('id')
                except: pass
                clog("Spotipy initialized.")
        except Exception as e:
            clog(f"Spotipy init error: {e}")

def cached_spotify_data(data_type, force=False):
    if data_type not in cache: return None
    if (time.time() - cache[data_type]["timestamp"] < 15) and not force:
        return cache[data_type]["data"]
    cache[data_type]["timestamp"] = time.time()
    try:
        if data_type == "current_playback": data = sp.current_playback()
        elif data_type == "devices": data = sp.devices()
        else: data = None
        cache[data_type]["data"] = data
        return data
    except Exception as e:
        clog(f"Cache fetch error ({data_type}): {e}")
        return cache[data_type]["data"]

# ── Schedule ──────────────────────────────────────────────────────────────────
def init_schedule():
    if not os.path.exists(SCHEDULE_FILE):
        with open(SCHEDULE_FILE, "w") as f: json.dump({}, f, indent=4)

def load_schedule():
    try:
        with open(SCHEDULE_FILE, "r") as f: return json.load(f)
    except: return {}

def save_schedule(data):
    with open(SCHEDULE_FILE, "w") as f: json.dump(data, f, indent=4)

def is_valid_time(t_str):
    return re.match(r"^([01]?[0-9]|2[0-3]):[0-5][0-9](:[0-5][0-9])?$", t_str) is not None

def parse_time(t_str):
    fmt = "%H:%M:%S" if t_str.count(":") == 2 else "%H:%M"
    return datetime.strptime(t_str, fmt).time()

last_endtime = None
closest_start_time = None
earliest_start_time = None
empty_schedule = None
last_schedule = ""

def is_within_schedule():
    global last_schedule, last_endtime, closest_start_time, empty_schedule, earliest_start_time
    last_schedule = ""; last_endtime = None; closest_start_time = None; earliest_start_time = None; empty_schedule = True
    match = False
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        now = datetime.now().time()
        sched = load_schedule().get(today, {})
        entries = sorted(sched.items(), key=lambda x: parse_time(x[0].split("-")[0]))
        for tr, ed in entries:
            empty_schedule = False
            s_str, e_str = tr.split("-")
            st, et = parse_time(s_str), parse_time(e_str)
            if st <= now <= et and (not config.get('WEEKDAYS_ONLY') or datetime.today().weekday() < 5):
                last_schedule = tr; match = tr
                edt = datetime.combine(datetime.now(), et)
                if last_endtime is None or last_endtime < edt: last_endtime = edt
            if st > now and (closest_start_time is None or st < closest_start_time): closest_start_time = st
            if earliest_start_time is None or st < earliest_start_time: earliest_start_time = st
        if match: closest_start_time = None
        return match
    except Exception as e:
        clog(f"Schedule read error: {e}"); return False

def get_schedule_value(val="playlist"):
    hour = is_within_schedule()
    if hour:
        day = datetime.now().strftime("%Y-%m-%d")
        sched = load_schedule()
        h = hour.strip()
        if day in sched and h in sched[day] and val in sched[day][h]:
            return sched[day][h][val]
    return None

def get_playlist_name(pid):
    if not pid or not pid.strip(): return _("--- Click to set playlist ---")
    if pid in _playlist_name_cache:
        n, ts = _playlist_name_cache[pid]
        if time.time() - ts < 300: return n
    try:
        if "37i9dQ" in pid: name = _("Spotify's playlist")
        else: name = sp.playlist(pid).get("name", "")
        _playlist_name_cache[pid] = (name, time.time())
        return name
    except: return _("--- Unknown playlist ---")

# ── Playback ──────────────────────────────────────────────────────────────────
def play_music():
    global last_playlist, last_spotify_run, last_randomqueue, user_id, randomqueuefix_playlist, randomqueuefix_run
    try:
        if not target_device: return
        pid = get_schedule_value("playlist")
        if not pid: return
        rq = get_schedule_value("randomqueue")
        if rq and "37i9dQ" not in pid:
            tracks = []; offset = 0
            while True:
                try:
                    r = sp.playlist_items(pid, fields="items(item(uri)),total", additional_types=['track'], limit=50, offset=offset)
                    tracks.extend([i['item']['uri'] for i in r['items']])
                    offset += 50
                    if len(r['items']) < 50: break
                except: break
            uris = [t for t in tracks if ":local:" not in t]
            if not uris: return
            random.shuffle(uris)
            if not user_id: user_id = sp.me()['id']
            tp = sp.current_user_playlist_create(name=f"{get_playlist_name(pid)} (Random queue)", public=False)
            sp.current_user_unfollow_playlist(tp['id'])
            sp.playlist_add_items(tp['id'], uris[:100])
            randomqueuefix_playlist = tp['id']
            sp.start_playback(device_id=target_device["id"], context_uri=f"spotify:playlist:{tp['id']}")
        else:
            sp.start_playback(device_id=target_device["id"], context_uri=f"spotify:playlist:{pid}")
        last_playlist = pid; last_randomqueue = rq; last_spotify_run = False
        clog(f"Playing on {target_device['name']}. Playlist: {get_playlist_name(pid)}")
    except Exception as e: clog(f"Play error: {e}")

def pause_music():
    global last_spotify_run
    last_spotify_run = False
    if not sp_ready: return
    try:
        cp = cached_spotify_data("current_playback", True)
        if cp and cp.get("is_playing"): sp.pause_playback()
        clog("Playback paused.")
    except Exception as e: clog(f"Pause error: {e}")

def spotify_main():
    global last_playlist, target_device, randomqueuefix_playlist, randomqueuefix_run, last_randomqueue
    if is_paused: return
    if not sp or not sp_ready: initialize_sp()
    if is_within_schedule():
        try:
            cp = cached_spotify_data("current_playback")
            devs = cached_spotify_data("devices")
            target_device = None; active_device = None
            if devs and "devices" in devs:
                for d in devs["devices"]:
                    if config['DEVICE_NAME'].lower() in d["name"].lower(): target_device = d
                    if d.get("is_active"): active_device = d
            pid = get_schedule_value("playlist")
            rq = get_schedule_value("randomqueue")
            if (not cp) or (not cp.get("is_playing")) or (last_playlist != pid) or (target_device and active_device and target_device["id"] != active_device["id"]) or (last_randomqueue != rq):
                if pid: play_music()
            else:
                randomqueuefix_playlist = None; randomqueuefix_run = False
                if config.get('SKIP_EXPLICIT') and cp and cp.get("item", {}).get("explicit"):
                    try: sp.next_track(device_id=target_device["id"]); clog("Skipped explicit.")
                    except: pass
        except Exception as e: clog(f"Main loop error: {e}")
    else:
        pause_music()

def scheduler_loop():
    while True:
        try: spotify_main()
        except Exception as e: clog(f"Loop exception: {e}")
        time.sleep(30)

# ── Flask Routes ──────────────────────────────────────────────────────────────
@app.route('/')
def index():
    return render_template('index.html', ver=VER)

@app.route('/callback')
def callback():
    """Spotify OAuth callback - let spotipy handle it then redirect home."""
    # The SpotifyOAuth will handle the code exchange via its built-in server
    # But since we're using Flask, we handle it here
    code = request.args.get('code')
    if code and sp:
        try:
            sp.auth_manager.get_access_token(code)
            clog("OAuth callback successful.")
        except Exception as e:
            clog(f"OAuth error: {e}")
    return redirect('/')

@app.route('/api/status')
def api_status():
    global closest_start_time, last_endtime, empty_schedule
    info = {"paused": is_paused, "sp_ready": sp_ready, "username": username, "ver": VER,
            "device": config.get('DEVICE_NAME', ''), "schedule_status": ""}
    if is_paused:
        info["schedule_status"] = _("Automation is paused")
    elif empty_schedule:
        info["schedule_status"] = _("Schedule is empty")
    elif last_endtime and last_endtime > datetime.now():
        d = str(last_endtime - datetime.now()).split('.')[0]
        info["schedule_status"] = f"{_('Stops in ')}{d}"
    elif closest_start_time and closest_start_time >= datetime.now().time():
        d = str(datetime.combine(datetime.today(), closest_start_time) - datetime.now()).split('.')[0]
        info["schedule_status"] = f"{_('Plays in ')}{d}"
    else:
        info["schedule_status"] = _("out_of_schedule")
    return jsonify(info)

@app.route('/api/now-playing')
def api_now_playing():
    if not sp_ready:
        return jsonify({"error": "not_ready", "message": _("failed_to_fetch_data_console")})
    try:
        cp = cached_spotify_data("current_playback")
        devs = cached_spotify_data("devices")
        dev_name = _("No device")
        dev_list = []
        if devs and "devices" in devs:
            for d in devs["devices"]:
                if "web player" not in d.get("name","").lower():
                    dev_list.append({"name": d["name"], "active": d.get("is_active", False)})
                if d.get("is_active"): dev_name = d["name"]
        
        # Checklist logic
        checklist = []
        # 1. Spotify is running
        is_running = any("web player" not in d.get("name", "").lower() for d in devs.get("devices", [])) if devs else False
        checklist.append({
            "label": _("Spotify Running") if is_running else _("Spotify Is Turned Off"),
            "status": is_running
        })
        
        # 2. Device match
        target_name = config.get('DEVICE_NAME', '')
        device_found = any(d.get("name", "").lower() == target_name.lower() for d in devs.get("devices", [])) if devs else False
        checklist.append({
            "label": _("Device Found", device_name=target_name) if device_found else _("Device Not Found"),
            "status": device_found
        })
        
        # 3. Volume > 0%
        vol_ok = False
        curr_vol = 0
        if device_found:
            for d in devs.get("devices", []):
                if d.get("name", "").lower() == target_name.lower():
                    curr_vol = d.get("volume_percent", 0)
                    vol_ok = curr_vol > 0
                    break
        checklist.append({
            "label": _("Volume OK", volume=curr_vol) if vol_ok else _("Volume Increase", volume=curr_vol),
            "status": vol_ok
        })

        if cp and cp.get("item"):
            t = cp["item"]
            album_img = ""
            imgs = t.get("album", {}).get("images", [])
            if imgs: album_img = imgs[0]["url"]
            ctx = cp.get("context") or {}
            pl_uri = ctx.get("uri", "")
            pl_id = pl_uri.split(":")[-1] if "playlist" in pl_uri else ""
            pl_name = ""
            if pl_id:
                try: pl_name = get_playlist_name(pl_id)
                except: pl_name = ""
            if not pl_name:
                pl_name = t.get("album", {}).get("name", "")
            return jsonify({"playing": True, "is_playing": cp.get("is_playing", False),
                "title": t["name"], "artist": t["artists"][0]["name"],
                "album_image": album_img, "playlist": pl_name,
                "device": dev_name, "devices": dev_list, "checklist": checklist,
                "time_slot": last_schedule, "state": _("Playing") if cp.get("is_playing") else _("Paused")})
        return jsonify({"playing": False, "message": _("no_playback"), "devices": dev_list, "device": dev_name, "checklist": checklist})
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route('/api/recently-played')
def api_recently_played():
    if not sp_ready: return jsonify({"error": "not_ready"})
    try:
        r = sp.current_user_recently_played(limit=50)
        tracks = []
        for i in r['items']:
            pa = str(i['played_at']).split('.')[0].replace("Z","")
            utc = datetime.strptime(pa, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
            local = utc.astimezone(datetime.now().astimezone().tzinfo)
            tracks.append({"time": local.strftime("%Y-%m-%d %H:%M:%S"),
                          "title": i['track']['name'], "artist": i['track']['artists'][0]['name']})
        return jsonify({"tracks": tracks, "refreshed": datetime.now().strftime("%H:%M:%S")})
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route('/api/schedule/<date>')
def api_get_schedule(date):
    sched = load_schedule()
    day = sched.get(date, {})
    entries = []
    for tr, ed in sorted(day.items(), key=lambda x: parse_time(x[0].split("-")[0])):
        s, e = tr.split("-")
        pid = ed.get("playlist", "")
        entries.append({"time_range": tr, "start": s, "end": e,
                       "playlist_id": pid, "playlist_name": get_playlist_name(pid),
                       "randomqueue": ed.get("randomqueue", False)})
    # Also return which dates have schedules for calendar highlighting
    dates_with_schedule = [d for d, v in sched.items() if any(v.values())]
    return jsonify({"date": date, "entries": entries, "scheduled_dates": dates_with_schedule})

@app.route('/api/schedule/<date>', methods=['POST'])
def api_add_entry(date):
    d = request.json
    st, et = d.get("start",""), d.get("end","")
    if not is_valid_time(st) or not is_valid_time(et):
        return jsonify({"error": _("Error: Incorrect time format.")}), 400
    if parse_time(et) <= parse_time(st):
        return jsonify({"error": _("Error: End time must be later than start time.")}), 400
    sched = load_schedule()
    if date not in sched: sched[date] = {}
    tr = f"{st}-{et}"
    if tr in sched[date]: return jsonify({"error": _("Error: Entry already exists.")}), 400
    sched[date][tr] = {"playlist": "", "randomqueue": False}
    sched[date] = dict(sorted(sched[date].items(), key=lambda x: parse_time(x[0].split("-")[0])))
    save_schedule(sched)
    clog(f"Added entry {tr} for {date}")
    return jsonify({"ok": True})

@app.route('/api/schedule/<date>/<path:time_range>', methods=['DELETE'])
def api_delete_entry(date, time_range):
    sched = load_schedule()
    if date in sched and time_range in sched[date]:
        del sched[date][time_range]
        save_schedule(sched)
        clog(f"Deleted {time_range} from {date}")
        return jsonify({"ok": True})
    return jsonify({"error": "Not found"}), 404

@app.route('/api/schedule/<date>/<path:time_range>', methods=['PUT'])
def api_update_entry(date, time_range):
    d = request.json
    sched = load_schedule()
    if date not in sched or time_range not in sched[date]:
        return jsonify({"error": "Not found"}), 404
    if "playlist" in d:
        pid = d["playlist"]
        if "open.spotify.com" in pid:
            m = re.search(r"playlist/(\w+)", pid)
            if m: pid = m.group(1)
        sched[date][time_range]["playlist"] = pid
        if "37i9dQ" in pid: sched[date][time_range]["randomqueue"] = False
    if "randomqueue" in d:
        sched[date][time_range]["randomqueue"] = d["randomqueue"]
    save_schedule(sched)
    return jsonify({"ok": True})

@app.route('/api/schedule/<date>/<path:time_range>/time', methods=['PUT'])
def api_edit_time(date, time_range):
    d = request.json
    st, et = d.get("start", ""), d.get("end", "")
    if not is_valid_time(st) or not is_valid_time(et):
        return jsonify({"error": _("Error: Incorrect time format.")}), 400
    if parse_time(et) <= parse_time(st):
        return jsonify({"error": _("Error: End time must be later than start time.")}), 400
    sched = load_schedule()
    if date not in sched or time_range not in sched[date]:
        return jsonify({"error": "Not found"}), 404
    new_tr = f"{st}-{et}"
    if new_tr != time_range and new_tr in sched[date]:
        return jsonify({"error": _("Error: Entry already exists.")}), 400
    entry_data = sched[date].pop(time_range)
    sched[date][new_tr] = entry_data
    sched[date] = dict(sorted(sched[date].items(), key=lambda x: parse_time(x[0].split("-")[0])))
    save_schedule(sched)
    clog(f"Edited time {time_range} → {new_tr} for {date}")
    return jsonify({"ok": True, "new_time_range": new_tr})

@app.route('/api/schedule/<date>/copy', methods=['POST'])
def api_copy_schedule(date, ):
    d = request.json
    days = d.get("days", 0)
    mode = d.get("mode", "days")  # "days" or "weekdays"
    sched = load_schedule()
    src = sched.get(date, {}).copy()
    base = datetime.strptime(date, "%Y-%m-%d").date()
    copied = 0
    if mode == "days":
        for i in range(1, days + 1):
            td = (base + timedelta(days=i)).strftime("%Y-%m-%d")
            sched[td] = {}
            for k, v in src.items(): sched[td][k] = v.copy()
            copied += 1
    else:
        wd = base.weekday(); tgt = base
        while copied < days:
            tgt += timedelta(days=1)
            if tgt.weekday() == wd:
                td = tgt.strftime("%Y-%m-%d")
                sched[td] = {}
                for k, v in src.items(): sched[td][k] = v.copy()
                copied += 1
    save_schedule(sched)
    return jsonify({"ok": True, "copied": copied})

@app.route('/api/playlists')
def api_playlists():
    if not sp_ready: return jsonify({"error": "not_ready"})
    try:
        pls = []; offset = 0
        while True:
            r = sp.current_user_playlists(limit=50, offset=offset)
            pls.extend([{"id": p['id'], "name": p['name'], "owner": p['owner']['display_name']} for p in r['items']])
            if len(r['items']) < 50: break
            offset += 50
        return jsonify({"playlists": pls})
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route('/api/devices')
def api_devices():
    if not sp_ready: return jsonify({"error": "not_ready"})
    try:
        devs = sp.devices()
        dl = [{"name": d["name"], "id": d["id"], "active": d.get("is_active", False)}
              for d in devs.get("devices", []) if "web player" not in d.get("name","").lower()]
        return jsonify({"devices": dl})
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route('/api/settings', methods=['GET'])
def api_get_settings():
    return jsonify({k: v for k, v in config.items()})

@app.route('/api/settings', methods=['POST'])
def api_save_settings():
    global config
    d = request.json
    if 'CLIENT_ID' in d and 'CLIENT_SECRET' in d:
        if not validate_credentials(d['CLIENT_ID'], d['CLIENT_SECRET']):
            return jsonify({"error": _("Couldn't save. Credentials are not valid.")}), 400
    for k in ['CLIENT_ID','CLIENT_SECRET','DEVICE_NAME','LANG']:
        if k in d: config[k] = d[k]
    for k in ['KILLSWITCH_ON','WEEKDAYS_ONLY','SKIP_EXPLICIT']:
        if k in d: config[k] = bool(d[k])
    save_config(config)
    config = load_config()
    initialize_sp()
    return jsonify({"ok": True, "message": _("Settings saved.")})

@app.route('/api/pause', methods=['POST'])
def api_pause():
    global is_paused
    is_paused = True
    pause_music()
    return jsonify({"ok": True})

@app.route('/api/resume', methods=['POST'])
def api_resume():
    global is_paused
    is_paused = False
    return jsonify({"ok": True})

@app.route('/api/toggle-pause', methods=['POST'])
def api_toggle():
    global is_paused
    is_paused = not is_paused
    if is_paused: pause_music()
    return jsonify({"ok": True, "paused": is_paused})

@app.route('/api/console')
def api_console():
    return jsonify({"lines": console_lines[-100:]})

@app.route('/api/export-playlist', methods=['POST'])
def api_export():
    if not sp_ready: return jsonify({"error": "not_ready"}), 400
    d = request.json; pid = d.get("playlist_id", "")
    if "open.spotify.com" in pid:
        m = re.search(r"playlist/(\w+)", pid); pid = m.group(1) if m else pid
    if "37i9dQ" in pid:
        return jsonify({"error": _("You cannot export Spotify's curated playlists due to API limitations.")}), 400
    try:
        tracks = []; offset = 0
        while True:
            r = sp.playlist_items(pid, fields="items(item(uri,name,artists(name))),total",
                                  additional_types=['track'], limit=50, offset=offset)
            for i in r['items']:
                t = i['item']
                if t: tracks.append({"uri": t['uri'], "name": t['name'],
                                     "artists": [a['name'] for a in t['artists']]})
            offset += 50
            if len(r['items']) < 50: break
        tracks = [t for t in tracks if ":local:" not in t.get("uri","")]
        pd = sp.playlist(pid)
        img_b64 = None
        try:
            for img in (pd.get("images") or []):
                if img.get("url"):
                    r = http_requests.get(img["url"], timeout=5)
                    if r.status_code == 200: img_b64 = base64.b64encode(r.content).decode(); break
        except: pass
        export = {"metadata": {"original_name": pd.get("name",""), "exported_by": "Spotify Scheduler",
                               "exported_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "image_b64": img_b64},
                  "tracks": tracks}
        return jsonify(export)
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route('/api/import-playlist', methods=['POST'])
def api_import():
    if not sp_ready: return jsonify({"error": "not_ready"}), 400
    try:
        d = request.json
        if not (d.get("metadata",{}).get("exported_by") == "Spotify Scheduler"):
            return jsonify({"error": _("This file was not exported by Spotify Scheduler.")}), 400
        tracks = d.get("tracks", [])
        name = d.get("name") or d["metadata"].get("original_name") or "Imported Playlist"
        uid = sp.me()['id']
        np = sp.current_user_playlist_create(name=name, public=False,
             description=f"Imported by Spotify Scheduler v4.0 on {datetime.now()}")
        uris = [t['uri'] for t in tracks if 'uri' in t]
        for i in range(0, len(uris), 100):
            sp.playlist_add_items(np['id'], uris[i:i+100])
        img = d["metadata"].get("image_b64")
        if img:
            try:
                ib = base64.b64decode(img)
                if len(ib) <= 256*1024: sp.playlist_upload_cover_image(np['id'], img)
            except: pass
        return jsonify({"ok": True, "message": _("Playlist imported successfully."), "count": len(uris)})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route('/api/auth/logout', methods=['POST'])
def api_logout():
    if os.path.exists(".cache"):
        os.remove(".cache")
        clog("Cache deleted (logged out).")
        initialize_sp()
    return jsonify({"ok": True})

# ── Start ─────────────────────────────────────────────────────────────────────
def open_browser():
    time.sleep(1.5)
    webbrowser.open("http://127.0.0.1:5000")

def is_already_running():
    try:
        # Try to ping the status endpoint to see if our app is already running
        r = http_requests.get("http://127.0.0.1:5000/api/status", timeout=0.5)
        return r.status_code == 200
    except:
        return False

def run_flask():
    app.run(host='127.0.0.1', port=5000, debug=False, use_reloader=False)

if __name__ == '__main__':
    # Check if app is already running
    if is_already_running():
        print("App is already running. Opening dashboard...")
        webbrowser.open("http://127.0.0.1:5000")
        sys.exit(0)

    init_schedule()
    initialize_sp()
    clog(f"Daniele's Scheduler v{VER} (Web)")
    clog(f"Data directory: {DATA_DIR}")
    
    # Start scheduler loop
    t_sched = threading.Thread(target=scheduler_loop, daemon=True)
    t_sched.start()
    
    # Start Flask in a separate thread
    t_flask = threading.Thread(target=run_flask, daemon=True)
    t_flask.start()
    
    # Automatically open browser on start
    t_browser = threading.Thread(target=open_browser, daemon=True)
    t_browser.start()
    
    # Run tray icon on main thread (blocking)
    setup_tray()
