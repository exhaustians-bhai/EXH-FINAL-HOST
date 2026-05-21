#!/usr/bin/env python3
"""
╔══════════════════════════════════════════╗
║      EXHAUST HOSTING — Bot Platform      ║
║   24/7 Python Bot Hosting | Ultra Pro    ║
╚══════════════════════════════════════════╝
Colored buttons  · User isolation  · Credit system
Force join       · Self-keepalive  · Crash watchdog
"""

import os, sys, asyncio, json, zipfile, shutil, subprocess
import time, signal, threading, http.server, urllib.request
from pathlib import Path

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters,
)
import psutil

# ══════════════════════════════════════════════════════════════
#  CONFIG
# ══════════════════════════════════════════════════════════════

BOT_TOKEN     = os.environ.get("BOT_TOKEN", "")
ADMIN_ID      = 7082733957
LOG_CHANNEL   = -1003608585339
FORCE_CHANNEL = "exhaustbots"
BOT_USERNAME  = ""

BOTS_DIR    = Path(__file__).parent / "bots"
UPLOADS_DIR = Path(__file__).parent / "uploads"
STATE_FILE  = Path(__file__).parent / "bots_state.json"
USERS_FILE  = Path(__file__).parent / "users_state.json"

BOTS_DIR.mkdir(exist_ok=True)
UPLOADS_DIR.mkdir(exist_ok=True)

# ══════════════════════════════════════════════════════════════
#  SELF-KEEPALIVE  (true 24/7 — works on ANY free hosting)
#
#  Auto-detects external URL from env vars:
#    SELF_URL              → set karo manually (recommended)
#    RENDER_EXTERNAL_URL   → Render pe auto-set hota hai
#    RAILWAY_PUBLIC_DOMAIN → Railway pe auto-set hota hai
#    KOYEB_PUBLIC_DOMAIN   → Koyeb pe auto-set hota hai
#    REPLIT_DOMAINS        → Replit pe auto-set hota hai
#
#  Agar koi bhi set nahi → localhost ping (basic fallback)
# ══════════════════════════════════════════════════════════════

_KA_PORT = int(os.environ.get("PORT", 8080))


def _detect_external_url() -> str | None:
    """Auto-detect this app's public URL from known platform env vars."""
    # Manual override — sabse reliable
    if os.environ.get("SELF_URL"):
        return os.environ["SELF_URL"].rstrip("/")
    # Render
    if os.environ.get("RENDER_EXTERNAL_URL"):
        return os.environ["RENDER_EXTERNAL_URL"].rstrip("/")
    # Railway
    if os.environ.get("RAILWAY_PUBLIC_DOMAIN"):
        return "https://" + os.environ["RAILWAY_PUBLIC_DOMAIN"].rstrip("/")
    # Koyeb
    if os.environ.get("KOYEB_PUBLIC_DOMAIN"):
        return "https://" + os.environ["KOYEB_PUBLIC_DOMAIN"].rstrip("/")
    # Replit
    domains = os.environ.get("REPLIT_DOMAINS", "")
    if domains:
        first = domains.split(",")[0].strip()
        if first:
            return "https://" + first
    return None


class _HealthHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(
            b'{"status":"ok","service":"EXHAUST HOSTING","uptime":"24/7"}'
        )
    def log_message(self, *args): pass


