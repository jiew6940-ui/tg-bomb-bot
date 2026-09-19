import os
import json
import random
import asyncio
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters

# 1. 核心安全配置：从 Render 环境变量中动态读取
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID_STR = os.getenv("ADMIN_ID")

# 严密校验环境变量是否存在
if not BOT_TOKEN or not ADMIN_ID_STR:
    raise ValueError("❌ 错误：未在 Render 后台检测到 BOT_TOKEN 或 ADMIN_ID 环境变量！请检查配置。")

ADMIN_ID = int(ADMIN_ID_STR)
RANK_FILE = "leaderboard.json" # 排行榜保存数据文件名

# 游戏状态控制
GAME_STATE = {
    "status": "idle",       # idle, waiting_capacity, join, playing
    "capacity": 0,          # 本局设定的总人数
    "min": 1,
    "max": 100,
    "bomb": 0,
    "used_bombs": set(),    # 确保每一局数字不重复
    "players": [],          # 存储结构: [{"uid": 123, "name": "xxx", "num_id": 1}]
    "turn_idx": 0,          # 当前该轮到几号玩家发言 (索引)
    "group_chat_id": None   # 记录当前游戏群组ID
}

# --- 排行榜数据持久化逻辑 ---
def load_leaderboard():
    if os.path.exists(RANK_FILE):
        try:
            with open(RANK_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_winner(user_id, username):
    data = load_leaderboard()
    uid_str = str(user_id)
    if uid_str in data:
        data[uid_str]["wins"] += 1
        data[uid_str]["name"] = username
    else:
        data[uid_str] = {"name": username, "wins": 1}
    
    with open(RANK_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

async def show_rank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """查看战神排行榜命令"""
    data = load_leaderboard()
    if not data:
        await update.message.reply_text("📊 **【数字炸弹战神榜】**\n\n目前暂无胜场记录，等待首位天选之子诞生！")
        return
    
    sorted_rank = sorted(data.values(), key=lambda x: x["wins"], reverse=True)
    
    rank_text = "🏆 **【数字炸弹 · 终极战神榜】** 🏆\n"
    rank_text += "━━━━━━━━━━━━━━━━━━\n"
    medals = ["🥇", "🥈", "🥉"]
    
    for idx, player in enumerate(sorted_rank[:10]):
        prefix = medals[idx] if idx < 3 else f"【第{idx+1}名】"
        rank_text += f"{prefix} {player['name']} ——— 胜场 👑 `{player['wins']}`\n"
        
    rank_text += "━━━━━━━━━━━━━━━━━━\n"
    rank_text += "👁‍🗨 谁能笑到最后？踩碎炸弹，即可登顶！"
    await update.message.reply_text(rank_text)

# --- 游戏控制逻辑 ---
def get_join_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("💀 签下生死状 · 报名", callback_data="btn_join")]])

def reset_game():
    GAME_STATE["status"] = "idle"
    GAME_STATE["capacity"] = 0
    GAME_STATE["min"], GAME_STATE["max"] = 1, 100
    GAME_STATE["bomb"] = 0
    GAME_STATE["players"] = []
    GAME_STATE["turn_idx"] = 0

async def start_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        return 

    if GAME_STATE["status"] != "idle":
        await update.message.reply_text("⚠️ 战场硝烟未散，上一局大逃杀还在继续，无法开启新房间！")
        return

    GAME_STATE["status"] = "waiting_capacity"
    GAME_STATE["group_chat_id"] = update.effective_chat.id
    
    await update.message.reply_text(
        "👁‍🗨 **【最高主宰令】数字炸弹生死战已就绪！**\n"
        "请上帝输入本局要清洗的玩家人数：\n"
        "👉 输入 `/2` 开启双人地狱局\n"
        "👉 输入 `/5` 开启五人困兽斗\n"
        "👉 输入 `/7` 开启七人狂欢夜\n"
        "*(请直接打指令回复，生杀大权在你手中)*"
    )

