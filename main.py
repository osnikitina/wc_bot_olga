print("🔥 ЭТО ТОТ MAIN.PY, КОТОРЫЙ ЗАПУСТИЛСЯ 🔥")
import sqlite3
import requests
import csv
import io
from datetime import datetime
import pytz
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ================= НАСТРОЙКИ =================
BOT_TOKEN = "8081762922:AAExyWb5PPwE0MML5cBf26yoCy9bk6UEImE"
ACCESS_PASSWORD = "qwe123qwe"

GOOGLE_SHEETS_CSV_URL = (
    "https://docs.google.com/spreadsheets/d/"
    "1GoUG8FZ8nRHGJalzgwfRAiVCExQRF5a9JmGlMGy8WPY"
    "/export?format=csv&gid=0"
)
DB_NAME = "bot.db"
MOSCOW_TZ = pytz.timezone("Europe/Moscow")
TIME_FORMAT = "%Y-%m-%d %H:%M"
MATCHES_PER_PAGE = 7
ADMIN_ID = 156845213
BACKUP_CHAT_ID = -1003647629033
# =============================================


# ---------- УТИЛИТЫ ----------
def now_moscow_str():
    return datetime.now(MOSCOW_TZ).strftime(TIME_FORMAT)

def get_display_name(user):
    return f"@{user.username}" if user.username else (user.first_name or "игрок")

def format_match_time(dt_str):
    dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
    return dt.strftime("%d.%m.%Y в %H:%M")


def format_date(date_str):
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    return dt.strftime("%d.%m.%Y")

def is_authorized(user_id):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT is_authorized FROM users WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return row and row[0] == 1



async def check_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("awaiting_password"):
        return False

    user = update.message.from_user
    name = get_display_name(user)

    if update.message.text.strip() == ACCESS_PASSWORD:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("UPDATE users SET is_authorized=1 WHERE user_id=?", (user.id,))
        conn.commit()
        conn.close()

        context.user_data["awaiting_password"] = False

        await update.message.reply_text(
            f"🔥 Отлично, {name}!\n\n"
            f"Ты в игре ⚽\n"
            f"Теперь ты участник турнира 🏆\n\n"
            f"👇 Выбирай действие:",
            reply_markup=main_menu(user.id)
        )
    else:
        await update.message.reply_text("❌ Неверный пароль")

    return True


async def guard(update, context):
    if update.message:
        if await check_password(update, context):
            return True
    if not is_authorized(update.effective_user.id):
        return True
    return False

# -----------GENERATE PREDICTIONS IN CSV-------
async def export_bets_core():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT 
            p.user_id,
            u.username,
            u.first_name,
            p.match_id,
            m.team_home,
            m.team_away,
            m.match_time,
            p.home_score,
            p.away_score
        FROM predictions p
        JOIN users u ON u.user_id = p.user_id
        JOIN matches m ON m.match_id = p.match_id
        ORDER BY m.match_time, p.user_id
    """)

    rows = cur.fetchall()
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow([
        "user_id",
        "username",
        "name",
        "match_id",
        "home_team",
        "away_team",
        "match_time",
        "prediction_home",
        "prediction_away"
    ])

    for r in rows:
        user_id, username, first_name, match_id, th, ta, mt, ph, pa = r
        writer.writerow([
            user_id,
            username or "",
            first_name or "",
            match_id,
            th,
            ta,
            mt,
            ph,
            pa
        ])

    output.seek(0)

    file_bytes = io.BytesIO(output.getvalue().encode("utf-8"))
    file_bytes.name = "bets_export.csv"

    return file_bytes


# EXPORT ALL PREDICTIONS BY CALL
async def export_bets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await guard(update, context):
        return

    q = update.callback_query
    await q.answer()

    if q.from_user.id != ADMIN_ID:
        await q.message.reply_text("⛔ Нет доступа")
        return

    file_bytes = await export_bets_core()

    await context.bot.send_document(
        chat_id=q.message.chat_id,
        document=file_bytes,
        caption="📤 Все ставки игроков (экспорт CSV)"
    )

# ---------- BACKUP PREDICTIONS TO CHAT ----------
async def send_prediction_backup(context, user, match_id, home, away):
    try:
        conn = get_db()
        cur = conn.cursor()

        cur.execute("""
            SELECT team_home, team_away, match_time
            FROM matches
            WHERE match_id = ?
        """, (match_id,))

        row = cur.fetchone()
        conn.close()

        if not row:
            return

        team_home, team_away, match_time = row

        user_name = (
            f"@{user.username}"
            if user.username
            else f"{user.first_name} ({user.id})"
        )
        
        text = (
            f"📥 Новая ставка\n\n"
            f"👤 Игрок: {user_name}\n"
            f"🆔 User ID: {user.id}\n"
            f"⚽ Матч: {team_home} – {team_away}\n"
            f"📅 Время: {format_match_time(match_time)}\n"
            f"🎯 Прогноз: {home}-{away}"
        )
        
        file_bytes = await export_bets_core()

        await context.bot.send_document(
            chat_id=BACKUP_CHAT_ID,
            document=file_bytes,
            caption=text
        )

    except Exception as e:
        print(f"Ошибка отправки бэкапа: {e}")


# ---------- БАЗА ----------
def get_db():
    return sqlite3.connect(DB_NAME)

def now_moscow():
    return datetime.now(MOSCOW_TZ)

def init_db():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS matches (
            match_id INTEGER PRIMARY KEY,
            team_home TEXT,
            team_away TEXT,
            match_time TEXT,
            home_score INTEGER,
            away_score INTEGER,
            finished INTEGER
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS predictions (
            user_id INTEGER,
            match_id INTEGER,
            home_score INTEGER,
            away_score INTEGER,
            PRIMARY KEY (user_id, match_id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            is_authorized INTEGER DEFAULT 0
        )
    """)

    conn.commit()
    conn.close()