def start_keepalive():
    """
    1. HTTP health server chalata hai (platform ki nazar mein port active)
    2. Bahari URL detect karke ping karta hai — platform ko lagta hai traffic aa raha hai
    3. Har 4 min pe ping → free tier pe bhi kabhi sleep nahi aayega
    """
    server_started = False
    try:
        srv = http.server.HTTPServer(("0.0.0.0", _KA_PORT), _HealthHandler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        server_started = True
        print(f"✅ Health server :{_KA_PORT}", flush=True)
    except Exception as e:
        print(f"[KA] Health server port {_KA_PORT} busy ({e}) — ping only mode", flush=True)

    ext_url = _detect_external_url()
    local_url = f"http://localhost:{_KA_PORT}/"

    if ext_url:
        ping_url = ext_url + "/"
        print(f"✅ External keepalive URL: {ping_url}", flush=True)
    else:
        ping_url = local_url
        print(f"⚠️  No external URL found — using localhost ping", flush=True)
        print(f"   Tip: SELF_URL env var set karo apne app ke URL se!", flush=True)

    def _ping():
        time.sleep(30)  # Startup ke baad 30s wait
        while True:
            try:
                req = urllib.request.Request(
                    ping_url,
                    headers={"User-Agent": "EXHAUST-HOSTING-Keepalive/1.0"},
                )
                urllib.request.urlopen(req, timeout=15)
            except Exception:
                # External fail hone par localhost try karo
                try:
                    urllib.request.urlopen(local_url, timeout=5)
                except Exception:
                    pass
            time.sleep(240)  # 4 min

    threading.Thread(target=_ping, daemon=True).start()
    mode = f"external ({ext_url})" if ext_url else "localhost (fallback)"
    print(f"✅ Self-ping keepalive ON — every 4 min → {mode}", flush=True)


# ══════════════════════════════════════════════════════════════
#  PLANS
# ══════════════════════════════════════════════════════════════

PLANS: dict[str, dict] = {
    "free":      {"limit": 4,  "price": 0,   "label": "Free",      "emoji": "🆓"},
    "starter":   {"limit": 6,  "price": 100,  "label": "Starter",   "emoji": "🥉"},
    "pro":       {"limit": 15, "price": 200,  "label": "Pro",       "emoji": "🥈"},
    "ultra":     {"limit": 50, "price": 300,  "label": "Ultra",     "emoji": "🥇"},
    "unlimited": {"limit": -1, "price": 500,  "label": "Unlimited", "emoji": "💎"},
}

# ══════════════════════════════════════════════════════════════
#  STATE
# ══════════════════════════════════════════════════════════════

running_bots: dict = {}
users_db: dict = {
    "all_users":      [],
    "bot_locked":     False,
    "owner_username": "exhaustbots",
    "updates_channel": "",
    "force_channel":  FORCE_CHANNEL,
    "plans":          {},
    "payment_info":   "UPI ID ya QR scan karo.\nPayment ke baad screenshot + User ID bhejo owner ko.",
    "payment_qr_id":  "",
    "subscribed":     [],
}
crash_notifications: list = []

# ══════════════════════════════════════════════════════════════
#  BUTTON HELPERS  (colored — Bot API 9.4 / PTB v22.7)
# ══════════════════════════════════════════════════════════════

def btn_primary(text: str, cbd: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text, callback_data=cbd, style="primary")

def btn_success(text: str, cbd: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text, callback_data=cbd, style="success")

def btn_danger(text: str, cbd: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text, callback_data=cbd, style="danger")

def btn_plain(text: str, cbd: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text, callback_data=cbd)

def btn_url(text: str, url: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text, url=url)

def btn_deeplink(text: str, action: str) -> InlineKeyboardButton:
    """Deep-link button — opens a fresh /start message."""
    return InlineKeyboardButton(text, url=f"https://t.me/{BOT_USERNAME}?start={action}")

def back_kb(action: str = "menu") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[btn_primary("🏠 Main Menu", f"nav_{action}")]])

# ══════════════════════════════════════════════════════════════
#  PERSISTENCE
# ══════════════════════════════════════════════════════════════

def load_state():
    global running_bots
    if not STATE_FILE.exists():
        return
    try:
        for bot_id, info in json.loads(STATE_FILE.read_text()).items():
            running_bots[bot_id] = {
                "name":         info.get("name", bot_id),
                "type":         info.get("type", "unknown"),
                "path":         info.get("path", ""),
                "pid":          None, "process": None, "start_time": None,
                "upload_time":  info.get("upload_time"),
                "auto_restart": info.get("auto_restart", True),
                "uploaded_by":  info.get("uploaded_by", 0),
                "was_running":  info.get("was_running", False),
                "crash_count":  info.get("crash_count", 0),
            }
    except Exception as e:
        print(f"[STATE] {e}", flush=True)
        running_bots = {}