async def handle_admin_commands(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID or GAME_STATE["status"] != "waiting_capacity":
        return

    text = update.message.text.strip()
    if text.startswith("/"):
        num_str = text.replace("/", "")
        if num_str.isdigit():
            capacity = int(num_str)
            if capacity < 2:
                await update.message.reply_text("❌ 杀戮游戏人数至少需要 2 人！")
                return
            
            GAME_STATE["status"] = "join"
            GAME_STATE["capacity"] = capacity
            GAME_STATE["players"] = []
            GAME_STATE["min"], GAME_STATE["max"] = 1, 100
            
            await update.message.reply_text(
                f"🚨 **【{capacity}人死局】数字炸弹大逃杀 · 囚徒征集令！** 🚨\n\n"
                f"💀 **警告：** 所有人踏入战场前，必须先私信激活机器人 @jieflqbot 接收专属编号！否则后果自负！\n\n"
                f"👇 倒计时开始，请各位迅速献出你们的灵魂：",
                reply_markup=get_join_keyboard()
            )

async def ask_next_player(context: ContextTypes.DEFAULT_TYPE):
    current_player = GAME_STATE["players"][GAME_STATE["turn_idx"]]
    await context.bot.send_message(
        chat_id=GAME_STATE["group_chat_id"],
        text=f"🏹 **轮到玩家 【{current_player['num_id']}号】{current_player['name']} 发言！**\n"
             f"📈 当前安全数字范围：`{GAME_STATE['min']}` ～ `{GAME_STATE['max']}`\n"
             f"👉 请在群内直接输入该范围内的整数！"
    )

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    user_id = query.from_user.id
    data = query.data
    username = query.from_user.first_name if query.from_user.first_name else f"User_{user_id}"

    if GAME_STATE["status"] != "join" or data != "btn_join":
        return

    if any(p["uid"] == user_id for p in GAME_STATE["players"]):
        return
        
    current_count = len(GAME_STATE["players"]) + 1
    if current_count > GAME_STATE["capacity"]:
        await query.message.reply_text("❌ 满员！地狱的大门已经对你关闭。")
        return

    GAME_STATE["players"].append({"uid": user_id, "name": username, "num_id": current_count})
    
    await context.bot.send_message(chat_id=chat_id, text=f"🩸 玩家{current_count}：{username} 已签下生死状！")
    
    try:
        await context.bot.send_message(chat_id=ADMIN_ID, text=f"🔔 报数：玩家{current_count}号【{username}】已踏入你的陷阱！")
    except Exception:
        pass

    if len(GAME_STATE["players"]) == GAME_STATE["capacity"]:
        GAME_STATE["status"] = "playing"
        GAME_STATE["turn_idx"] = 0
        
        while True:
            new_bomb = random.randint(2, 99)
            if new_bomb not in GAME_STATE["used_bombs"]:
                GAME_STATE["bomb"] = new_bomb
                GAME_STATE["used_bombs"].add(new_bomb)
                break
            if len(GAME_STATE["used_bombs"]) >= 95:
                GAME_STATE["used_bombs bombs"].clear()

        await context.bot.send_message(
            chat_id=GAME_STATE["group_chat_id"],
            text=f"⚡ **所有人已到齐！审判正式开始！**\n"
                 f"🔒 专属玩家编号已发往各位的私信，请严格按照编号顺序发言！\n"
                 f"初始范围：`1` ～ `100`"
        )

        for p in GAME_STATE["players"]:
            try:
                await context.bot.send_message(
                    chat_id=p["uid"],
                    text=f"👁‍🗨 你的专属出场编号是：【 {p['num_id']}号 】！本局游戏将按照编号从小到大轮流发言，请做好准备！"
                )
            except Exception:
                await context.bot.send_message(
                    chat_id=GAME_STATE["group_chat_id"],
                    text=f"⚠️ 警告：玩家【{p['name']}】由于未私信激活机器人，无法接收编号私信！"
                )

        await ask_next_player(context)

async def handle_player_guess(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if GAME_STATE["status"] != "playing" or update.effective_chat.id != GAME_STATE["group_chat_id"]:
        return

    user_id = update.effective_user.id
    current_player = GAME_STATE["players"][GAME_STATE["turn_idx"]]

    if user_id != current_player["uid"]:
        return

    text = update.message.text.strip()
    if not text.isdigit():
        return

    guess = int(text)

    if guess <= GAME_STATE["min"] or guess >= GAME_STATE["max"]:
        await update.message.reply_text(f"❌ 违规输入！请输入当前范围内的数字 (`{GAME_STATE['min']}` ~ `{GAME_STATE['max']}`之间)！")
        return

    if guess == GAME_STATE["bomb"]:
        await update.message.reply_text(
            f"💥 **轰！！！** 玩家 【{current_player['num_id']}号】{current_player['name']} 踩中了炸弹数字 【{GAME_STATE['bomb']}】！\n"
            f"💀 你已被当场无情抹杀！"
        )

        GAME_STATE["players"].pop(GAME_STATE["turn_idx"])

        if len(GAME_STATE["players"]) <= 1:
            winner = GAME_STATE["players"] if GAME_STATE["players"] else None
            if winner:
                save_winner(winner["uid"], winner["name"])
                w_text = f"🏆 **本局最终幸存者是：【{winner['num_id']}号】{winner['name']}**！\n👑 胜场 +1！已被载入至尊战神榜！"
            else:
                w_text = "💀 全军覆没！没有人活下来。"
                
            await context.bot.send_message(
                chat_id=GAME_STATE["group_chat_id"],
                text=f"🏁 **大逃杀宣告结束！**\n\n{w_text}\n\n💡 发送 `/rank` 可查看当前群组胜率天梯！游戏已重置。"
            )
            reset_game()
            return
        
        while True:
            new_bomb = random.randint(2, 99)
            if new_bomb not in GAME_STATE["used_bombs"]:
                GAME_STATE["bomb"] = new_bomb
                GAME_STATE["used_bombs"].add(new_bomb)
                break
            if len(GAME_STATE["used_bombs"]) >= 95:
                GAME_STATE["used_bombs"].clear()

        GAME_STATE["min"], GAME_STATE["max"] = 1, 100
        
        await context.bot.send_message(
            chat_id=GAME_STATE["group_chat_id"],
            text=f"🔄 **安全局势洗牌！** 炸弹已重新秘密埋设，数字范围重置为 `1` ～ `100`！"
        )

        if GAME_STATE["turn_idx"] >= len(GAME_STATE["players"]):
            GAME_STATE["turn_idx"] = 0

    else:
        if guess < GAME_STATE["bomb"]:
            GAME_STATE["min"] = guess
        else:
            GAME_STATE["max"] = guess

        GAME_STATE["turn_idx"] = (GAME_STATE["turn_idx"] + 1) % len(GAME_STATE["players"])

    await ask_next_player(context)

# 简易 HTTP 服务
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

def run_http_server():
    server = HTTPServer(('0.0.0.0', 8080), HealthCheckHandler)
    server.serve_forever()