# ---------- GOOGLE SHEETS ----------
def sync_matches_from_google():
    response = requests.get(GOOGLE_SHEETS_CSV_URL, timeout=10)
    response.raise_for_status()
    response.encoding = "utf-8"

    reader = csv.DictReader(io.StringIO(response.text))
    rows = list(reader)

    conn = get_db()
    cur = conn.cursor()

    cur.execute("DELETE FROM matches")

    for row in rows:
        home_score = row["home_score"].strip()
        away_score = row["away_score"].strip()
        finished = 1 if home_score and away_score else 0
        
        raw = row["match_time"].strip()
        dt = datetime.strptime(raw, "%Y-%m-%d %H:%M")
        match_time = dt.strftime("%Y-%m-%d %H:%M")

        cur.execute("""
            INSERT OR REPLACE INTO matches
            (match_id, team_home, team_away, match_time, home_score, away_score, finished)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            int(row["match_id"]),
            row["team_home"],
            row["team_away"],
            match_time,
            int(home_score) if home_score else None,
            int(away_score) if away_score else None,
            finished
        ))

    conn.commit()
    conn.close()


# ---------- МЕНЮ ----------
def main_menu(user_id: int):
    keyboard = [
        [InlineKeyboardButton("📅 Матчи", callback_data="matches")],
        [InlineKeyboardButton("📊 Мои прогнозы", callback_data="my_predictions")],
        [InlineKeyboardButton("📈 Мои результаты", callback_data="my_results")],
        [InlineKeyboardButton("🏆 Рейтинг", callback_data="rating")],
    ]

    if user_id == ADMIN_ID:
        keyboard.append([
            InlineKeyboardButton("🔄 Обновить результаты", callback_data="sync")
        ])
        keyboard.append([
            InlineKeyboardButton("📤 Распечатать все ставки", callback_data="export_bets")
        ])

    return InlineKeyboardMarkup(keyboard)


def back_button():
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="back")]])


# ---------- РАСЧЕТ ОЧКОВ ----------
def calculate_points(hr, ar, hp, ap):
    MIN_POINTS = -5
    if hp is None or ap is None:
        return MIN_POINTS
    if hr == hp and ar == ap:
        return 10
    if (hr > ar and hp > ap) or (hr < ar and hp < ap) or (hr == ar and hp == ap):
        diff = abs(hr - hp) + abs(ar - ap)
        return max(7 - diff, MIN_POINTS)
    diff = abs(hr - hp) + abs(ar - ap)
    return max(0 - diff, MIN_POINTS)

# ---------- РАСЧЕТ БОНУСОВ ----------
def get_outcome(home_score, away_score):
    if home_score > away_score:
        return "H"
    elif home_score < away_score:
        return "A"
    return "D"
    
def calculate_bonus_points(cur, match_id, hr, ar, hp, ap):
    if hp is None or ap is None:
        return 0

    actual_outcome = get_outcome(hr, ar)
    predicted_outcome = get_outcome(hp, ap)

    # бонус только за угаданный исход
    if predicted_outcome != actual_outcome:
        return 0

    cur.execute("""
        SELECT home_score, away_score
        FROM predictions
        WHERE match_id = ?
    """, (match_id,))

    same_outcome_count = 0

    for pred_home, pred_away in cur.fetchall():
        if get_outcome(pred_home, pred_away) == actual_outcome:
            same_outcome_count += 1

    if same_outcome_count < 3:
        return 4

    if same_outcome_count < 5:
        return 2

    return 0


# ---------- START ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    name = get_display_name(user)

    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        INSERT OR IGNORE INTO users (user_id, username, first_name, is_authorized)
        VALUES (?, ?, ?, 0)
    """, (user.id, user.username, user.first_name))
    conn.commit()

    cur.execute("SELECT is_authorized FROM users WHERE user_id=?", (user.id,))
    is_auth = cur.fetchone()[0]
    conn.close()

    if is_auth:
        await update.message.reply_text(
            f"🔥 С возвращением, {name}!\n\n👇 Выбирай действие:",
            reply_markup=main_menu(user.id)
        )
    else:
        context.user_data["awaiting_password"] = True
        await update.message.reply_text(
            f"👋 Привет, {name}!\n\n"
            f"⚽ Это турнир прогнозов\n\n"
            f"🔐 Введи пароль для доступа:"
        )