def load_users():
    global users_db
    if USERS_FILE.exists():
        try:
            users_db.update(json.loads(USERS_FILE.read_text()))
        except Exception:
            pass


def save_state():
    STATE_FILE.write_text(json.dumps({
        bid: {
            "name": i["name"], "type": i["type"], "path": i["path"],
            "start_time": i.get("start_time"), "upload_time": i.get("upload_time"),
            "auto_restart": i.get("auto_restart", True),
            "uploaded_by": i.get("uploaded_by", 0),
            "was_running": get_status(bid) == "running",
            "crash_count": i.get("crash_count", 0),
        }
        for bid, i in running_bots.items()
    }, indent=2))


def save_users():
    USERS_FILE.write_text(json.dumps(users_db, indent=2))


def register_user(uid: int):
    if str(uid) not in users_db["all_users"]:
        users_db["all_users"].append(str(uid))
    users_db.setdefault("plans", {}).setdefault(str(uid), {"plan": "free", "since": time.time()})
    save_users()

# ══════════════════════════════════════════════════════════════
#  AUTH & PLANS
# ══════════════════════════════════════════════════════════════

def is_admin(uid: int) -> bool:
    return uid == ADMIN_ID

def get_user_plan(uid: int) -> str:
    if is_admin(uid): return "unlimited"
    return users_db.get("plans", {}).get(str(uid), {}).get("plan", "free")

def get_bot_limit(uid: int) -> int:
    return PLANS[get_user_plan(uid)]["limit"]

def get_user_bot_count(uid: int) -> int:
    return sum(1 for i in running_bots.values() if i.get("uploaded_by") == uid)

def can_upload(uid: int) -> bool:
    lim = get_bot_limit(uid)
    return lim == -1 or get_user_bot_count(uid) < lim

def set_user_plan(uid: int, plan: str):
    users_db.setdefault("plans", {})[str(uid)] = {"plan": plan, "since": time.time()}
    save_users()

def is_subscribed(uid: int) -> bool:
    if is_admin(uid): return True
    if not users_db.get("bot_locked", False): return True
    return str(uid) in users_db.get("subscribed", [])

def owns_bot(uid: int, bot_id: str) -> bool:
    if is_admin(uid): return True
    return running_bots.get(bot_id, {}).get("uploaded_by") == uid

# ══════════════════════════════════════════════════════════════
#  FORCE JOIN
# ══════════════════════════════════════════════════════════════

async def check_force_join(uid: int, bot) -> bool:
    if is_admin(uid): return True
    fc = users_db.get("force_channel", "")
    if not fc: return True
    try:
        m = await bot.get_chat_member(chat_id=f"@{fc}", user_id=uid)
        return m.status not in ("left", "kicked", "banned")
    except Exception:
        return True

def force_join_kb() -> InlineKeyboardMarkup:
    fc = users_db.get("force_channel", FORCE_CHANNEL)
    return InlineKeyboardMarkup([
        [btn_success("✅ Join Channel", f"https://t.me/{fc}")._replace()],
        [btn_primary("🔄 I Joined — Check", "nav_menu")],
    ])

# ══════════════════════════════════════════════════════════════
#  PROCESS MANAGEMENT
# ══════════════════════════════════════════════════════════════

def get_status(bot_id: str) -> str:
    if bot_id not in running_bots: return "unknown"
    proc = running_bots[bot_id].get("process")
    if proc is not None:
        if proc.poll() is None: return "running"
        running_bots[bot_id]["process"] = None
        running_bots[bot_id]["pid"] = None
    return "stopped"


