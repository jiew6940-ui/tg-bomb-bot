import os
import random
import asyncio
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters

# 1. 核心锁死配置
BOT_TOKEN = "8953042632:AAFpdONdgOLYOu9zcFUQ93mSIBpAVlitNz0"
ADMIN_ID = 8267239773  # 只有你可以运行控制命令

# 游戏状态控制
GAME_STATE = {
    "status": "idle",       # idle, waiting_capacity, join, playing
    "capacity": 0,          # 本局设定的总人数
    "min": 1,
    "max": 100,
    "bomb": 0,
    "used_bombs": set(),    # 确保每一局数字不重复
    "players": [],          # 存储结构: [{"uid": 123, "name": "xxx", "hp": 3, "num_id": 1}]
    "turn_idx": 0,          # 当前该轮到几号玩家发言 (索引)
    "group_chat_id": None   # 记录当前游戏群组ID
}

def get_join_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("💀 签下生死状 · 报名", callback_data="btn_join")]])

# 重置游戏状态
def reset_game():
    GAME_STATE["status"] = "idle"
    GAME_STATE["capacity"] = 0
    GAME_STATE["min"], GAME_STATE["max"] = 1, 100
    GAME_STATE["bomb"] = 0
    GAME_STATE["players"] = []
    GAME_STATE["turn_idx"] = 0
    # used_bombs 不重置，保留全局去重

# 2. 只有管理员可以运行的命令入口
async def start_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        return 

    if GAME_STATE["status"] != "idle":
        await update.message.reply_text("⚠️ 战场硝烟未散，上一局大逃杀还在继续，无法开启新房间！")
        return

    GAME_STATE["status"] = "waiting_capacity"
    GAME_STATE["group_chat_id"] = update.effective_chat.id # 记录游戏发生的群组
    
    await update.message.reply_text(
        "👁‍🗨 **【最高主宰令】数字炸弹生死战已就绪！**\n"
        "请上帝输入本局要清洗的玩家人数：\n"
        "👉 输入 `/2` 开启双人地狱局\n"
        "👉 输入 `/5` 开启五人困兽斗\n"
        "👉 输入 `/7` 开启七人狂欢夜\n"
        "*(请直接打指令回复，生杀大权在你手中)*"
    )

# 3. 监听管理员输入的局数人数
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
            
            # 初始化报名房间
            GAME_STATE["status"] = "join"
            GAME_STATE["capacity"] = capacity
            GAME_STATE["players"] = []
            GAME_STATE["min"], GAME_STATE["max"] = 1, 100
            
            await update.message.reply_text(
                f"🚨 **【{capacity}人死局】数字炸弹大逃杀 · 囚徒征集令！** 🚨\n\n"
                f"💀 **警告：** 所有人踏入战场前，必须先私信激活机器人 @jieflqbot 接收死亡代码！否则后果自负！\n\n"
                f"👇 倒计时开始，请各位迅速献出你们的灵魂：",
                reply_markup=get_join_keyboard()
            )

# 4. 按钮报名回调与游戏启动
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    user_id = query.from_user.id
    data = query.data
    username = query.from_user.first_name if query.from_user.first_name else f"User_{user_id}"

    if GAME_STATE["status"] != "join" or data != "btn_join":
        return

    # 防止重复加入
    if any(p["uid"] == user_id for p in GAME_STATE["players"]):
        return
        
    current_count = len(GAME_STATE["players"]) + 1
    if current_count > GAME_STATE["capacity"]:
        await query.message.reply_text("❌ 满员！地狱的大门已经对你关闭。")
        return

    # 录入玩家 (初始HP: 3)
    GAME_STATE["players"].append({"uid": user_id, "name": username, "hp": 3, "num_id": current_count})
    
    await context.bot.send_message(
        chat_id=chat_id, 
        text=f"🩸 玩家{current_count}：{username} 已签下生死状！"
    )
    
    try:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"🔔 报数：玩家{current_count}号【{username}】已踏入你的陷阱！"
        )
    except Exception:
        pass

    # 如果人数收齐了，自动开启游戏
    if len(GAME_STATE["players"]) == GAME_STATE["capacity"]:
        GAME_STATE["status"] = "playing"
        GAME_STATE["turn_idx"] = 0
        
        # 生成绝不重复的炸弹数字
        while True:
            new_bomb = random.randint(2, 99)
            if new_bomb not in GAME_STATE["used_bombs"]:
                GAME_STATE["bomb"] = new_bomb
                GAME_STATE["used_bombs"].add(new_bomb)
                break
            if len(GAME_STATE["used_bombs"]) >= 95:
                GAME_STATE["used_bombs"].clear()

        # 私信发送号码
        for p in GAME_STATE["players"]:
            try:
                await context.bot.send_message(
                    chat_id=p["uid"],
                    text=f"💀 【死亡序列】你在本局中的发言号码是： 👉 【 {p['num_id']}号 】 👈\n"
                         f"盯紧群里的局势，死神点到你的号码时再打字输入！提前或延误都将遭到抹杀！"
                )
            except Exception:
                await context.bot.send_message(
                    chat_id=chat_id, 
                    text=f"⚠️ 处决警告：玩家【{p['name']}】未激活机器人 @jieflqbot ，死亡号码无法送达！"
                )

        # 播报第一回合
        current_player = GAME_STATE["players"][GAME_STATE["turn_idx"]]
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"🏁 **大逃杀正式开始！死神之轮启动！**\n\n"
                 f"当前数字范围：👉 **{GAME_STATE['min']} ~ {GAME_STATE['max']}** 👈\n"
                 f"💀 轮到玩家：**{current_player['num_id']}号【{current_player['name']}】** (❤️ HP: {current_player['hp']})\n"
                 f"❗ 请直接在群里发送你猜测的纯数字！"
        )