async def back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await guard(update, context): return
    q = update.callback_query
    await q.answer()
    await q.message.reply_text("Главное меню:", reply_markup=main_menu(q.from_user.id))


# ---------- МАТЧИ ----------
async def matches_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await guard(update, context): return
    q = update.callback_query
    await q.answer()
    keyboard = [
        [InlineKeyboardButton("📋 Все матчи", callback_data="all_0")],
        [InlineKeyboardButton("📆 По датам", callback_data="dates")],
        [InlineKeyboardButton("⬅️ Главное меню", callback_data="back")]
    ]
    await q.message.reply_text("Как показать матчи?", reply_markup=InlineKeyboardMarkup(keyboard))


async def show_all_matches(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await guard(update, context): return
    q = update.callback_query
    await q.answer()

    page = int(q.data.split("_")[1])
    offset = page * MATCHES_PER_PAGE

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT m.match_id, m.team_home, m.team_away, m.match_time, m.finished,
               EXISTS(
                   SELECT 1 FROM predictions p
                   WHERE p.match_id = m.match_id AND p.user_id = ?
               )
        FROM matches m
        WHERE m.match_time >= ?
        ORDER BY m.match_time
        LIMIT ? OFFSET ?
    """, (q.from_user.id, now_moscow_str(), MATCHES_PER_PAGE, offset))

    rows = cur.fetchall()
    conn.close()

    if not rows:
        await q.message.reply_text("Матчей больше нет.", reply_markup=back_button())
        return

    keyboard = []
    for mid, th, ta, ttime, fin, has_pred in rows:
        icon = "✅" if has_pred else "⚽"
        keyboard.append([InlineKeyboardButton(f"{icon} {th} – {ta} ({format_match_time(ttime)})", callback_data=f"predict_{mid}")])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ Назад", callback_data=f"all_{page-1}"))
    nav.append(InlineKeyboardButton("➡️ Далее", callback_data=f"all_{page+1}"))
    keyboard.append(nav)
    keyboard.append([InlineKeyboardButton("⬅️ Главное меню", callback_data="back")])

    await q.message.reply_text("Матчи:", reply_markup=InlineKeyboardMarkup(keyboard))


async def show_dates(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await guard(update, context): return

    q = update.callback_query
    await q.answer()

    # ---- pagination ----
    parts = q.data.split("_")
    page = int(parts[1]) if len(parts) > 1 else 0

    offset = page * MATCHES_PER_PAGE

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT DISTINCT date(match_time)
        FROM matches
        WHERE match_time >= ?
        ORDER BY date(match_time)
        LIMIT ? OFFSET ?
    """, (now_moscow_str(), MATCHES_PER_PAGE, offset))

    dates = cur.fetchall()

    cur.execute("""
        SELECT COUNT(DISTINCT date(match_time))
        FROM matches
        WHERE match_time >= ?
    """, (now_moscow_str(),))

    total = cur.fetchone()[0]
    conn.close()

    keyboard = [
        [InlineKeyboardButton(format_date(d[0]), callback_data=f"date_{d[0]}")]
        for d in dates
    ]

    # ---- navigation ----
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ Назад", callback_data=f"dates_{page-1}"))

    if offset + MATCHES_PER_PAGE < total:
        nav.append(InlineKeyboardButton("➡️ Далее", callback_data=f"dates_{page+1}"))

    if nav:
        keyboard.append(nav)

    keyboard.append([InlineKeyboardButton("⬅️ Главное меню", callback_data="back")])

    await q.message.reply_text(
        "Выбери дату:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def show_matches_by_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await guard(update, context): return
    q = update.callback_query
    await q.answer()

    date = q.data.split("_")[1]

    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT m.match_id, m.team_home, m.team_away, m.finished,
               EXISTS(
                   SELECT 1 FROM predictions p
                   WHERE p.match_id = m.match_id AND p.user_id = ?
               )
        FROM matches m
        WHERE date(m.match_time)=?
        ORDER BY m.match_time
    """, (q.from_user.id, date))

    rows = cur.fetchall()
    conn.close()

    keyboard = []
    for mid, th, ta, fin, has_pred in rows:
        icon = "✅" if has_pred else "⚽"
        keyboard.append([InlineKeyboardButton(f"{icon} {th} – {ta}", callback_data=f"predict_{mid}")])


    keyboard.append([
    InlineKeyboardButton("⬅️ К выбору дат", callback_data="dates"),
    InlineKeyboardButton("🏠 Главное меню", callback_data="back")
])

    await q.message.reply_text(f"Матчи {format_date(date)}:", reply_markup=InlineKeyboardMarkup(keyboard))


# ---------- ВЫБОР МАТЧА ----------
async def choose_match(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await guard(update, context): return
    q = update.callback_query
    await q.answer()
    mid = int(q.data.split("_")[1])
    context.user_data["match_id"] = mid
    await q.message.reply_text("Введи прогноз в формате: 2-1")

# ---------- СОХРАНЕНИЕ ПРОГНОЗА ----------
async def save_prediction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await guard(update, context): return

    if "match_id" not in context.user_data:
        return

    try:
        home, away = map(int, update.message.text.split("-"))
    except:
        await update.message.reply_text("Формат должен быть 2-1")
        return

    mid = context.user_data["match_id"]

    conn = get_db()
    cur = conn.cursor()

    # 🔥 ДОБАВЛЯЕМ ПРОВЕРКУ ВРЕМЕНИ
    cur.execute("SELECT match_time FROM matches WHERE match_id = ?", (mid,))
    row = cur.fetchone()

    if not row:
        await update.message.reply_text("Матч не найден")
        conn.close()
        return

    match_time = datetime.strptime(row[0], TIME_FORMAT)
    match_time = MOSCOW_TZ.localize(match_time)

    if match_time <= now_moscow():
        await update.message.reply_text(
            "⛔ Матч уже начался.\n"
            "Прогноз не принят — будет начислен минимальный балл."
        )
        conn.close()
        return

    # ✅ ЕСЛИ ВСЁ ОК — СОХРАНЯЕМ
    cur.execute("""
        INSERT OR REPLACE INTO predictions (user_id, match_id, home_score, away_score)
        VALUES (?, ?, ?, ?)
    """, (update.message.from_user.id, mid, home, away))

    conn.commit()
    conn.close()
    
    await send_prediction_backup(
    context,
    update.message.from_user,
    mid,
    home,
    away
    )

    context.user_data.pop("match_id")

    await update.message.reply_text(
        "✅ Прогноз сохранён!",
        reply_markup=main_menu(update.message.from_user.id)
    )



# ---------- МОИ ПРОГНОЗЫ ----------
async def my_predictions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await guard(update, context): return
    q = update.callback_query
    await q.answer()

    uid = q.from_user.id

    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT m.team_home, m.team_away, p.home_score, p.away_score
        FROM predictions p
        JOIN matches m ON p.match_id = m.match_id
        WHERE p.user_id = ?
        ORDER BY m.match_time
    """, (uid,))
    rows = cur.fetchall()
    conn.close()

    text = "📊 Твои прогнозы:\n\n" if rows else "У тебя пока нет прогнозов."
    for r in rows:
        text += f"{r[0]} – {r[1]}: {r[2]}-{r[3]}\n"

    await q.message.reply_text(text, reply_markup=back_button())