def start_bot(bot_id: str) -> tuple[bool, str]:
    if bot_id not in running_bots: return False, "Bot nahi mila."
    info = running_bots[bot_id]
    p = Path(info["path"])
    if not p.exists(): return False, "File delete ho gayi."
    if get_status(bot_id) == "running": return False, "Already chal raha hai."
    if info["type"] == "single":
        cmd, cwd = [sys.executable, str(p)], str(p.parent)
    else:
        main = p / "main.py"
        if not main.exists():
            py = list(p.glob("*.py"))
            if not py: return False, "main.py nahi mili."
            main = py[0]
        cmd, cwd = [sys.executable, str(main)], str(p)
    try:
        lf = open(BOTS_DIR / f"{bot_id}.log", "a")
        lf.write(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] ══ BOT STARTED ══\n")
        lf.flush()
        _BLOCKED = {"BOT_TOKEN", "SESSION_SECRET", "DATABASE_URL", "REPLIT_DB_URL"}
        env = {k: v for k, v in os.environ.items() if k not in _BLOCKED}
        proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=lf, stderr=lf, preexec_fn=os.setsid)
        running_bots[bot_id].update(process=proc, pid=proc.pid, start_time=time.time())
        save_state()
        return True, f"Started — PID {proc.pid}"
    except Exception as e:
        return False, f"Error: {e}"


def stop_bot(bot_id: str) -> tuple[bool, str]:
    if bot_id not in running_bots: return False, "Bot nahi mila."
    proc = running_bots[bot_id].get("process")
    if proc is None or proc.poll() is not None:
        running_bots[bot_id].update(process=None, pid=None)
        return False, "Pehle se band hai."
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        try: proc.wait(timeout=5)
        except subprocess.TimeoutExpired: os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        running_bots[bot_id].update(process=None, pid=None)
        save_state()
        return True, "Bot band ho gaya."
    except Exception as e:
        return False, f"Error: {e}"


def restart_bot(bot_id: str) -> tuple[bool, str]:
    stop_bot(bot_id)
    time.sleep(0.8)
    running_bots[bot_id]["auto_restart"] = True
    return start_bot(bot_id)


def get_logs(bot_id: str, n: int = 30) -> str:
    lf = BOTS_DIR / f"{bot_id}.log"
    if not lf.exists(): return "(no logs)"
    try:
        lines = lf.read_text(errors="replace").splitlines()
        return "\n".join(lines[-n:] if len(lines) > n else lines)
    except Exception as e:
        return f"(error: {e})"


def fmt_uptime(s: float) -> str:
    s = int(s)
    if s < 60:   return f"{s}s"
    if s < 3600: return f"{s//60}m {s%60}s"
    return f"{s//3600}h {(s%3600)//60}m"

# ══════════════════════════════════════════════════════════════
#  CRASH WATCHDOG
# ══════════════════════════════════════════════════════════════

_crash_ts: dict[str, list[float]] = {}
_CRASH_WIN, _CRASH_MAX = 60, 5


def watchdog_loop():
    while True:
        try:
            for bid, info in list(running_bots.items()):
                if not info.get("auto_restart", True): continue
                proc = info.get("process")
                if proc is None or proc.poll() is None: continue

                code  = proc.returncode
                uid   = info.get("uploaded_by", 0)
                running_bots[bid].update(process=None, pid=None)
                running_bots[bid]["crash_count"] = running_bots[bid].get("crash_count", 0) + 1

                now = time.time()
                ts  = _crash_ts.setdefault(bid, [])
                ts.append(now)
                _crash_ts[bid] = [t for t in ts if now - t < _CRASH_WIN]
                recent = len(_crash_ts[bid])

                if recent >= _CRASH_MAX:
                    running_bots[bid]["auto_restart"] = False
                    running_bots[bid]["was_running"]  = False
                    _crash_ts.pop(bid, None)
                    save_state()
                    print(f"[WATCHDOG] {bid} crash-loop → disabled", flush=True)
                    if uid:
                        crash_notifications.append({
                            "uid": int(uid), "name": info["name"], "bid": bid,
                            "code": code, "log": get_logs(bid, 20), "loop": True,
                        })
                    continue

                print(f"[WATCHDOG] {bid} crash #{recent} → restarting", flush=True)
                if uid:
                    crash_notifications.append({
                        "uid": int(uid), "name": info["name"], "bid": bid,
                        "code": code, "log": get_logs(bid, 15), "loop": False,
                    })
                ok, msg = start_bot(bid)
                print(f"[WATCHDOG] {msg}", flush=True)
        except Exception as e:
            print(f"[WATCHDOG] {e}", flush=True)
        time.sleep(10)