# 5. 核心：游戏运行中的报数监听逻辑
async def handle_game_play(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # 严格锁死：只在进行游戏时，且在特定群组中监听
    if GAME_STATE["status"] != "playing" or update.effective_chat.id != GAME_STATE["group_chat_id"]:
        return

    user_id = update.effective_user.id
    text = update.message.text.strip()

    # 如果不是纯数字输入，直接无视（不属于游戏竞猜）
    if not text.isdigit():
        return

    guess = int(text)
    current_player = GAME_STATE["players"][GAME_STATE["turn_idx"]]

    # 严格检验：是否是当前轮到的玩家在说话
    if user_id != current_player["uid"]:
        # 非法插嘴惩罚（可选：这里选择直接无视或提示，不惩罚HP）
        return

    # 验证输入数字是否在合法边界内
    if guess <= GAME_STATE["min"] or guess >= GAME_STATE["max"]:
        await update.message.reply_text(
            f"❌ 愚蠢的错误！请输入范围 **{GAME_STATE['min']} ~ {GAME_STATE['max']}** 之间的数字！"
        )
        return

    chat_id = update.effective_chat.id

    # 情况 A：踩中炸弹 💥
    if guess == GAME_STATE["bomb"]:
        current_player["hp"] -= 1
        await update.message.reply_text(
            f"💥💥 **轰！！！你引爆了数字炸弹【{GAME_STATE['bomb']}】！** 💥💥\n"
            f"💀 玩家【{current_player['name']}】受到致命反噬，扣除 1 点生命值！\n"
            f"🩸 剩余生命值： ❤️ **{current_player['hp']} / 3**"
        )

        # 检查该玩家是否彻底死亡
        if current_player["hp"] <= 0:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"☠️ **【神罚降临】玩家 {current_player['num_id']}号【{current_player['name']}】生命值归零，被无情抹杀！**"
            )
            # 从赛场中剔除
            GAME_STATE["players"].remove(current_player)
            
            # 游戏终局判定
            if len(GAME_STATE["players"]) <= 1:
                if len(GAME_STATE["players"]) == 1:
                    winner = GAME_STATE["players"][0]
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=f"🏆🏆 **杀戮结束！最后的幸存者诞生：** 🏆🏆\n"
                             f"👑 恭喜玩家 **{winner['num_id']}号【{winner['name']}】** 成功逃出升天！生存至最后！"
                    )
                else:
                    await context.bot.send_message(chat_id=chat_id, text=f"☠️ 战况惨烈！所有人同归于尽，没有幸存者！")
                
                reset_game()
                return
            
            # 如果没结束，因为删除了元素，指针不需要前移，直接缩进到下一个
            if GAME_STATE["turn_idx"] >= len(GAME_STATE["players"]):
                GAME_STATE["turn_idx"] = 0
        else:
            # 踩中炸弹但没死，数字重置，开启全新一轮炸弹
            while True:
                new_bomb = random.randint(2, 99)
                if new_bomb not in GAME_STATE["used_bombs"]:
                    GAME_STATE["bomb"] = new_bomb
                    GAME_STATE["used_bombs"].add(new_bomb)
                    break
            
            # 回合移交给下一个人
            GAME_STATE["turn_idx"] = (GAME_STATE["turn_idx"] + 1) % len(GAME_STATE["players"])

        # 重新生成边界
        GAME_STATE["min"], GAME_STATE["max"] = 1, 100
        next_player = GAME_STATE["players"][GAME_STATE["turn_idx"]]
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"🔄 **安全区重置！盲区刷新完毕！**\n"
                 f"当前数字范围：👉 **{GAME_STATE['min']} ~ {GAME_STATE['max']}** 👈\n"
                 f"💀 下一位受害者：**{next_player['num_id']}号【{next_player['name']}】** (❤️ HP: {next_player['hp']})"
        )

    # 情况 B：未踩中炸弹，缩小安全区 📉
    else:
        if guess > GAME_STATE["bomb"]:
            GAME_STATE["max"] = guess
        else:
            GAME_STATE["min"] = guess

        # 回合递进
        GAME_STATE["turn_idx"] = (GAME_STATE["turn_idx"] + 1) % len(GAME_STATE["players"])
        next_player = GAME_STATE["players"][GAME_STATE["turn_idx"]]

        await context.bot.send_message(
            chat_id=chat_id,
            text=f"📉 **避开死线！范围正在向地狱收缩...**\n"
                 f"当前新范围：👉 **{GAME_STATE['min']} ~ {GAME_STATE['max']}** 👈\n"
                 f"💀 轮到玩家：**{next_player['num_id']}号【{next_player['name']}】** (❤️ HP: {next_player['hp']})"
        )

# 6. 用于防止部署到平台（如 Render）因缺少 Web 端口而死机的健康检查
def run_health_server():
    class HealthCheckHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

# 7. 主函数入口
def main():
    # 异步开启健康检查 Web 服务
