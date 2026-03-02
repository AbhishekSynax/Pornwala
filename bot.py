import logging
import sqlite3
import asyncio
import html
import aiohttp
import os
import io
import random
import shutil
from datetime import datetime, timedelta
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, 
    ReplyKeyboardMarkup, KeyboardButton, InputMediaVideo
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, 
    MessageHandler, filters, ContextTypes
)
from PIL import Image, ImageDraw, ImageFont

# ================= CONFIGURATION =================
BOT_TOKEN = "8251553782:AAF5NygZvlgzqGpR7mSH9ExPBUXPqSDnYlM"
OWNER_ID = 6742625894

# ================= DATABASE =================
DB_NAME = "bot_data.db"

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, plan TEXT, expiry TEXT, free_videos INTEGER DEFAULT 0, is_banned INTEGER DEFAULT 0, shortener_expiry TEXT, join_date TEXT, last_active TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS videos (id INTEGER PRIMARY KEY AUTOINCREMENT, file_id TEXT, file_unique_id TEXT UNIQUE)''')
    c.execute('''CREATE TABLE IF NOT EXISTS admins (user_id INTEGER PRIMARY KEY)''')
    c.execute('''CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS coupons (code TEXT PRIMARY KEY, plan TEXT, days INTEGER)''')
    c.execute('''CREATE TABLE IF NOT EXISTS delete_queue (chat_id INTEGER, message_id INTEGER, delete_time TEXT)''')
    
    try: c.execute("ALTER TABLE users ADD COLUMN is_banned INTEGER DEFAULT 0")
    except: pass
    try: c.execute("ALTER TABLE users ADD COLUMN shortener_expiry TEXT")
    except: pass
    try: c.execute("ALTER TABLE users ADD COLUMN join_date TEXT")
    except: pass
    try: c.execute("ALTER TABLE users ADD COLUMN last_active TEXT")
    except: pass

    c.execute("INSERT OR IGNORE INTO admins VALUES (?)", (OWNER_ID,))
    
    defaults = [
        ('delete_timer', '20'), ('price_silver', '100'), ('price_gold', '200'), 
        ('price_diamond', '300'), ('qr_code', 'None'), ('force_channel', 'None'),
        ('maintenance', '0'), ('shortener_api', 'None'), ('shortener_domain', 'gplinks.in'),
        ('shortener_on', '0')
    ]
    for key, val in defaults:
        c.execute("INSERT OR IGNORE INTO settings VALUES (?, ?)", (key, val))
    conn.commit()
    conn.close()

def get_db(): return sqlite3.connect(DB_NAME)

def is_admin(uid):
    conn = get_db()
    res = conn.execute("SELECT user_id FROM admins WHERE user_id=?", (uid,)).fetchone()
    conn.close()
    return res is not None

def is_banned(uid):
    conn = get_db()
    res = conn.execute("SELECT is_banned FROM users WHERE user_id=?", (uid,)).fetchone()
    conn.close()
    return res and res[0] == 1

def get_setting(key):
    conn = get_db()
    res = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    conn.close()
    return res[0] if res else None

def update_activity(uid):
    conn = get_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("UPDATE users SET last_active=? WHERE user_id=?", (now, uid))
    conn.commit()
    conn.close()

# ================= RECEIPT GENERATOR =================
def create_receipt_image(user_id, name, plan, price, validity_days, expiry_date):
    W, H = 1080, 1350
    BG_COLOR = (20, 20, 25)
    CARD_COLOR = (30, 30, 35)
    ACCENT_COLOR = (255, 184, 0)
    TEXT_WHITE = (255, 255, 255)
    TEXT_GREY = (160, 160, 160)
    SUCCESS_GREEN = (46, 204, 113)

    img = Image.new('RGB', (W, H), color=BG_COLOR)
    d = ImageDraw.Draw(img)
    
    try:
        font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        if not os.path.exists(font_path): font_path = "arial.ttf"
        f_mega = ImageFont.truetype(font_path, 100)
        f_title = ImageFont.truetype(font_path, 60)
        f_head = ImageFont.truetype(font_path, 45)
        f_body = ImageFont.truetype(font_path, 35)
    except:
        f_mega = f_title = f_head = f_body = ImageFont.load_default()

    d.rectangle([(0, 0), (W, 250)], fill=CARD_COLOR)
    d.text((50, 80), "PREMIUM RECEIPT", font=f_mega, fill=ACCENT_COLOR)
    d.rectangle([(800, 80), (1030, 170)], fill=SUCCESS_GREEN, outline=None)
    d.text((855, 100), "PAID", font=f_head, fill=BG_COLOR)

    txn_id = f"TXN-{random.randint(100000, 999999)}"
    date_now = datetime.now().strftime("%d %B %Y, %I:%M %p")
    d.text((50, 300), "Transaction ID", font=f_head, fill=TEXT_GREY)
    d.text((50, 360), txn_id, font=f_title, fill=TEXT_WHITE)
    d.text((50, 450), "Date", font=f_head, fill=TEXT_GREY)
    d.text((50, 510), date_now, font=f_title, fill=TEXT_WHITE)
    d.line([(50, 600), (1030, 600)], fill=(50, 50, 50), width=3)

    d.text((50, 650), "Billed To:", font=f_head, fill=ACCENT_COLOR)
    d.text((50, 720), str(name), font=f_title, fill=TEXT_WHITE)
    d.text((50, 800), f"User ID: {user_id}", font=f_body, fill=TEXT_GREY)

    d.rectangle([(50, 900), (1030, 1150)], outline=ACCENT_COLOR, width=4)
    d.rectangle([(50, 900), (1030, 1150)], fill=CARD_COLOR)
    d.text((80, 930), "Plan Details", font=f_body, fill=ACCENT_COLOR)
    d.text((80, 1000), f"{plan} Membership", font=f_title, fill=TEXT_WHITE)
    d.text((80, 1080), f"Validity: {validity_days} Days", font=f_body, fill=TEXT_GREY)
    d.text((750, 930), "Amount", font=f_body, fill=ACCENT_COLOR)
    d.text((750, 1000), f"₹ {price}", font=f_mega, fill=SUCCESS_GREEN)

    d.rectangle([(0, 1250), (W, H)], fill=ACCENT_COLOR)
    d.text((150, 1280), f"VALID UNTIL: {expiry_date}", font=f_head, fill=BG_COLOR)

    bio = io.BytesIO()
    img.save(bio, 'JPEG', quality=95)
    bio.seek(0)
    return bio

# ================= HELPERS =================
async def get_short_link(destination_url):
    api_key = get_setting('shortener_api')
    domain = get_setting('shortener_domain')
    if not api_key or api_key == 'None' or not domain or domain == 'None': return None
    api_url = f"https://{domain}/api?api={api_key}&url={destination_url}&format=text"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url) as response:
                if response.status == 200: return await response.text()
    except: return None

async def check_force_sub(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    channel = get_setting('force_channel')
    if is_admin(uid): return True 
    if not channel or channel == 'None': return True
    try:
        member = await context.bot.get_chat_member(channel, uid)
        if member.status in ['left', 'kicked']:
            try: link = (await context.bot.get_chat(channel)).invite_link
            except: link = "https://t.me/"
            await update.message.reply_text(
                "<b>⛔ Access Denied!</b>\n\nYou must join our channel to use this bot.", 
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔔 Join Channel", url=link)]])
            )
            return False
        return True
    except: return True

# ================= KEYBOARDS =================
def main_menu_kb(uid):
    conn = get_db()
    u = conn.execute("SELECT plan FROM users WHERE user_id=?", (uid,)).fetchone()
    conn.close()
    plan = u[0] if u else 'FREE'
    kb = [[KeyboardButton("🎬 Get Video"), KeyboardButton("👤 My Account")], [KeyboardButton("📞 Support")]]
    if plan == 'FREE': kb.insert(1, [KeyboardButton("💎 Buy Premium")])
    if is_admin(uid): kb.append([KeyboardButton("⚙️ Admin Panel")])
    return ReplyKeyboardMarkup(kb, resize_keyboard=True)

def account_kb():
    return ReplyKeyboardMarkup([
        [KeyboardButton("💎 Buy Premium"), KeyboardButton("🎟 Redeem Code")], 
        [KeyboardButton("🤝 Refer & Earn"), KeyboardButton("🔙 Main Menu")]
    ], resize_keyboard=True)

def admin_home_kb(context):
    bulk = "ON" if context.bot_data.get('bulk_mode', False) else "OFF"
    maint = "ON" if get_setting('maintenance') == '1' else "OFF"
    return ReplyKeyboardMarkup([
        [KeyboardButton("🎬 Video Manager"), KeyboardButton("📊 Advanced Stats")],
        [KeyboardButton("⚙️ Bot Settings"), KeyboardButton("👤 User Manager")],
        [KeyboardButton(f"📤 Bulk Save: {bulk}"), KeyboardButton(f"🛑 Maintenance: {maint}")],
        [KeyboardButton("📢 Broadcast"), KeyboardButton("💾 Backup DB")],
        [KeyboardButton("♻️ Restore DB"), KeyboardButton("🔙 Back to Menu")]
    ], resize_keyboard=True)

def admin_settings_kb():
    short = "ON" if get_setting('shortener_on') == '1' else "OFF"
    return ReplyKeyboardMarkup([
        [KeyboardButton(f"🔗 Link Shortener: {short}"), KeyboardButton("🔑 Set API Key")],
        [KeyboardButton("🌐 Set Domain"), KeyboardButton("💰 Update Prices")],
        [KeyboardButton("⏱ Delete Timer"), KeyboardButton("📢 Force Channel")],
        [KeyboardButton("🎟 Create Coupon"), KeyboardButton("🖼 Payment QR")],
        [KeyboardButton("🔙 Back to Panel")]
    ], resize_keyboard=True)

def admin_users_kb():
    return ReplyKeyboardMarkup([
        [KeyboardButton("⛔ Remove Plan"), KeyboardButton("🚫 Ban User")],
        [KeyboardButton("🔓 Unban User"), KeyboardButton("➕ Add Admin")],
        [KeyboardButton("➖ Remove Admin"), KeyboardButton("🔙 Back to Panel")]
    ], resize_keyboard=True)

def cancel_kb(): return ReplyKeyboardMarkup([[KeyboardButton("🔙 Cancel")]], resize_keyboard=True)
def buy_plan_kb():
    s, g, d = get_setting('price_silver'), get_setting('price_gold'), get_setting('price_diamond')
    return ReplyKeyboardMarkup([[KeyboardButton(f"🥈 Silver - ₹{s}"), KeyboardButton(f"🥇 Gold - ₹{g}")],[KeyboardButton(f"💎 Diamond - ₹{d}"), KeyboardButton("🔙 Cancel")]], resize_keyboard=True)

# ================= HANDLERS =================
ADMIN_HELP_TEXTS = {
    'SET_API': "🔑 <b>Send your Shortener API Key now:</b>",
    'SET_DOMAIN': "🌐 <b>Send your Shortener Domain (e.g. gplinks.in):</b>",
    'SET_PRICE': "💰 <b>Format:</b> <code>PLAN_NAME PRICE</code>\nExample: <code>SILVER 150</code>",
    'SET_TIMER': "⏱ <b>Send video auto-delete time in minutes (e.g. 20):</b>",
    'SET_CHANNEL': "📢 <b>Send Channel Username (e.g. @mychannel):</b>",
    'ADD_COUPON': "🎟 <b>Format:</b> <code>CODE PLAN DAYS</code>\nExample: <code>FREE20 GOLD 5</code>",
    'REM_SUB': "⛔ <b>Send the User ID to remove their plan:</b>",
    'BAN_USER': "🚫 <b>Send the User ID to Ban them:</b>",
    'UNBAN_USER': "🔓 <b>Send the User ID to Unban them:</b>",
    'ADD_ADMIN': "➕ <b>Send the User ID to make Admin:</b>",
    'REM_ADMIN': "➖ <b>Send the User ID to remove from Admin:</b>",
    'BROADCAST': "📢 <b>Send the message you want to broadcast to all users:</b>",
    'SET_QR': "🖼 <b>Please upload the Payment QR Code Photo:</b>"
}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid = user.id
    context.user_data.clear() 
    update_activity(uid)
    
    if not await check_force_sub(update, context): return

    maint = get_setting('maintenance')
    if maint == '1' and not is_admin(uid):
        await update.message.reply_text("<b>🚧 Bot is under Maintenance.</b>", parse_mode=ParseMode.HTML)
        return

    conn = get_db()
    curr_user = conn.execute("SELECT user_id FROM users WHERE user_id=?", (uid,)).fetchone()
    if not curr_user:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute("INSERT INTO users (user_id, plan, free_videos, is_banned, join_date, last_active) VALUES (?, 'FREE', 0, 0, ?, ?)", (uid, now, now))
        conn.commit()
        args = context.args
        if args and str(args[0]).isdigit():
            ref_id = int(args[0])
            if ref_id != uid:
                conn.execute("UPDATE users SET free_videos = free_videos - 2 WHERE user_id=?", (ref_id,))
                conn.commit()
                try: await context.bot.send_message(ref_id, "<b>🎉 Referral Bonus!</b>\nLimit Increased!", parse_mode=ParseMode.HTML)
                except: pass
    
    if context.args and context.args[0].startswith('verify_'):
        check_id = context.args[0].replace('verify_', '')
        if str(check_id) == str(uid):
            exp = (datetime.now() + timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")
            conn.execute("UPDATE users SET shortener_expiry=?, free_videos=0 WHERE user_id=?", (exp, uid))
            conn.commit()
            await update.message.reply_text("✅ <b>Access Granted!</b>\nUnlimited videos for 2 Hours.", parse_mode=ParseMode.HTML)
    conn.close()

    if is_banned(uid):
        await update.message.reply_text("<b>🚫 You are Banned.</b>", parse_mode=ParseMode.HTML)
        return

    welcome_text = f"""
    <b>🎬 Welcome to Video Bot, {user.first_name}!</b>
    
    <i>We provide the best random video streaming experience.</i>

    <b>✨ Features:</b>
    🎥 <b>Unlimited Random Videos</b> - Fresh content every time.
    💎 <b>Premium Plans</b> - Silver, Gold, and Diamond memberships.
    🚀 <b>High Speed</b> - Optimized for fast loading.
    🤝 <b>Referral System</b> - Earn free video limits.
    📞 <b>24/7 Support</b> - We are here to help.

    <b>Select an option below to get started 👇</b>
    """
    
    await update.message.reply_text(welcome_text, parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(uid))

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if is_admin(update.effective_user.id):
        context.user_data.clear()
        await update.message.reply_text("<b>⚙️ Admin Panel</b>", parse_mode=ParseMode.HTML, reply_markup=admin_home_kb(context))

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Robust text handling
    if not update.message or not update.message.text:
        return
    text = update.message.text.strip()
    uid = update.effective_user.id

    # ================= 1. UNIVERSAL BACK LOGIC (HIGHEST PRIORITY) =================
    # This block must be at the very top to catch all back button clicks regardless of state
    if text in ["🔙 Main Menu", "🔙 Back to Menu", "🔙 Back to Panel", "🔙 Cancel", "🔙 Back"]:
        context.user_data.clear() # Clears ALL states
        
        # Determine where to go based on Admin status
        if is_admin(uid):
            try:
                await update.message.reply_text("<b>⚙️ Admin Panel</b>", parse_mode=ParseMode.HTML, reply_markup=admin_home_kb(context))
            except Exception as e:
                print(f"Error sending admin panel: {e}")
        else:
            try:
                await update.message.reply_text("<b>🏠 Main Menu</b>", parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(uid))
            except Exception as e:
                print(f"Error sending main menu: {e}")
        return # IMPORTANT: Stop processing further

    # ================= 2. ADMIN REPLY TO SUPPORT =================
    if context.user_data.get('replying_to'):
        target_id = context.user_data.pop('replying_to')
        try:
            await context.bot.send_message(target_id, f"📩 <b>Admin Reply:</b>\n\n{text}", parse_mode=ParseMode.HTML)
            await update.message.reply_text(f"✅ Reply sent to User ID: <code>{target_id}</code>", parse_mode=ParseMode.HTML, reply_markup=admin_home_kb(context))
        except Exception as e:
            logging.error(f"Reply failed: {e}")
            await update.message.reply_text("❌ Failed to send reply.", reply_markup=admin_home_kb(context))
        return

    # ================= 3. USER COMMANDS =================
    if text == "💎 Buy Premium":
        context.user_data.clear()
        await update.message.reply_text("<b>💎 Select a Plan:</b>", parse_mode=ParseMode.HTML, reply_markup=buy_plan_kb())
        return
    
    if text == "🎟 Redeem Code":
        context.user_data.clear()
        context.user_data['state'] = 'REDEEM'
        await update.message.reply_text("<b>🎟 Send your Coupon Code:</b>", parse_mode=ParseMode.HTML, reply_markup=cancel_kb())
        return
    
    if text == "🤝 Refer & Earn":
        bot_usr = context.bot.username
        link = f"https://t.me/{bot_usr}?start={uid}"
        msg = f"<b>🤝 Refer & Earn</b>\n\nShare this link and get extra video limits!\n\n🔗 {link}"
        await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
        return
    
    if text == "📞 Support":
        context.user_data.clear()
        context.user_data['state'] = 'SUPPORT_USER'
        await update.message.reply_text("<b>✍️ Write your message below:</b>", parse_mode=ParseMode.HTML, reply_markup=cancel_kb())
        return

    # ================= 4. ADMIN COMMANDS =================
    if is_admin(uid):
        if text == "⚙️ Admin Panel":
            context.user_data.clear()
            await update.message.reply_text("<b>⚙️ Admin Panel</b>", parse_mode=ParseMode.HTML, reply_markup=admin_home_kb(context))
            return

        if text == "⚙️ Bot Settings":
            context.user_data.clear()
            await update.message.reply_text("<b>⚙️ Bot Settings</b>", parse_mode=ParseMode.HTML, reply_markup=admin_settings_kb())
            return

        if text == "👤 User Manager":
            context.user_data.clear()
            await update.message.reply_text("<b>👤 User Manager</b>", parse_mode=ParseMode.HTML, reply_markup=admin_users_kb())
            return

        if "Bulk Save:" in text:
            curr = context.bot_data.get('bulk_mode', False)
            context.bot_data['bulk_mode'] = not curr
            status = "ON" if not curr else "OFF"
            await update.message.reply_text(f"✅ Bulk Save Mode: <b>{status}</b>", parse_mode=ParseMode.HTML, reply_markup=admin_home_kb(context))
            return

        if "Maintenance:" in text:
            curr = get_setting('maintenance')
            new = '1' if curr == '0' else '0'
            conn=get_db(); conn.execute("INSERT OR REPLACE INTO settings VALUES (?, ?)", ('maintenance', new)); conn.commit(); conn.close()
            await update.message.reply_text(f"✅ Maintenance Mode: <b>{new}</b>", parse_mode=ParseMode.HTML, reply_markup=admin_home_kb(context))
            return

        if "Link Shortener:" in text:
            curr = get_setting('shortener_on')
            new = '1' if curr == '0' else '0'
            conn=get_db(); conn.execute("INSERT OR REPLACE INTO settings VALUES (?, ?)", ('shortener_on', new)); conn.commit(); conn.close()
            await update.message.reply_text(f"✅ Shortener: <b>{'ON' if new=='1' else 'OFF'}</b>", parse_mode=ParseMode.HTML, reply_markup=admin_settings_kb())
            return

        if text == "💾 Backup DB":
            await update.message.reply_document(document=open(DB_NAME, 'rb'), caption="💾 Database Backup")
            return

        if text == "♻️ Restore DB":
            context.user_data['state'] = 'RESTORE_DB'
            await update.message.reply_text("<b>📤 Upload your .db file now.</b>\n⚠️ This will replace current data!", parse_mode=ParseMode.HTML, reply_markup=cancel_kb())
            return

        if text == "🎬 Video Manager":
            await show_admin_video(update, context, 0)
            return

        if text == "📊 Advanced Stats":
            conn = get_db()
            total_users = conn.execute("SELECT count(*) FROM users").fetchone()[0]
            premium_users = conn.execute("SELECT count(*) FROM users WHERE plan != 'FREE'").fetchone()[0]
            banned_users = conn.execute("SELECT count(*) FROM users WHERE is_banned = 1").fetchone()[0]
            total_videos = conn.execute("SELECT count(*) FROM videos").fetchone()[0]
            conn.close()

            stats_msg = f"""
<b>📊 Advanced Statistics</b>

👥 <b>Total Users:</b> {total_users}
💎 <b>Premium Users:</b> {premium_users}
🚫 <b>Banned Users:</b> {banned_users}
🎬 <b>Total Videos:</b> {total_videos}
            """
            await update.message.reply_text(stats_msg, parse_mode=ParseMode.HTML)
            return

        # Admin Input Mapping
        input_map = {
            "🔑 Set API Key": "SET_API", "🌐 Set Domain": "SET_DOMAIN", "💰 Update Prices": "SET_PRICE",
            "⏱ Delete Timer": "SET_TIMER", "📢 Force Channel": "SET_CHANNEL", "🎟 Create Coupon": "ADD_COUPON",
            "🖼 Payment QR": "SET_QR", "📢 Broadcast": "BROADCAST", "⛔ Remove Plan": "REM_SUB",
            "🚫 Ban User": "BAN_USER", "🔓 Unban User": "UNBAN_USER",
            "➕ Add Admin": "ADD_ADMIN", "➖ Remove Admin": "REM_ADMIN"
        }
        if text in input_map:
            state_key = input_map[text]
            context.user_data['state'] = state_key
            help_msg = ADMIN_HELP_TEXTS.get(state_key, "👇 Send Input:")
            await update.message.reply_text(help_msg, parse_mode=ParseMode.HTML, reply_markup=cancel_kb())
            return

    # ================= 5. STATE HANDLING =================
    state = context.user_data.get('state')
    
    # Admin States
    if is_admin(uid) and state:
        conn = get_db()
        msg = "✅ Saved Successfully!"
        try:
            if state == 'SET_API': conn.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", ('shortener_api', text))
            elif state == 'SET_DOMAIN': conn.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", ('shortener_domain', text.replace("https://", "").replace("/", "")))
            elif state == 'SET_PRICE':
                try: 
                    parts = text.upper().split()
                    if len(parts) >= 2:
                        plan = parts[0]; price = parts[1]
                        conn.execute("INSERT OR REPLACE INTO settings VALUES (?, ?)", (f'price_{plan}', price))
                    else: raise ValueError
                except: msg = "❌ Invalid Format!\nExample: <code>SILVER 100</code>"
            elif state == 'SET_TIMER':
                if text.isdigit(): conn.execute("INSERT OR REPLACE INTO settings VALUES (?, ?)", ('delete_timer', text))
            elif state == 'SET_CHANNEL': conn.execute("INSERT OR REPLACE INTO settings VALUES (?, ?)", ('force_channel', text))
            elif state == 'ADD_COUPON':
                try: 
                    p = text.split(); 
                    if len(p) >= 3: conn.execute("INSERT OR REPLACE INTO coupons VALUES (?,?,?)", (p[0].upper(), p[1].upper(), p[2]))
                    else: raise ValueError
                except: msg = "❌ Invalid Format!\nExample: <code>CODE PLAN DAYS</code>"
            elif state == 'BAN_USER' and text.isdigit(): 
                conn.execute("UPDATE users SET is_banned=1 WHERE user_id=?", (int(text),)); msg=f"🚫 Banned {text}"
            elif state == 'UNBAN_USER' and text.isdigit(): 
                conn.execute("UPDATE users SET is_banned=0 WHERE user_id=?", (int(text),)); msg=f"🔓 Unbanned {text}"
            elif state == 'REM_SUB' and text.isdigit():
                conn.execute("UPDATE users SET plan='FREE', expiry=NULL, shortener_expiry=NULL WHERE user_id=?", (int(text),)); msg=f"⛔ Plan removed for {text}"
                try: await context.bot.send_message(int(text), "<b>⚠️ Your Premium Plan has been removed by Admin.</b>", parse_mode=ParseMode.HTML)
                except: pass
            elif state == 'ADD_ADMIN' and text.isdigit(): 
                conn.execute("INSERT OR IGNORE INTO admins VALUES (?)", (int(text),)); msg="➕ Admin Added"
            elif state == 'REM_ADMIN' and text.isdigit(): 
                conn.execute("DELETE FROM admins WHERE user_id=?", (int(text),)); msg="➖ Admin Removed"
            elif state == 'BROADCAST':
                users = conn.execute("SELECT user_id FROM users").fetchall()
                count = 0
                for u in users: 
                    try: await context.bot.send_message(u[0], text); count += 1
                    except: pass
                msg = f"✅ Broadcast sent to {count} users."
            
            conn.commit(); conn.close()
            await update.message.reply_text(msg, parse_mode=ParseMode.HTML, reply_markup=admin_home_kb(context))
        except Exception as e:
            logging.error(f"Admin State Error: {e}")
            await update.message.reply_text("❌ An error occurred.", parse_mode=ParseMode.HTML)
        finally:
            context.user_data.clear()
        return

    # User States
    if state == 'REDEEM':
        code = text.strip().upper()
        conn = get_db(); coupon = conn.execute("SELECT plan, days FROM coupons WHERE code=?", (code,)).fetchone()
        if coupon:
            exp = (datetime.now() + timedelta(days=coupon[1])).strftime("%Y-%m-%d %H:%M:%S")
            conn.execute("UPDATE users SET plan=?, expiry=? WHERE user_id=?", (coupon[0], exp, uid)); conn.commit()
            await update.message.reply_text(f"🎉 <b>Coupon Redeemed!</b>\nPlan: {coupon[0]}", parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(uid))
        else: await update.message.reply_text("❌ <b>Invalid Coupon Code.</b>", parse_mode=ParseMode.HTML, reply_markup=account_kb())
        context.user_data.clear(); conn.close(); return

    if state == 'SUPPORT_USER':
        try:
            user_link = f"tg://user?id={uid}"
            msg_text = f"💌 <b>New Support Request</b>\n\n<b>User:</b> <a href='{user_link}'>{update.effective_user.first_name}</a>\n<b>ID:</b> <code>{uid}</code>\n\n<b>Message:</b>\n{text}"
            
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("📩 Reply to User", callback_data=f'sup_rep_{uid}')]])
            await context.bot.send_message(OWNER_ID, msg_text, parse_mode=ParseMode.HTML, reply_markup=kb)
            await update.message.reply_text("✅ <b>Message sent to Admin!</b>\nWe will reply shortly.", parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(uid))
        except Exception as e:
            logging.error(f"Support Error: {e}")
            await update.message.reply_text("❌ Error sending message.")
        context.user_data.clear()
        return

    # ================= 6. NORMAL FLOWS =================
    if is_banned(uid): return
    update_activity(uid)
    maint = get_setting('maintenance')
    if maint == '1' and not is_admin(uid): await update.message.reply_text("<b>🚧 Maintenance Mode</b>", parse_mode=ParseMode.HTML); return
    if not await check_force_sub(update, context): return

    if text == "🎬 Get Video": await send_random_video(update, context, uid); return
    
    if text == "👤 My Account":
        conn=get_db(); u=conn.execute("SELECT plan, expiry, free_videos FROM users WHERE user_id=?", (uid,)).fetchone(); conn.close()
        plan_stat = u[0]
        if u[1]: plan_stat += f" (Exp: {u[1]})"
        await update.message.reply_text(f"<b>👤 Account</b>\n\nName: {update.effective_user.first_name}\n💎 Plan: {plan_stat}\n👀 Free Used: {u[2]}/5", parse_mode=ParseMode.HTML, reply_markup=account_kb())
        return
    
    if "Silver" in text or "Gold" in text or "Diamond" in text:
        try:
            parts = text.split('-')
            plan = parts[0].split()[1].upper(); price = parts[1].strip()
            context.user_data['pending_plan'] = plan
            qr = get_setting('qr_code')
            msg = f"💎 <b>{plan} Plan</b>\n💰 Price: {price}\n\n👇 <b>Pay via QR & Send Screenshot</b>"
            if qr and qr != 'None': await update.message.reply_photo(qr, caption=msg, parse_mode=ParseMode.HTML)
            else: await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
        except: pass
        return

async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    
    # Restore DB
    if is_admin(uid) and context.user_data.get('state') == 'RESTORE_DB':
        if update.message.document and update.message.document.file_name.endswith('.db'):
            if os.path.exists(DB_NAME): shutil.copy(DB_NAME, f"{DB_NAME}.bak")
            new_file = await update.message.document.get_file()
            await new_file.download_to_drive(DB_NAME)
            await update.message.reply_text("✅ <b>Database Restored!</b>", parse_mode=ParseMode.HTML, reply_markup=admin_home_kb(context))
            context.user_data.clear()
        else: await update.message.reply_text("❌ Send a valid .db file.")
        return

    # Auto Save Video
    if is_admin(uid) and update.message.video:
        current_state = context.user_data.get('state')
        pending_plan = context.user_data.get('pending_plan')
        if not current_state and not pending_plan:
            vid = update.message.video
            conn = get_db()
            c = conn.execute("INSERT OR IGNORE INTO videos (file_id, file_unique_id) VALUES (?,?)", (vid.file_id, vid.file_unique_id))
            conn.commit(); conn.close()
            if c.rowcount > 0: await update.message.reply_text("✅ <b>Video Saved!</b>", quote=True, parse_mode=ParseMode.HTML)
            return
        if context.bot_data.get('bulk_mode'):
            vid = update.message.video
            conn = get_db()
            c = conn.execute("INSERT OR IGNORE INTO videos (file_id, file_unique_id) VALUES (?,?)", (vid.file_id, vid.file_unique_id))
            conn.commit(); conn.close()
            if c.rowcount > 0: await update.message.reply_text("✅ Saved (Bulk)", quote=True, parse_mode=ParseMode.HTML)
            return

    # Other Media
    state = context.user_data.get('state')
    if state == 'SET_QR' and update.message.photo:
        fid = update.message.photo[-1].file_id
        conn = get_db(); conn.execute("INSERT OR REPLACE INTO settings VALUES (?, ?)", ('qr_code', fid)); conn.commit(); conn.close()
        await update.message.reply_text("✅ <b>QR Code Saved!</b>", parse_mode=ParseMode.HTML, reply_markup=admin_settings_kb()); context.user_data.clear(); return

    if state == 'BROADCAST':
        conn=get_db(); users=conn.execute("SELECT user_id FROM users").fetchall(); conn.close()
        for u in users:
            try: await update.message.copy(u[0])
            except: pass
        await update.message.reply_text("✅ <b>Broadcast Sent!</b>", parse_mode=ParseMode.HTML, reply_markup=admin_home_kb(context)); context.user_data.clear()
        return

    if context.user_data.get('pending_plan') and (update.message.photo or update.message.document):
        plan = context.user_data.pop('pending_plan')
        fid = update.message.photo[-1].file_id if update.message.photo else update.message.document.file_id
        u_name = html.escape(update.effective_user.full_name)
        price = get_setting(f'price_{plan.lower()}') or "N/A"
        days = 30 if plan=='DIAMOND' else 15 if plan=='GOLD' else 7
        exp_date = (datetime.now() + timedelta(days=days)).strftime("%d-%m-%Y")

        cap = f"<b>🆕 PAYMENT REQUEST</b>\n👤 {u_name}\n🆔 <code>{uid}</code>\n💎 Plan: {plan}"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Approve", callback_data=f'ok_{uid}_{plan}'), InlineKeyboardButton("❌ Reject", callback_data=f'no_{uid}')]])
        try:
            if update.message.photo: await context.bot.send_photo(OWNER_ID, fid, caption=cap, reply_markup=kb, parse_mode=ParseMode.HTML)
            else: await context.bot.send_document(OWNER_ID, fid, caption=cap, reply_markup=kb, parse_mode=ParseMode.HTML)
            await update.message.reply_text("✅ <b>Payment sent for verification!</b>", parse_mode=ParseMode.HTML)
        except: await update.message.reply_text("❌ Error sending to admin.")
        return

# ================= CALLBACKS =================
async def admin_vid_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; d = q.data
    if d == 'vid_back':
        await q.message.delete()
        await q.message.reply_text("<b>⚙️ Admin Panel</b>", parse_mode=ParseMode.HTML, reply_markup=admin_home_kb(context))
        return
    try: idx = int(d.split('_')[2])
    except: idx = 0
    if 'adm_d_' in d:
        conn = get_db(); vids = conn.execute("SELECT id FROM videos ORDER BY id DESC").fetchall()
        if 0 <= idx < len(vids): conn.execute("DELETE FROM videos WHERE id=?", (vids[idx][0],)); conn.commit(); await q.answer("Deleted!"); await show_admin_video(update, context, idx) 
        else: await q.answer("Error"); conn.close()
    else: await show_admin_video(update, context, idx)

async def show_admin_video(update, context, idx):
    conn = get_db(); vids = conn.execute("SELECT id, file_id FROM videos ORDER BY id DESC").fetchall(); conn.close()
    if not vids: return await (update.callback_query.answer("No videos.") if update.callback_query else update.message.reply_text("No videos."))
    if idx >= len(vids): idx = len(vids)-1
    if idx < 0: idx = 0
    nav = [[InlineKeyboardButton("⏮", callback_data=f'adm_v_{idx-1}'), InlineKeyboardButton("⏭", callback_data=f'adm_v_{idx+1}')],[InlineKeyboardButton("🗑 Delete", callback_data=f'adm_d_{idx}'), InlineKeyboardButton("🔙 Back", callback_data="vid_back")]]
    if update.callback_query:
        try: await update.callback_query.edit_message_media(media=InputMediaVideo(vids[idx][1], caption=f"ID: {vids[idx][0]}"), reply_markup=InlineKeyboardMarkup(nav))
        except: await update.callback_query.answer()
    else: await update.message.reply_video(vids[idx][1], caption=f"ID: {vids[idx][0]}", reply_markup=InlineKeyboardMarkup(nav))

async def random_cb(update, context):
    q = update.callback_query
    if q.data == 'buy_prem_cb': await q.message.reply_text("<b>👇 Choose Plan:</b>", parse_mode=ParseMode.HTML, reply_markup=buy_plan_kb())
    else: await send_random_video(update, context, q.from_user.id)
    await q.answer()

async def approve_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; d = q.data
    if 'ok_' in d:
        uid, plan = int(d.split('_')[1]), d.split('_')[2]
        days = 30 if plan=='DIAMOND' else 15 if plan=='GOLD' else 7
        exp = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        conn = get_db()
        conn.execute("UPDATE users SET plan=?, expiry=? WHERE user_id=?", (plan, exp, uid))
        conn.commit()
        price = get_setting(f'price_{plan.lower()}') or "N/A"
        try:
            user_info = await context.bot.get_chat(uid)
            img_bio = create_receipt_image(uid, user_info.first_name, plan, price, days, exp)
            await context.bot.send_photo(chat_id=uid, photo=img_bio, caption="✅ <b>Plan Activated Successfully!</b>", parse_mode=ParseMode.HTML)
            await context.bot.send_message(uid, "✨ <b>Menu Updated:</b>", parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(uid))
        except: await context.bot.send_message(uid, f"✅ <b>Plan Activated: {plan}</b>", parse_mode=ParseMode.HTML)
        await q.edit_message_caption("✅ <b>Approved & Receipt Sent.</b>", parse_mode=ParseMode.HTML)
        conn.close()
    else:
        try: await context.bot.send_message(int(d.split('_')[1]), "❌ <b>Payment Rejected.</b> Please try again.", parse_mode=ParseMode.HTML)
        except: pass
        await q.edit_message_caption("❌ <b>Rejected</b>", parse_mode=ParseMode.HTML)

# NEW: Support Reply Callback
async def support_reply_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    # Data format: sup_rep_USERID
    user_id = int(q.data.split('_')[-1])
    
    # Set state so next text message goes to this user
    context.user_data['replying_to'] = user_id
    
    await q.message.reply_text(f"📝 <b>Type your reply for User ID:</b> <code>{user_id}</code>", parse_mode=ParseMode.HTML)
    await q.answer()

async def send_random_video(update, context, uid):
    conn = get_db()
    user = conn.execute("SELECT plan, free_videos, shortener_expiry FROM users WHERE user_id=?", (uid,)).fetchone()
    vid = conn.execute("SELECT file_id FROM videos ORDER BY RANDOM() LIMIT 1").fetchone()
    conn.close()
    if not vid: return await update.message.reply_text("<b>⚠️ No videos available.</b>", parse_mode=ParseMode.HTML)

    plan, count, s_exp = user[0], user[1], user[2]
    can_watch = False
    if plan != 'FREE': can_watch = True
    elif s_exp:
        try:
            if datetime.now() < datetime.strptime(s_exp, "%Y-%m-%d %H:%M:%S"): can_watch = True
        except: pass
    
    if not can_watch:
        if count < 5:
            conn = get_db(); conn.execute("UPDATE users SET free_videos = free_videos + 1 WHERE user_id=?", (uid,)); conn.commit(); conn.close()
            can_watch = True
        else:
            s_on = get_setting('shortener_on')
            kb = []
            if s_on == '1':
                link = await get_short_link(f"https://t.me/{context.bot.username}?start=verify_{uid}")
                if link: kb.append([InlineKeyboardButton("🔓 Unlock 2 Hours", url=link)])
            kb.append([InlineKeyboardButton("💎 Buy Premium", callback_data="buy_prem_cb")])
            return await update.message.reply_text("<b>⛔️ Limit Reached!</b>\nPlease unlock or buy premium.", parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(kb))

    kb = InlineKeyboardMarkup([[InlineKeyboardButton("Next Video ➡️", callback_data='random_vid')]])
    msg = None
    try: 
        if update.callback_query: await update.callback_query.delete_message()
        msg = await context.bot.send_video(uid, vid[0], caption="🎥 Enjoy!", reply_markup=kb, protect_content=True)
    except: msg = await context.bot.send_video(uid, vid[0], caption="🎥 Enjoy!", reply_markup=kb, protect_content=True)

    if msg:
        timer_min = int(get_setting('delete_timer') or 20)
        del_time = (datetime.now() + timedelta(minutes=timer_min)).strftime("%Y-%m-%d %H:%M:%S")
        conn = get_db()
        conn.execute("INSERT INTO delete_queue (chat_id, message_id, delete_time) VALUES (?, ?, ?)", (uid, msg.message_id, del_time))
        conn.commit(); conn.close()

# ================= BACKGROUND TASKS =================
async def process_delete_queue_task(application: Application):
    while True:
        try:
            conn = get_db()
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            rows = conn.execute("SELECT rowid, chat_id, message_id FROM delete_queue WHERE delete_time <= ?", (now_str,)).fetchall()
            for row in rows:
                try: await application.bot.delete_message(chat_id=row[1], message_id=row[2])
                except: pass
                conn.execute("DELETE FROM delete_queue WHERE rowid=?", (row[0],))
            conn.commit(); conn.close()
        except: pass
        await asyncio.sleep(30)

async def check_expired_users_task(application: Application):
    while True:
        try:
            conn = get_db()
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            expired_users = conn.execute("SELECT user_id FROM users WHERE plan != 'FREE' AND expiry < ?", (now_str,)).fetchall()
            for u in expired_users:
                conn.execute("UPDATE users SET plan='FREE', expiry=NULL WHERE user_id=?", (u[0],)); conn.commit()
                try: await application.bot.send_message(u[0], "<b>⚠️ Your Plan has Expired.</b>", parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(u[0]))
                except: pass
            conn.close()
        except: pass
        await asyncio.sleep(60)

async def post_init(application: Application):
    asyncio.create_task(process_delete_queue_task(application))
    asyncio.create_task(check_expired_users_task(application))

# ================= MAIN =================
def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('admin', admin_command))
    app.add_handler(CallbackQueryHandler(admin_vid_cb, pattern='^adm_|vid_back'))
    app.add_handler(CallbackQueryHandler(random_cb, pattern='^random_vid|buy_prem_cb'))
    app.add_handler(CallbackQueryHandler(approve_cb, pattern='^(ok_|no_)'))
    app.add_handler(CallbackQueryHandler(support_reply_callback, pattern='^sup_rep_')) 
    app.add_handler(MessageHandler(filters.TEXT, handle_text))
    app.add_handler(MessageHandler(filters.ALL, handle_media))
    print("Bot Started Successfully...")
    app.run_polling()

if __name__ == '__main__':
    main()