def auto_start_bots() -> int:
    if os.environ.get("DISABLE_AUTOSTART", "").strip() in ("1", "true", "yes"):
        print("⚠️  DISABLE_AUTOSTART — skipping.", flush=True); return 0
    n = 0
    for bid, info in running_bots.items():
        if info.get("was_running") or info.get("auto_restart", True):
            ok, msg = start_bot(bid)
            if ok: n += 1
            print(f"[AUTOSTART] {bid}: {msg}", flush=True)
    return n


async def send_crash_notifications(ctx: ContextTypes.DEFAULT_TYPE):
    while crash_notifications:
        n = crash_notifications.pop(0)
        uid = n.get("uid")
        if not uid: continue
        log = n.get("log", "").strip()
        if len(log) > 900: log = "…" + log[-900:]
        loop = n.get("loop", False)
        try:
            await ctx.bot.send_message(
                chat_id=uid,
                text=(
                    f"{'🔴 Crash Loop — Auto-Restart OFF' if loop else '⚠️ Bot Crashed & Restarted'}\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"📛 *{n['name']}*\n"
                    f"🆔 `{n['bid']}`\n"
                    f"💥 Exit: `{n.get('code','?')}`\n"
                    + ("🛑 Auto-restart DISABLED — code fix karo.\n" if loop else "🔄 Auto-restarted ✅\n")
                    + f"━━━━━━━━━━━━━━━━━━━━\n```\n{log or '(empty)'}\n```"
                ),
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [btn_primary("📋 View Logs", f"logs_{n['bid']}"),
                     btn_success("🔄 Restart", f"restart_{n['bid']}") if loop else btn_plain("", "noop")]
                ]),
            )
        except Exception: pass

# ══════════════════════════════════════════════════════════════
#  BOT LIST BUILDER
# ══════════════════════════════════════════════════════════════

def build_bot_list(uid: int) -> tuple[str | None, list | None]:
    bots = {bid: i for bid, i in running_bots.items()
            if is_admin(uid) or i.get("uploaded_by") == uid}
    if not bots: return None, None

    plan    = PLANS[get_user_plan(uid)]
    used    = get_user_bot_count(uid)
    lim     = plan["limit"]
    ls      = "∞" if lim == -1 else str(lim)
    label   = "All Bots" if is_admin(uid) else "My Bots"

    txt = f"💎 *{label}*   {plan['emoji']} `{used}/{ls}`\n{'━'*22}\n\n"
    kb  = []
    for bid, info in bots.items():
        st  = get_status(bid)
        em  = "🟢" if st == "running" else "🔴"
        up  = fmt_uptime(time.time() - info["start_time"]) if st == "running" and info.get("start_time") else "—"
        own = f"  👤`{info.get('uploaded_by','?')}`" if is_admin(uid) else ""
        cc  = info.get("crash_count", 0)
        crash_note = f"  💥×{cc}" if cc > 0 else ""
        txt += f"{em} *{info['name']}*{own}{crash_note}\n   ⏱ `{up}`  ·  `{bid}`\n\n"
        row = []
        if st == "running":
            row.append(btn_danger("⏹ Stop", f"toggle_{bid}"))
        else:
            row.append(btn_success("▶️ Start", f"toggle_{bid}"))
        row.append(btn_primary("🔄 Restart", f"restart_{bid}"))
        row.append(btn_plain("📋 Logs", f"logs_{bid}"))
        row.append(btn_danger("🗑", f"delete_{bid}"))
        kb.append(row)
    kb.append([btn_primary("🏠 Main Menu", "nav_menu")])
    return txt, kb

# ══════════════════════════════════════════════════════════════
#  MENUS
# ══════════════════════════════════════════════════════════════

def user_menu(uid: int) -> InlineKeyboardMarkup:
    ch  = users_db.get("updates_channel", "")
    rows =