# ---------- МОИ РЕЗУЛЬТАТЫ ----------
async def my_results(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await guard(update, context): return
    q = update.callback_query
    await q.answer()

    uid = q.from_user.id

    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT match_id, home_score, away_score FROM matches WHERE finished=1")
    matches = cur.fetchall()

    total = exact = correct = wrong = total_bonus  = 0

    for mid, hr, ar in matches:
        cur.execute("SELECT home_score, away_score FROM predictions WHERE user_id=? AND match_id=?", (uid, mid))
        r = cur.fetchone()
        hp, ap = r if r else (None, None)

        base_pts = calculate_points(hr, ar, hp, ap)
        bonus_pts = calculate_bonus_points(cur, mid, hr, ar, hp, ap)
        pts = base_pts + bonus_pts 
        #pts = calculate_points(hr, ar, hp, ap)
        total += pts
        total_bonus += bonus_pts

        if base_pts == 10:
            exact += 1
        elif base_pts > 0:
            correct += 1
        else:
            wrong += 1

    cur.execute("SELECT user_id FROM users")
    users = [u[0] for u in cur.fetchall()]

    scores = []
    for u in users:
        s = 0
        for mid, hr, ar in matches:
            cur.execute("SELECT home_score, away_score FROM predictions WHERE user_id=? AND match_id=?", (u, mid))
            r = cur.fetchone()
            hp, ap = r if r else (None, None)
            s += calculate_points(hr, ar, hp, ap)
            s += calculate_bonus_points(cur, mid, hr, ar, hp, ap)
        scores.append((u, s))

    scores.sort(key=lambda x: x[1], reverse=True)
    place = [u for u, _ in scores].index(uid) + 1

    conn.close()

    text = (
        f"📊 Твой рейтинг: {place} место — {total} очков (из них {total_bonus} бонусных)\n\n"
        f"✅ Точные прогнозы: {exact}\n"
        f"⚽ Правильный исход: {correct}\n"
        f"❌ Неправильный исход: {wrong}"
    )

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Матчи и очки", callback_data="my_results_matches")],
        [InlineKeyboardButton("⬅️ Главное меню", callback_data="back")]
    ])

    await q.message.reply_text(text, reply_markup=kb)


