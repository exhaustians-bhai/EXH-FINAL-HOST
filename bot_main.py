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

BOT_TOKEN     = os.environ.get("BOT_TOKEN", "8898666736:AAEUXN8pgeYpDLkMFmNK1YO0JZh_LUTUxfM")
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
#  SELF-KEEPALIVE  (built-in 24/7 — no external pinger needed)
# ══════════════════════════════════════════════════════════════

_KA_PORT = int(os.environ.get("PORT", 8080))


class _HealthHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"status":"ok","service":"EXHAUST HOSTING"}')
    def log_message(self, *args): pass


def start_keepalive():
    """HTTP health-check server + self-ping every 4 min → 24/7 uptime."""
    try:
        srv = http.server.HTTPServer(("0.0.0.0", _KA_PORT), _HealthHandler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        print(f"✅ Health server :{_KA_PORT}", flush=True)
    except Exception as e:
        print(f"[KA] Health server failed: {e}", flush=True)

    def _ping():
        while True:
            time.sleep(240)
            try:
                urllib.request.urlopen(f"http://localhost:{_KA_PORT}/", timeout=10)
            except Exception:
                pass
    threading.Thread(target=_ping, daemon=True).start()
    print("✅ Self-ping keepalive active (every 4 min)", flush=True)


# ══════════════════════════════════════════════════════════════
#  PLANS
# ══════════════════════════════════════════════════════════════

PLANS: dict = {
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
        [btn_url("✅ Join Channel", f"https://t.me/{fc}")],
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


def start_bot(bot_id: str) -> tuple:
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


def stop_bot(bot_id: str) -> tuple:
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


def restart_bot(bot_id: str) -> tuple:
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

_crash_ts: dict = {}
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

def build_bot_list(uid: int) -> tuple:
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
    rows = [
        [btn_primary("🚀 Upload Bot", "nav_upload"),    btn_primary("💎 My Bots", "nav_bots")],
        [btn_plain("💳 My Plan", "nav_myplan"),         btn_success("🛒 Buy Credits", "nav_buy")],
        [btn_plain("⚡ Speed Test", "nav_speed"),        btn_plain("👻 Support", "nav_support")],
    ]
    if ch:
        rows.insert(0, [btn_url(f"📣 Updates Channel ↗", f"https://t.me/{ch.lstrip('@')}")])
    return InlineKeyboardMarkup(rows)


def admin_menu() -> InlineKeyboardMarkup:
    locked = users_db.get("bot_locked", False)
    return InlineKeyboardMarkup([
        [btn_primary("📊 Dashboard", "nav_dashboard"),  btn_primary("💎 All Bots", "nav_bots")],
        [btn_primary("👥 User Manager", "nav_users"),   btn_success("🔢 Running Now", "nav_running")],
        [btn_primary("📣 Broadcast", "nav_broadcast"),  btn_primary("📋 Plans & Credits", "nav_buy")],
        [btn_danger("🔒 Lock Bot", "nav_lock") if not locked else btn_success("🔓 Unlock Bot", "nav_lock"),
         btn_plain("⚙️ Settings", "nav_settings")],
    ])


def get_menu(uid: int) -> InlineKeyboardMarkup:
    return admin_menu() if is_admin(uid) else user_menu(uid)

# ══════════════════════════════════════════════════════════════
#  NAV CALLBACK ROUTER
# ══════════════════════════════════════════════════════════════

async def nav_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handles all nav_ callback actions (inline buttons on existing message)."""
    q    = update.callback_query
    user = q.from_user
    await q.answer()
    register_user(user.id)
    action = q.data[4:]  # strip "nav_"

    if not is_subscribed(user.id):
        await q.answer("🔒 Bot locked!", show_alert=True); return

    if not await check_force_join(user.id, ctx.bot):
        fc = users_db.get("force_channel", FORCE_CHANNEL)
        await q.answer(f"⚠️ Pehle @{fc} join karo!", show_alert=True); return

    # ── Main menu ──
    if action == "menu":
        plan  = PLANS[get_user_plan(user.id)]
        used  = get_user_bot_count(user.id)
        lim   = plan["limit"]
        ls    = "∞" if lim == -1 else str(lim)
        txt   = _welcome_text(user.first_name, plan, used, ls)
        try:
            await q.edit_message_text(txt, parse_mode="Markdown", reply_markup=get_menu(user.id))
        except Exception: pass

    # ── My Bots ──
    elif action == "bots":
        txt, kb = build_bot_list(user.id)
        if txt is None:
            try:
                await q.edit_message_text(
                    "📂 *No Bots Yet*\n\nFile upload karo!",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup([[btn_primary("🚀 Upload Now", "nav_upload")]]),
                )
            except Exception: pass
            return
        try: await q.edit_message_text(txt, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
        except Exception: pass

    # ── Upload ──
    elif action == "upload":
        plan = PLANS[get_user_plan(user.id)]
        used = get_user_bot_count(user.id)
        lim  = plan["limit"]
        ls   = "∞" if lim == -1 else str(lim)
        can  = can_upload(user.id)
        rows = []
        if not can: rows.append([btn_success("🛒 Upgrade Plan", "nav_buy")])
        rows.append([btn_primary("🏠 Menu", "nav_menu")])
        try:
            await q.edit_message_text(
                f"🚀 *Upload Your Bot*\n{'━'*20}\n\n"
                f"{plan['emoji']} Plan: *{plan['label']}*  `{used}/{ls}` slots\n\n"
                + ("❌ *Slot full — upgrade karo!*\n\n" if not can else "")
                + "🐍 *Single `.py` File:*\n  Direct file bhejo\n\n"
                  "📦 *ZIP Package:*\n  `main.py` andar hona chahiye\n\n"
                  "🌐 Python 3.11  ·  🔄 24/7 Auto-restart  ·  🔔 Crash alerts\n\n"
                  "⬇️ *File bhejo*",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(rows),
            )
        except Exception: pass

    # ── My Plan ──
    elif action == "myplan":
        pk   = get_user_plan(user.id)
        plan = PLANS[pk]
        used = get_user_bot_count(user.id)
        lim  = plan["limit"]
        ls   = "∞" if lim == -1 else str(lim)
        pd   = users_db.get("plans", {}).get(str(user.id), {})
        since = time.strftime("%d %b %Y", time.localtime(pd["since"])) if pd.get("since") else "—"
        apl  = "\n".join(
            f"  {'▶' if k == pk else '  '} {v['emoji']} *{v['label']}* — "
            + (f"₹{v['price']}" if v["price"] else "Free")
            + f"  ({v['limit'] if v['limit'] != -1 else '∞'} bots)"
            for k, v in PLANS.items()
        )
        try:
            await q.edit_message_text(
                f"💳 *My Plan*\n{'━'*20}\n\n"
                f"{plan['emoji']} *{plan['label']}*\n"
                f"📊 Bots: `{used}/{ls}`\n"
                f"📅 Since: `{since}`\n"
                f"🆔 ID: `{user.id}`\n\n"
                f"*All Plans:*\n{apl}",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [btn_success("🛒 Upgrade Plan", "nav_buy")],
                    [btn_primary("🏠 Menu", "nav_menu")],
                ]),
            )
        except Exception: pass

    # ── Buy Credits ──
    elif action == "buy":
        await _show_buy_menu(q, ctx, user.id)

    # ── Speed ──
    elif action == "speed":
        t1  = time.time()
        await asyncio.sleep(0)
        lat = (time.time() - t1) * 1000
        cpu = psutil.cpu_percent(interval=0.3)
        mem = psutil.virtual_memory()
        try:
            await q.edit_message_text(
                f"⚡ *Speed Test*\n{'━'*20}\n"
                f"🏓 Latency: `{lat:.1f} ms`\n"
                f"💻 CPU: `{cpu:.1f}%`\n"
                f"🧠 Free RAM: `{mem.available/1024**2:.1f} MB`\n"
                f"🟢 Status: `24/7 Online`",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[btn_primary("🏠 Menu", "nav_menu")]]),
            )
        except Exception: pass

    # ── Support ──
    elif action == "support":
        owner = users_db.get("owner_username", "")
        rows  = []
        if owner: rows.append([btn_url(f"💬 @{owner}", f"https://t.me/{owner}")])
        rows.append([btn_primary("🏠 Menu", "nav_menu")])
        try:
            await q.edit_message_text(
                "👻 *Support*\n━━━━━━━━━━━━━━━━━\n"
                + (f"Contact: @{owner}" if owner else "Owner set nahi."),
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(rows),
            )
        except Exception: pass

    # ─── ADMIN-ONLY BELOW ────────────────────────────────────

    elif action == "dashboard":
        if not is_admin(user.id): await q.answer("❌ Admin only!", show_alert=True); return
        await _show_dashboard(q)

    elif action == "users":
        if not is_admin(user.id): await q.answer("❌ Admin only!", show_alert=True); return
        await _show_users(q)

    elif action == "running":
        if not is_admin(user.id): await q.answer("❌ Admin only!", show_alert=True); return
        await _show_running(q, user.id)

    elif action == "broadcast":
        if not is_admin(user.id): await q.answer("❌ Admin only!", show_alert=True); return
        try:
            await q.edit_message_text(
                f"📣 *Broadcast*\n{'━'*20}\n"
                f"Users: `{len(users_db.get('all_users', []))}`\n\n"
                f"Command: `/broadcast <message>`\n\n"
                f"Supports text, emoji, markdown.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[btn_primary("🏠 Menu", "nav_menu")]]),
            )
        except Exception: pass

    elif action == "lock":
        if not is_admin(user.id): await q.answer("❌ Admin only!", show_alert=True); return
        locked = users_db.get("bot_locked", False)
        try:
            await q.edit_message_text(
                f"🔒 *Lock Bot*\n{'━'*20}\n"
                f"Status: `{'🔒 Locked' if locked else '🔓 Unlocked'}`\n"
                f"Subscribed: `{len(users_db.get('subscribed', []))}`\n\n"
                "Lock ON → sirf subscribed users access kar sakte hain.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [btn_success("🔓 Unlock", "do_unlock") if locked else btn_danger("🔒 Lock", "do_lock")],
                    [btn_primary("🏠 Menu", "nav_menu")],
                ]),
            )
        except Exception: pass

    elif action == "settings":
        if not is_admin(user.id): await q.answer("❌ Admin only!", show_alert=True); return
        fc    = users_db.get("force_channel", "—")
        owner = users_db.get("owner_username", "—")
        ch    = users_db.get("updates_channel", "—")
        has_qr = "✅" if users_db.get("payment_qr_id") else "❌"
        try:
            await q.edit_message_text(
                f"⚙️ *Settings*\n{'━'*20}\n\n"
                f"👻 Owner: `@{owner}`\n"
                f"📣 Updates Ch: `{ch}`\n"
                f"🔗 Force Join: `@{fc}`\n"
                f"💳 Payment QR: {has_qr}\n\n"
                f"*Change via commands:*\n"
                f"`/setowner @username`\n"
                f"`/setchannel @channel`\n"
                f"`/setforcechannel @ch` or `off`\n"
                f"`/setpayinfo <text>`\n"
                f"`/setqr` _(reply to QR photo)_",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[btn_primary("🏠 Menu", "nav_menu")]]),
            )
        except Exception: pass


async def _show_buy_menu(q, ctx, uid: int):
    pay  = users_db.get("payment_info", "Admin se contact karo.")
    qr   = users_db.get("payment_qr_id", "")
    pln  = "\n".join(
        f"  {v['emoji']} *{v['label']}* — "
        + (f"₹{v['price']}" if v["price"] else "FREE")
        + f"  |  {'∞' if v['limit']==-1 else v['limit']} bots"
        for _, v in PLANS.items()
    )
    txt  = (
        f"🛒 *Plans & Pricing*\n{'━'*22}\n\n{pln}\n\n"
        f"{'━'*22}\n💳 *Payment:*\n{pay}\n\n"
        "Plan select karo 👇"
    )
    kb = [[btn_success(f"{v['emoji']} {v['label']} — ₹{v['price']}", f"buyplan_{k}")]
          for k, v in PLANS.items() if v["price"] > 0]
    kb.append([btn_primary("🏠 Menu", "nav_menu")])
    if qr:
        try:
            await ctx.bot.send_photo(
                chat_id=q.message.chat.id, photo=qr,
                caption=txt, parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(kb),
            )
            return
        except Exception: pass
    try: await q.edit_message_text(txt, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
    except Exception: pass


async def _show_dashboard(q):
    total  = len(running_bots)
    run_c  = sum(1 for bid in running_bots if get_status(bid) == "running")
    mem    = psutil.virtual_memory()
    cpu    = psutil.cpu_percent(interval=0.5)
    pdata  = users_db.get("plans", {})
    plan_s = "  " + "  ".join(
        f"{PLANS[k]['emoji']}{sum(1 for v in pdata.values() if v.get('plan')==k)}"
        for k in PLANS
    )
    try:
        await q.edit_message_text(
            f"📊 *Dashboard*\n{'━'*22}\n\n"
            f"🤖 Bots: `{total}` total  🟢 `{run_c}` running\n"
            f"💻 CPU: `{cpu:.1f}%`\n"
            f"🧠 RAM: `{mem.used/1024**2:.0f}` / `{mem.total/1024**2:.0f} MB`  "
            f"(`{mem.percent:.0f}%`)\n\n"
            f"👥 Users: `{len(users_db.get('all_users', []))}`\n"
            f"📋 Plans: {plan_s}\n"
            f"🔒 Lock: `{'ON' if users_db.get('bot_locked') else 'OFF'}`\n"
            f"🔗 Force: `@{users_db.get('force_channel','—')}`\n\n"
            f"*Quick Commands:*\n"
            f"`/stopall` `/broadcast <msg>` `/listusers`\n"
            f"`/setplan <uid> <plan>` `/userinfo <uid>`",
            parse_mode="Markdown",
            reply_markup=admin_menu(),
        )
    except Exception: pass


async def _show_users(q):
    all_u = users_db.get("all_users", [])
    pdata = users_db.get("plans", {})
    lines = []
    for uid in all_u[-40:]:
        pk    = pdata.get(uid, {}).get("plan", "free")
        em    = PLANS.get(pk, PLANS["free"])["emoji"]
        bc    = sum(1 for i in running_bots.values() if str(i.get("uploaded_by")) == uid)
        lines.append(f"{em} `{uid}` — {bc} bots")
    more = f"\n_+{len(all_u)-40} more_" if len(all_u) > 40 else ""
    try:
        await q.edit_message_text(
            f"👥 *Users ({len(all_u)})*\n{'━'*22}\n\n"
            + "\n".join(lines) + more + "\n\n"
            + "Manage: `/setplan <uid> <plan>` `/userinfo <uid>`",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[btn_primary("🏠 Menu", "nav_menu")]]),
        )
    except Exception: pass


async def _show_running(q, uid: int):
    bots = {bid: info for bid, info in running_bots.items()
            if is_admin(uid) or info.get("uploaded_by") == uid}
    run  = [(bid, info) for bid, info in bots.items() if get_status(bid) == "running"]
    if not run:
        try:
            await q.edit_message_text(
                "🔢 *Running Bots*\n━━━━━━━━━━━━━━━━━\nKoi bot nahi chal raha.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[btn_primary("🏠 Menu", "nav_menu")]]),
            )
        except Exception: pass
        return
    txt = f"🔢 *Running Bots ({len(run)})*\n{'━'*22}\n\n"
    for bid, info in run:
        pid  = info.get("pid", "—")
        up   = fmt_uptime(time.time() - info["start_time"]) if info.get("start_time") else "—"
        cpu_ = mem_ = "—"
        try:
            pr   = psutil.Process(int(pid))
            cpu_ = f"{pr.cpu_percent(interval=0.1):.1f}%"
            mem_ = f"{pr.memory_info().rss/1024**2:.1f} MB"
        except Exception: pass
        own  = f"  👤`{info.get('uploaded_by','?')}`" if is_admin(uid) else ""
        txt += f"🟢 *{info['name']}*{own}\n   ⏱`{up}`  CPU`{cpu_}`  RAM`{mem_}`\n\n"
    try:
        await q.edit_message_text(
            txt, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[btn_primary("🏠 Menu", "nav_menu")]]),
        )
    except Exception: pass

# ══════════════════════════════════════════════════════════════
#  /start HANDLER
# ══════════════════════════════════════════════════════════════

def _welcome_text(name, plan, used, ls) -> str:
    return (
        f"✨ *Welcome, {name}!*\n\n"
        f"⚡ *EXHAUST HOSTING*\n"
        f"{'━'*22}\n"
        f"🔥 24/7 Python bot hosting\n"
        f"   🐍 Single `.py` bots\n"
        f"   📦 Multi-file `.zip` bots\n"
        f"🔄 Auto-restart on crash\n"
        f"🔔 Instant crash alerts\n"
        f"🔒 Full user isolation\n"
        f"{'━'*22}\n"
        f"{plan['emoji']} *{plan['label']} Plan*  —  `{used}/{ls}` bots used\n"
        f"👇 Choose an option:"
    )


async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    register_user(user.id)

    if not is_subscribed(user.id):
        owner   = users_db.get("owner_username", "")
        await update.message.reply_text(
            "🔒 *Bot Locked*\n\nSirf subscribed users access kar sakte hain."
            + (f"\n\n💬 Contact: @{owner}" if owner else ""),
            parse_mode="Markdown",
        )
        return

    if not await check_force_join(user.id, ctx.bot):
        fc = users_db.get("force_channel", FORCE_CHANNEL)
        await update.message.reply_text(
            f"⚠️ *Join Required!*\n\n"
            f"Bot use karne ke liye pehle join karo:\n"
            f"👉 @{fc}\n\n"
            f"Join ke baad *I Joined* button dabao.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [btn_url("✅ Join Channel", f"https://t.me/{fc}")],
                [btn_primary("🔄 I Joined — Check", "nav_menu")],
            ]),
        )
        return

    plan = PLANS[get_user_plan(user.id)]
    used = get_user_bot_count(user.id)
    lim  = plan["limit"]
    ls   = "∞" if lim == -1 else str(lim)
    await update.message.reply_text(
        _welcome_text(user.first_name, plan, used, ls),
        parse_mode="Markdown",
        reply_markup=get_menu(user.id),
    )

# ══════════════════════════════════════════════════════════════
#  CALLBACK HANDLER (action buttons)
# ══════════════════════════════════════════════════════════════

async def btn(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    user = q.from_user
    await q.answer()
    data = q.data
    register_user(user.id)

    # nav_ actions handled separately
    if data.startswith("nav_"):
        await nav_handler(update, ctx); return

    # ── Lock/Unlock ──
    if data == "do_lock":
        if not is_admin(user.id): await q.answer("❌ Admin only!", show_alert=True); return
        users_db["bot_locked"] = True; save_users()
        await q.answer("🔒 Bot locked!", show_alert=True)
        try: await q.edit_message_text("🔒 Bot is now *Locked*.", parse_mode="Markdown",
             reply_markup=InlineKeyboardMarkup([[btn_success("🔓 Unlock", "do_unlock"), btn_primary("🏠 Menu","nav_menu")]]))
        except Exception: pass

    elif data == "do_unlock":
        if not is_admin(user.id): await q.answer("❌ Admin only!", show_alert=True); return
        users_db["bot_locked"] = False; save_users()
        await q.answer("🔓 Bot unlocked!", show_alert=True)
        try: await q.edit_message_text("🔓 Bot is now *Unlocked*.", parse_mode="Markdown",
             reply_markup=InlineKeyboardMarkup([[btn_danger("🔒 Lock", "do_lock"), btn_primary("🏠 Menu","nav_menu")]]))
        except Exception: pass

    # ── Toggle start/stop ──
    elif data.startswith("toggle_"):
        bid = data[7:]
        if not is_subscribed(user.id): await q.answer("🔒 Locked!", show_alert=True); return
        if bid not in running_bots: await q.answer("❌ Not found!", show_alert=True); return
        if not owns_bot(user.id, bid): await q.answer("❌ Yeh bot tumhara nahi!", show_alert=True); return
        if get_status(bid) == "running":
            running_bots[bid]["auto_restart"] = False
            ok, msg = stop_bot(bid)
        else:
            running_bots[bid]["auto_restart"] = True
            ok, msg = start_bot(bid)
        await q.answer(msg, show_alert=True)
        txt, kb = build_bot_list(user.id)
        if txt:
            try: await q.edit_message_text(txt, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
            except Exception: pass

    # ── Restart ──
    elif data.startswith("restart_"):
        bid = data[8:]
        if not owns_bot(user.id, bid): await q.answer("❌ Yeh bot tumhara nahi!", show_alert=True); return
        if bid not in running_bots: await q.answer("❌ Not found!", show_alert=True); return
        ok, msg = restart_bot(bid)
        await q.answer(f"{'✅' if ok else '❌'} {msg}", show_alert=True)
        txt, kb = build_bot_list(user.id)
        if txt:
            try: await q.edit_message_text(txt, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
            except Exception: pass

    # ── Logs ──
    elif data.startswith("logs_"):
        bid = data[5:]
        if bid not in running_bots: await q.answer("❌ Not found!", show_alert=True); return
        if not owns_bot(user.id, bid): await q.answer("❌ Yeh bot tumhara nahi!", show_alert=True); return
        log = get_logs(bid, 25)
        try:
            await q.edit_message_text(
                f"📋 *Logs — {running_bots[bid]['name']}*\n\n```\n{log.strip() or '(empty)'}\n```",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [btn_primary("🔄 Refresh", f"logs_{bid}"), btn_primary("🔙 Back", "nav_bots")],
                ]),
            )
        except Exception: pass

    # ── Delete (confirm step) ──
    elif data.startswith("delete_"):
        bid = data[7:]
        if bid not in running_bots: await q.answer("❌ Not found!", show_alert=True); return
        if not owns_bot(user.id, bid): await q.answer("❌ Yeh bot tumhara nahi!", show_alert=True); return
        try:
            await q.edit_message_text(
                f"⚠️ *Delete Bot?*\n\n"
                f"*{running_bots[bid]['name']}*\n`{bid}`\n\n"
                "Yeh permanently delete ho jaayega!",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [btn_danger("🗑 Haan, Delete Karo!", f"confirm_del_{bid}"),
                     btn_success("❌ Cancel", "nav_bots")],
                ]),
            )
        except Exception: pass

    elif data.startswith("confirm_del_"):
        bid = data[12:]
        if not owns_bot(user.id, bid): await q.answer("❌ Yeh bot tumhara nahi!", show_alert=True); return
        if bid in running_bots:
            stop_bot(bid)
            info = running_bots.pop(bid)
            p    = Path(info["path"])
            if p.is_dir():    shutil.rmtree(p, ignore_errors=True)
            elif p.is_file():
                p.unlink(missing_ok=True)
                if p.parent != BOTS_DIR: shutil.rmtree(p.parent, ignore_errors=True)
            (BOTS_DIR / f"{bid}.log").unlink(missing_ok=True)
            save_state()
        await q.answer("✅ Deleted!", show_alert=True)
        txt, kb = build_bot_list(user.id)
        try:
            if txt:
                await q.edit_message_text(txt, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
            else:
                await q.edit_message_text(
                    "✅ *Bot deleted!*\n\nKoi bot nahi bacha.",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup([[btn_primary("🚀 Upload New", "nav_upload")]]),
                )
        except Exception: pass

    # ── Buy plan ──
    elif data.startswith("buyplan_"):
        pk   = data[8:]
        plan = PLANS.get(pk)
        if not plan: return
        owner = users_db.get("owner_username", "exhaustbots")
        txt  = (
            f"💳 *Payment — {plan['emoji']} {plan['label']}*\n{'━'*22}\n"
            f"💰 Price: *₹{plan['price']}*\n"
            f"🤖 Bots: `{'∞' if plan['limit']==-1 else plan['limit']}`\n\n"
            f"*Steps:*\n{users_db.get('payment_info', 'Admin se contact karo.')}\n\n"
            f"📸 Payment screenshot bhejo: @{owner}\n"
            f"💬 Apna ID: `{user.id}`\n\n"
            f"Admin verify karke plan activate karega."
        )
        kb = InlineKeyboardMarkup([
            [btn_url(f"💬 Contact @{owner}", f"https://t.me/{owner}")],
            [btn_primary("🔙 Back", "nav_buy")],
        ])
        try: await q.edit_message_text(txt, parse_mode="Markdown", reply_markup=kb)
        except Exception:
            try: await q.edit_message_caption(caption=txt, parse_mode="Markdown", reply_markup=kb)
            except Exception: pass

    elif data == "noop":
        pass

# ══════════════════════════════════════════════════════════════
#  DOCUMENT / PHOTO HANDLERS
# ══════════════════════════════════════════════════════════════

async def handle_document(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    register_user(user.id)
    if not is_subscribed(user.id): await update.message.reply_text("🔒 Access denied."); return
    if not await check_force_join(user.id, ctx.bot):
        fc = users_db.get("force_channel", FORCE_CHANNEL)
        await update.message.reply_text(
            f"⚠️ Pehle @{fc} join karo!",
            reply_markup=InlineKeyboardMarkup([[btn_url("✅ Join", f"https://t.me/{fc}")]]),
        ); return

    doc   = update.message.document
    fname = doc.file_name or "unknown"
    ext   = Path(fname).suffix.lower()

    if ext not in (".py", ".zip"):
        await update.message.reply_text(
            "❌ *Unsupported File!*\n\n✅ `.py` or `.zip` only\n🌐 Python 3.11",
            parse_mode="Markdown",
        ); return

    if not can_upload(user.id):
        plan = PLANS[get_user_plan(user.id)]
        await update.message.reply_text(
            f"❌ *Slot Full!*\n{'━'*20}\n"
            f"{plan['emoji']} *{plan['label']}* — `{get_user_bot_count(user.id)}/{plan['limit']}` used\n\n"
            "Upgrade karke zyada bots host karo!",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[btn_success("🛒 Upgrade", "nav_buy")]]),
        ); return

    msg = await update.message.reply_text("⏳ *Uploading...* Please wait", parse_mode="Markdown")
    try:
        fo     = await doc.get_file()
        bot_id = f"bot_{int(time.time())}_{user.id}"
        name   = Path(fname).stem

        if ext == ".py":
            dp = BOTS_DIR / bot_id; dp.mkdir(exist_ok=True)
            dest = dp / fname
            await fo.download_to_drive(str(dest))
            running_bots[bot_id] = {
                "name": name, "type": "single", "path": str(dest),
                "process": None, "pid": None, "start_time": None,
                "upload_time": time.time(), "auto_restart": True,
                "uploaded_by": user.id, "was_running": False, "crash_count": 0,
            }
        else:
            zp = UPLOADS_DIR / f"{bot_id}.zip"
            await fo.download_to_drive(str(zp))
            ep = BOTS_DIR / bot_id; ep.mkdir(exist_ok=True)
            with zipfile.ZipFile(zp, "r") as zf: zf.extractall(str(ep))
            zp.unlink(missing_ok=True)
            running_bots[bot_id] = {
                "name": name, "type": "zip", "path": str(ep),
                "process": None, "pid": None, "start_time": None,
                "upload_time": time.time(), "auto_restart": True,
                "uploaded_by": user.id, "was_running": False, "crash_count": 0,
            }

        save_state()
        plan = PLANS[get_user_plan(user.id)]
        used = get_user_bot_count(user.id)
        ls   = "∞" if plan["limit"] == -1 else str(plan["limit"])
        await log_to_channel(ctx, update, bot_id, name, ext.upper(), doc.file_size or 0)
        await msg.edit_text(
            f"✅ *Uploaded Successfully!*\n{'━'*22}\n"
            f"📛 *{name}*\n"
            f"🆔 `{bot_id}`\n"
            f"📄 `{'Single .py' if ext=='.py' else 'ZIP Package'}`\n"
            f"📏 `{(doc.file_size or 0)/1024:.1f} KB`\n"
            f"📊 Slots: `{used}/{ls}`\n"
            f"🔄 Auto-restart: `✅ 24/7`\n\n"
            f"▶️ Start karo!",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [btn_success("🚀 Start Now", f"toggle_{bot_id}"),
                 btn_primary("💎 My Bots", "nav_bots")],
            ]),
        )
    except Exception as e:
        await msg.edit_text(f"❌ *Upload Failed!*\n\n`{e}`", parse_mode="Markdown")


async def handle_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user    = update.effective_user
    caption = (update.message.caption or "").strip()
    if is_admin(user.id) and caption.startswith("/setqr"):
        users_db["payment_qr_id"] = update.message.photo[-1].file_id
        save_users()
        await update.message.reply_text("✅ Payment QR saved!")

# ══════════════════════════════════════════════════════════════
#  COMMANDS
# ══════════════════════════════════════════════════════════════

async def help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    register_user(update.effective_user.id)
    adm = is_admin(update.effective_user.id)
    txt = (
        "📖 *Commands*\n━━━━━━━━━━━━━━━━━\n"
        "*/start* — Main menu\n"
        "*/list* — My bots\n"
        "*/myplan* — My plan & slots\n"
        "*/listplans* — All plans & prices\n"
        "*/start\\_bot <id>* — Start\n"
        "*/stop\\_bot <id>* — Stop\n"
        "*/restart\\_bot <id>* — Restart\n"
        "*/logs <id>* — Last 30 log lines\n"
        "*/delete <id>* — Delete bot\n"
        "*/stats* — System stats\n"
    )
    if adm:
        txt += (
            "\n👑 *Admin Commands:*\n"
            "*/setplan <uid> <plan>*\n"
            "*/userinfo <uid>*\n"
            "*/broadcast <msg>*\n"
            "*/addsub /removesub <uid>*\n"
            "*/lock /unlock /stopall*\n"
            "*/setqr /setpayinfo <text>*\n"
            "*/setforcechannel @ch*\n"
            "*/setchannel /setowner*\n"
            "*/listusers*"
        )
    await update.message.reply_text(txt, parse_mode="Markdown")


async def list_bots_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; register_user(user.id)
    if not is_subscribed(user.id): await update.message.reply_text("🔒 Access denied."); return
    txt, kb = build_bot_list(user.id)
    if txt is None: await update.message.reply_text("📂 Koi bot nahi.\n\nFile bhejo!"); return
    await update.message.reply_text(txt, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))


async def myplan_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; register_user(user.id)
    pk   = get_user_plan(user.id); plan = PLANS[pk]
    used = get_user_bot_count(user.id); lim = plan["limit"]
    await update.message.reply_text(
        f"💳 *My Plan*\n━━━━━━━━━━━━━━━━━\n"
        f"{plan['emoji']} *{plan['label']}*\n"
        f"📊 `{used}/{'∞' if lim==-1 else lim}` bots used\n"
        f"👤 ID: `{user.id}`",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[btn_success("🛒 Upgrade", "nav_buy")]]),
    )


async def listplans_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    txt = "📋 *Plans*\n━━━━━━━━━━━━━━━━━\n\n" + "\n\n".join(
        f"{v['emoji']} *{v['label']}* — {'₹' + str(v['price']) if v['price'] else 'FREE'}\n"
        f"   📊 {'∞' if v['limit']==-1 else v['limit']} bots"
        for _, v in PLANS.items()
    )
    await update.message.reply_text(
        txt, parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[btn_success("🛒 Buy Now", "nav_buy")]]),
    )


def _check_own(update, uid, bot_id) -> bool:
    if bot_id not in running_bots: return False
    return owns_bot(uid, bot_id)


async def start_bot_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_subscribed(uid): await update.message.reply_text("🔒 Access denied."); return
    if not ctx.args: await update.message.reply_text("Usage: `/start_bot <id>`", parse_mode="Markdown"); return
    bid = ctx.args[0]
    if bid not in running_bots: await update.message.reply_text("❌ Bot not found."); return
    if not owns_bot(uid, bid): await update.message.reply_text("❌ Yeh bot tumhara nahi."); return
    ok, msg = start_bot(bid)
    await update.message.reply_text(f"{'✅' if ok else '❌'} {msg}")


async def stop_bot_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_subscribed(uid): await update.message.reply_text("🔒 Access denied."); return
    if not ctx.args: await update.message.reply_text("Usage: `/stop_bot <id>`", parse_mode="Markdown"); return
    bid = ctx.args[0]
    if bid not in running_bots: await update.message.reply_text("❌ Bot not found."); return
    if not owns_bot(uid, bid): await update.message.reply_text("❌ Yeh bot tumhara nahi."); return
    ok, msg = stop_bot(bid)
    await update.message.reply_text(f"{'✅' if ok else '❌'} {msg}")


async def restart_bot_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_subscribed(uid): await update.message.reply_text("🔒 Access denied."); return
    if not ctx.args: await update.message.reply_text("Usage: `/restart_bot <id>`", parse_mode="Markdown"); return
    bid = ctx.args[0]
    if bid not in running_bots: await update.message.reply_text("❌ Bot not found."); return
    if not owns_bot(uid, bid): await update.message.reply_text("❌ Yeh bot tumhara nahi."); return
    m = await update.message.reply_text("🔄 Restarting...")
    ok, res = restart_bot(bid)
    await m.edit_text(f"{'✅' if ok else '❌'} {res}")


async def logs_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_subscribed(uid): await update.message.reply_text("🔒 Access denied."); return
    if not ctx.args: await update.message.reply_text("Usage: `/logs <id>`", parse_mode="Markdown"); return
    bid = ctx.args[0]
    if bid not in running_bots: await update.message.reply_text("❌ Bot not found."); return
    if not owns_bot(uid, bid): await update.message.reply_text("❌ Yeh bot tumhara nahi."); return
    log = get_logs(bid, 30)
    await update.message.reply_text(
        f"📋 *Logs — {running_bots[bid]['name']}*\n\n```\n{log.strip() or '(empty)'}\n```",
        parse_mode="Markdown",
    )


async def delete_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_subscribed(uid): await update.message.reply_text("🔒 Access denied."); return
    if not ctx.args: await update.message.reply_text("Usage: `/delete <id>`", parse_mode="Markdown"); return
    bid = ctx.args[0]
    if bid not in running_bots: await update.message.reply_text("❌ Not found."); return
    if not owns_bot(uid, bid): await update.message.reply_text("❌ Yeh bot tumhara nahi."); return
    stop_bot(bid); info = running_bots.pop(bid); p = Path(info["path"])
    if p.is_dir(): shutil.rmtree(p, ignore_errors=True)
    elif p.is_file():
        p.unlink(missing_ok=True)
        if p.parent != BOTS_DIR: shutil.rmtree(p.parent, ignore_errors=True)
    (BOTS_DIR / f"{bid}.log").unlink(missing_ok=True)
    save_state()
    await update.message.reply_text(f"✅ `{bid}` deleted.", parse_mode="Markdown")


async def stats_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    register_user(update.effective_user.id)
    total = len(running_bots); run_c = sum(1 for b in running_bots if get_status(b) == "running")
    mem   = psutil.virtual_memory(); cpu = psutil.cpu_percent(interval=0.5)
    await update.message.reply_text(
        f"📊 *System Stats*\n━━━━━━━━━━━━━━━━━\n"
        f"🤖 Bots: `{total}` (🟢 {run_c})\n"
        f"💻 CPU: `{cpu:.1f}%`\n"
        f"🧠 RAM: `{mem.used/1024**2:.0f}/{mem.total/1024**2:.0f} MB`\n"
        f"👥 Users: `{len(users_db.get('all_users',[]))}`",
        parse_mode="Markdown",
    )


async def broadcast_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): await update.message.reply_text("❌ Admin only."); return
    if not ctx.args: await update.message.reply_text("Usage: `/broadcast <msg>`", parse_mode="Markdown"); return
    text = " ".join(ctx.args); ok = fail = 0
    for uid in users_db.get("all_users", []):
        try:
            await ctx.bot.send_message(int(uid), f"📣 *Broadcast*\n━━━━━━━━━━━━━━━━━\n{text}", parse_mode="Markdown")
            ok += 1
        except Exception: fail += 1
    await update.message.reply_text(f"📣 Done — ✅ `{ok}` | ❌ `{fail}`", parse_mode="Markdown")


async def addsub_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    if not ctx.args: await update.message.reply_text("Usage: `/addsub <uid>`", parse_mode="Markdown"); return
    uid = ctx.args[0]
    if uid not in users_db["subscribed"]: users_db["subscribed"].append(uid); save_users()
    await update.message.reply_text(f"✅ `{uid}` subscribed.", parse_mode="Markdown")


async def removesub_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    if not ctx.args: await update.message.reply_text("Usage: `/removesub <uid>`", parse_mode="Markdown"); return
    uid = ctx.args[0]
    if uid in users_db["subscribed"]: users_db["subscribed"].remove(uid); save_users()
    await update.message.reply_text(f"✅ `{uid}` removed.", parse_mode="Markdown")


async def lock_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    users_db["bot_locked"] = True; save_users(); await update.message.reply_text("🔒 Locked!")


async def unlock_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    users_db["bot_locked"] = False; save_users(); await update.message.reply_text("🔓 Unlocked!")


async def stopall_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    stopped = []; failed = []
    for bid in list(running_bots.keys()):
        ok, _ = stop_bot(bid); running_bots[bid]["was_running"] = False
        (stopped if ok else failed).append(bid)
    save_state()
    lines = ["🛑 *Stop All*\n━━━━━━━━━━━━━━━━━"]
    if stopped: lines.append("✅ Stopped:\n" + "\n".join(f"  `{b}`" for b in stopped))
    if failed:  lines.append("⚠️ Already off:\n" + "\n".join(f"  `{b}`" for b in failed))
    if not stopped and not failed: lines.append("ℹ️ No bots found.")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def setplan_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    if len(ctx.args) < 2:
        await update.message.reply_text(f"Usage: `/setplan <uid> <plan>`\nPlans: `{', '.join(PLANS)}`", parse_mode="Markdown"); return
    uid_s, pk = ctx.args[0], ctx.args[1].lower()
    if pk not in PLANS: await update.message.reply_text(f"❌ Invalid plan. Valid: `{', '.join(PLANS)}`", parse_mode="Markdown"); return
    set_user_plan(int(uid_s), pk); plan = PLANS[pk]
    await update.message.reply_text(f"✅ `{uid_s}` → *{plan['emoji']} {plan['label']}*", parse_mode="Markdown")
    try:
        await ctx.bot.send_message(
            int(uid_s),
            f"🎉 *Plan Upgraded!*\n━━━━━━━━━━━━━━━━━\n"
            f"{plan['emoji']} *{plan['label']}* activated!\n"
            f"📊 Bots: `{'∞' if plan['limit']==-1 else plan['limit']}`\n\n"
            f"Happy hosting! 🚀",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[btn_primary("🏠 Menu", "nav_menu")]]),
        )
    except Exception: pass


async def userinfo_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    if not ctx.args: await update.message.reply_text("Usage: `/userinfo <uid>`", parse_mode="Markdown"); return
    uid  = int(ctx.args[0]); pk = get_user_plan(uid); plan = PLANS[pk]
    pd   = users_db.get("plans", {}).get(str(uid), {})
    since = time.strftime("%d %b %Y", time.localtime(pd["since"])) if pd.get("since") else "—"
    bots  = [(b, i) for b, i in running_bots.items() if i.get("uploaded_by") == uid]
    blines = "\n".join(f"  {'🟢' if get_status(b)=='running' else '🔴'} `{b}` {i['name']}" for b, i in bots) or "  None"
    await update.message.reply_text(
        f"👤 *User Info*\n━━━━━━━━━━━━━━━━━\n"
        f"🆔 `{uid}`\n{plan['emoji']} *{plan['label']}*\n"
        f"📊 Bots: `{get_user_bot_count(uid)}`\n"
        f"📅 Since: `{since}`\n\n"
        f"*Bots:*\n{blines}\n\n"
        f"`/setplan {uid} <plan>`",
        parse_mode="Markdown",
    )


async def setqr_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    r = update.message.reply_to_message
    if r and r.photo:
        users_db["payment_qr_id"] = r.photo[-1].file_id; save_users()
        await update.message.reply_text("✅ Payment QR saved!")
    else:
        await update.message.reply_text("📸 QR photo bhejo → reply karo `/setqr` se", parse_mode="Markdown")


async def setpayinfo_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    if not ctx.args: await update.message.reply_text("Usage: `/setpayinfo <text>`", parse_mode="Markdown"); return
    users_db["payment_info"] = " ".join(ctx.args); save_users()
    await update.message.reply_text(f"✅ Payment info:\n\n{users_db['payment_info']}")


async def setforcechannel_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    if not ctx.args: await update.message.reply_text("Usage: `/setforcechannel @ch` or `off`"); return
    val = ctx.args[0].lstrip("@")
    if val.lower() == "off": users_db["force_channel"] = ""; save_users(); await update.message.reply_text("✅ Force join disabled.")
    else: users_db["force_channel"] = val; save_users(); await update.message.reply_text(f"✅ Force: @{val}")


async def setowner_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    if not ctx.args: await update.message.reply_text("Usage: `/setowner @username`"); return
    users_db["owner_username"] = ctx.args[0].lstrip("@"); save_users()
    await update.message.reply_text(f"✅ Owner: @{users_db['owner_username']}")


async def setchannel_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    if not ctx.args: await update.message.reply_text("Usage: `/setchannel @ch`"); return
    users_db["updates_channel"] = ctx.args[0]; save_users()
    await update.message.reply_text(f"✅ Channel: {users_db['updates_channel']}")


async def listusers_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    all_u = users_db.get("all_users", []); pd = users_db.get("plans", {})
    txt   = f"👥 *Users ({len(all_u)})*\n━━━━━━━━━━━━━━━━━\n"
    for uid in all_u[-50:]:
        pk  = pd.get(uid, {}).get("plan", "free")
        em  = PLANS.get(pk, PLANS["free"])["emoji"]
        bc  = sum(1 for i in running_bots.values() if str(i.get("uploaded_by")) == uid)
        txt += f"{em} `{uid}` — {bc} bots\n"
    if len(all_u) > 50: txt += f"\n_+{len(all_u)-50} more_"
    await update.message.reply_text(txt, parse_mode="Markdown")

# ══════════════════════════════════════════════════════════════
#  CHANNEL LOGGER
# ══════════════════════════════════════════════════════════════

async def log_to_channel(ctx, update, bot_id, name, ftype, fsize):
    user  = update.effective_user
    uname = f"@{user.username}" if user.username else f"[{user.first_name}](tg://user?id={user.id})"
    plan  = PLANS[get_user_plan(user.id)]
    try:
        await ctx.bot.forward_message(LOG_CHANNEL, update.effective_chat.id, update.message.message_id)
        await ctx.bot.send_message(
            LOG_CHANNEL,
            f"📦 *New Bot Uploaded*\n\n"
            f"👤 {uname} (`{user.id}`)\n"
            f"📛 `{name}`  ·  `{bot_id}`\n"
            f"📄 `{ftype}`  ·  `{fsize/1024:.1f} KB`\n"
            f"💳 {plan['emoji']} `{plan['label']}`\n"
            f"🕐 `{time.strftime('%Y-%m-%d %H:%M:%S UTC')}`",
            parse_mode="Markdown",
        )
    except Exception as e:
        print(f"[LOG] {e}", flush=True)

# ══════════════════════════════════════════════════════════════
#  POST-INIT
# ══════════════════════════════════════════════════════════════

async def post_init(app: Application):
    global BOT_USERNAME
    BOT_USERNAME = (await app.bot.get_me()).username
    print(f"✅ @{BOT_USERNAME} ready!", flush=True)

# ══════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════

def main():
    if not BOT_TOKEN:
        print("ERROR: BOT_TOKEN not set!", file=sys.stderr); sys.exit(1)

    load_state(); load_users()

    print(f"╔══════════════════════════════════╗", flush=True)
    print(f"║    EXHAUST HOSTING — Starting    ║", flush=True)
    print(f"╚══════════════════════════════════╝", flush=True)
    print(f"✅ Admin: {ADMIN_ID}", flush=True)
    print(f"✅ Log Channel: {LOG_CHANNEL}", flush=True)
    print(f"✅ Force: @{users_db.get('force_channel', FORCE_CHANNEL)}", flush=True)
    print(f"✅ Bots loaded: {len(running_bots)}", flush=True)
    print(f"✅ Users: {len(users_db.get('all_users', []))}", flush=True)

    start_keepalive()

    started = auto_start_bots()
    print(f"✅ Auto-started: {started}", flush=True)

    threading.Thread(target=watchdog_loop, daemon=True).start()
    print("✅ Watchdog 24/7 active!", flush=True)

    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start",           start))
    app.add_handler(CommandHandler("help",            help_cmd))
    app.add_handler(CommandHandler("list",            list_bots_cmd))
    app.add_handler(CommandHandler("myplan",          myplan_cmd))
    app.add_handler(CommandHandler("listplans",       listplans_cmd))
    app.add_handler(CommandHandler("start_bot",       start_bot_cmd))
    app.add_handler(CommandHandler("stop_bot",        stop_bot_cmd))
    app.add_handler(CommandHandler("restart_bot",     restart_bot_cmd))
    app.add_handler(CommandHandler("logs",            logs_cmd))
    app.add_handler(CommandHandler("delete",          delete_cmd))
    app.add_handler(CommandHandler("stats",           stats_cmd))
    app.add_handler(CommandHandler("broadcast",       broadcast_cmd))
    app.add_handler(CommandHandler("addsub",          addsub_cmd))
    app.add_handler(CommandHandler("removesub",       removesub_cmd))
    app.add_handler(CommandHandler("setplan",         setplan_cmd))
    app.add_handler(CommandHandler("userinfo",        userinfo_cmd))
    app.add_handler(CommandHandler("lock",            lock_cmd))
    app.add_handler(CommandHandler("unlock",          unlock_cmd))
    app.add_handler(CommandHandler("stopall",         stopall_cmd))
    app.add_handler(CommandHandler("setowner",        setowner_cmd))
    app.add_handler(CommandHandler("setchannel",      setchannel_cmd))
    app.add_handler(CommandHandler("setforcechannel", setforcechannel_cmd))
    app.add_handler(CommandHandler("setqr",           setqr_cmd))
    app.add_handler(CommandHandler("setpayinfo",      setpayinfo_cmd))
    app.add_handler(CommandHandler("listusers",       listusers_cmd))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.PHOTO,        handle_photo))
    app.add_handler(CallbackQueryHandler(btn))

    app.job_queue.run_repeating(send_crash_notifications, interval=15, first=10)

    print("🤖 Polling started...", flush=True)
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