# ---------- МОИ МАТЧИ С ОЧКАМИ ----------
async def my_results_matches(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await guard(update, context): return
    q = update.callback_query
    await q.answer()

    uid = q.from_user.id

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT m.match_id, m.team_home, m.team_away, m.home_score, m.away_score,
               p.home_score, p.away_score
        FROM matches m
        LEFT JOIN predictions p ON m.match_id=p.match_id AND p.user_id=?
        WHERE m.finished=1
        ORDER BY m.match_time
    """, (uid,))
    rows = cur.fetchall()


    text = "📊 Твои матчи и очки:\n\n<pre>"
    keyboard = []

    for i, r in enumerate(rows, 1):
        mid, th, ta, hr, ar, hp, ap = r

        base_pts = calculate_points(hr, ar, hp, ap)
        bonus_pts = calculate_bonus_points(cur, mid, hr, ar, hp, ap)
        pts = base_pts + bonus_pts          
        #pts = calculate_points(hr, ar, hp, ap)
        
        icon = "✅" if base_pts == 10 else "⚽" if base_pts > 0 else "❌"

        hp_text = f"{hp}" if hp is not None else "-"
        ap_text = f"{ap}" if ap is not None else "-"

        #text += f"{i}. {th} – {ta}\nТвой прогноз: {hp_text}-{ap_text}\nРезультат: {hr}-{ar} {icon}\nОчки: {pts} (из них {bonus_pts} бонусы)\n\n"
        t_name = f"{th} – {ta}"
        t_name = t_name.ljust(42)
        
        t_pred = f"🎯{hp_text}-{ap_text}"
        t_pred = t_pred.ljust(7)
        
        t_act = f"⚽️{hr}-{ar}"
        t_act = t_act.ljust(7)
        
        t_total = f"⭐️{pts}"
        t_total = t_total.ljust(4)
        
        t_bonus = f"🎁{bonus_pts}"
        t_bonus = t_bonus.ljust(3)

        text += f"{t_name} | {t_pred} {t_act} {t_bonus} {t_total}\n"

        keyboard.append([InlineKeyboardButton(f"🔍 {th} – {ta}", callback_data=f"compare_{mid}")])

    conn.close()

    keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="my_results")])
    text += "</pre>"
    
    await q.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")


# ---------- СРАВНЕНИЕ ----------
async def compare_match(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await guard(update, context): return
    q = update.callback_query
    await q.answer()

    mid = int(q.data.split("_")[1])

    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT team_home, team_away, home_score, away_score FROM matches WHERE match_id=?", (mid,))
    th, ta, hr, ar = cur.fetchone()

    cur.execute("""
        SELECT u.username, u.first_name, p.home_score, p.away_score
        FROM users u
        LEFT JOIN predictions p ON u.user_id=p.user_id AND p.match_id=?
    """, (mid,))
    rows = cur.fetchall()

    text = f"{th} – {ta}\nИтог: {hr}-{ar}\n\n"

    for u, f, hp, ap in rows:
        name = f"@{u}" if u else (f or "без имени")
        
        base_pts = calculate_points(hr, ar, hp, ap)
        bonus_pts = calculate_bonus_points(cur, mid, hr, ar, hp, ap)
        pts = base_pts + bonus_pts        
        #pts = calculate_points(hr, ar, hp, ap)

        icon = "✅" if base_pts == 10 else "⚽" if base_pts > 0 else "❌"

        if hp is None:
            text += f"{name}: — {icon} {pts}\n"
        else:
            text += f"{name}: {hp}-{ap} {icon} {pts}\n"

    conn.close()

    await q.message.reply_text(text, reply_markup=back_button())


# ---------- РЕЙТИНГ ----------
async def rating(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await guard(update, context): return
    q = update.callback_query
    await q.answer()

    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT user_id, username, first_name FROM users")
    users = cur.fetchall()

    cur.execute("SELECT match_id, home_score, away_score FROM matches WHERE finished=1")
    matches = cur.fetchall()

    ranking = []

    for uid, u, f in users:
        pts = exact = 0

        for mid, hr, ar in matches:
            #conn_match  = get_db()
            #cur = conn_match .cursor()
            cur.execute("SELECT home_score, away_score FROM predictions WHERE user_id=? AND match_id=?", (uid, mid))
            r = cur.fetchone()

            hp, ap = r if r else (None, None)
            
            base_pts = calculate_points(hr, ar, hp, ap)
            bonus_pts = calculate_bonus_points(cur, mid, hr, ar, hp, ap)
            p = base_pts + bonus_pts
            #p = calculate_points(hr, ar, hp, ap)

            #conn_match .close()

            pts += p
            if base_pts == 10:
                exact += 1

        name = f"@{u}" if u else (f or "без имени")
        ranking.append((name, pts, exact))

    conn.close()

    ranking.sort(key=lambda x: (x[1], x[2]), reverse=True)

    text = "🏆 Рейтинг игроков:\n\n"
    for i, (n, p, e) in enumerate(ranking, 1):
        text += f"{i}. {n} — {p} очков (точные: {e})\n"

    await q.message.reply_text(text)


# ---------- СИНХРОНИЗАЦИЯ ----------
async def sync_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await guard(update, context): return
    q = update.callback_query
    await q.answer()

    if q.from_user.id != ADMIN_ID:
        return

    sync_matches_from_google()
    await q.message.reply_text("✅ Матчи обновлены")


# ---------- MAIN ----------
def main():
    print("🚀 Бот запускается...")
    init_db()
    sync_matches_from_google()

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, save_prediction))

    app.add_handler(CallbackQueryHandler(back, pattern="^back$"))
    app.add_handler(CallbackQueryHandler(matches_menu, pattern="^matches$"))
    app.add_handler(CallbackQueryHandler(show_all_matches, pattern="^all_"))
    app.add_handler(CallbackQueryHandler(show_dates, pattern="^dates"))
    app.add_handler(CallbackQueryHandler(show_matches_by_date, pattern="^date_"))
    app.add_handler(CallbackQueryHandler(choose_match, pattern="^predict_"))
    app.add_handler(CallbackQueryHandler(my_predictions, pattern="^my_predictions$"))
    app.add_handler(CallbackQueryHandler(my_results, pattern="^my_results$"))
    app.add_handler(CallbackQueryHandler(my_results_matches, pattern="^my_results_matches$"))
    app.add_handler(CallbackQueryHandler(compare_match, pattern="^compare_"))
    app.add_handler(CallbackQueryHandler(rating, pattern="^rating$"))
    app.add_handler(CallbackQueryHandler(sync_handler, pattern="^sync$"))
    app.add_handler(CallbackQueryHandler(export_bets, pattern="^export_bets$"))
    print("🤖 Бот запущен и ждёт события...")
    app.run_polling()


if __name__ == "__main__":
    main()
