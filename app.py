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
    "turn_idx": 0           # 当前该轮到几号玩家发言
}

def get_join_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("💀 签下生死状 · 报名", callback_data="btn_join")]])

# 2. 只有管理员可以运行的命令入口
async def start_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        return # 严格限制：其他人运行直接无视

    if GAME_STATE["status"] != "idle":
        await update.message.reply_text("⚠️ 战场硝烟未散，上一局大逃杀还在继续，无法开启新房间！")
        return

    GAME_STATE["status"] = "waiting_capacity"
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

# 4. 按钮报名回调
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

    # 录入玩家
    GAME_STATE["players"].append({"uid": user_id, "name": username, "hp": 3, "num_id": current_count})
    
    # 严格格式在群里展示玩家
    await context.bot.send_message(
        chat_id=chat_id, 
        text=f"🩸 玩家{current_count}：{username} 已签下生死状！"
    )
    
    # 核心需求：每有一位玩家加入，立刻发私信给管理员(8267239773)
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

        # 核心需求：给所有参赛玩家私信发送他们本局的号码
        for p in GAME_STATE["players"]:
            try:
                await context.bot.send_message(
                    chat_id=p["uid"],
                    text=f"💀 【死亡序列】你在本局中的发言号码是： 👉 【 {p['num_id']}号 】 👈\n盯紧群里的局势，死神点到你的号码时再打字输入！提前或延误都将遭到抹杀！"
                )
            except Exception:
                await context.bot.send_message(chat_id=chat_id, text=f"⚠️ 处决警告：玩家【{p['name']}】未激活机器人 @jieflqbot ，死亡号码无法送达！")

        # 上帝视角核心需求：私信发给管理员所有玩家号码配置以及本局炸弹答案
        admin_report = f"👁‍🗨 **【全知全能·上帝主控台】**\n\n💣 本局核心爆破核心数值： 👉 `{GAME_STATE['bomb']}` 👈\n\n📊 **卑微的牺牲者名单：**\n"
        for p in GAME_STATE["players"]:
            admin_report += f"• 玩家{p['num_id']}号 ： {p['name']} (ID: {p['uid']})\n"
        
        try:
            await context.bot.send_message(chat_id=ADMIN_ID, text=admin_report, parse_mode="Markdown")
        except Exception:
            pass

        # 群内战役宣布爆发
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"⚔️ **牢笼已锁死！大逃杀正式爆发！** ⚔️\n"
                 f"死亡代码已在暗中发放。谁敢越界或者插队，将被系统瞬间清洗！\n"
                 f"🚨 **初始安全防线：`1 ~ 100`**\n"
                 f"⏱ 窒息开始！请 【1号】 玩家在群里打出第一个数字！其他人的任何声音一概视为无效！"
        )

# 5. 监听群聊内的抢答（高智商轮流控场逻辑）
async def handle_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    text = update.message.text.strip()
    
    if GAME_STATE["status"] != "playing": return
    if not text.isdigit(): return # 只听纯数字

    # 找出当前有哪些人还活着
    alive_players = [p for p in GAME_STATE["players"] if p["hp"] > 0]
    current_turn_player = alive_players[GAME_STATE["turn_idx"] % len(alive_players)]

    # 严格拦截非本回合玩家发言
    if user_id != current_turn_player["uid"]:
        return 

    guess = int(text)
    player = current_turn_player
    bomb = GAME_STATE["bomb"]
    
    # 🌟 极度紧绷的文字仪式感！
    suspense_msg = await context.bot.send_message(
        chat_id=chat_id,
        text=f"⚠️ **【极限核验】** 玩家 【{player['num_id']}号：{player['name']}】 孤注一掷！打出了数字 `{guess}`！\n"
             f"🚨 起爆装置正将该数值强行注入…… 核心齿轮咬合……\n"
             f"🔥 `🔊 ［ 滋滋滋…… 3.. 2.. 1.. ］屏住呼吸，静候判决！`"
    )
    
    # 静默 1.5 秒，让群友彻底抓狂
    await asyncio.sleep(1.5)
    
    log_msg = ""
    # 判定结果
    if guess == bomb or guess <= GAME_STATE["min"] or guess >= GAME_STATE["max"]:
        reason = f"正好踩中了死神设定的引爆数字 `{bomb}` ！💥" if guess == bomb else f"愚蠢地打出了安全圈 `{GAME_STATE['min']}~{GAME_STATE['max']}` 之外的自杀数值！⚡"
        player["hp"] -= 1
        log_msg = f"💀 **HISS——！！！ 轰隆！！！**\n【玩家{player['num_id']}号：{player['name']}】{reason}\n" \
                  f"🔥 汹涌的火海瞬间将你吞噬！**你的生命值被狠狠扣除 1 点！**\n"
        
        # 踩雷后重新生成新一局的数字，重置范围，继续大逃杀
        while True:
            new_bomb = random.randint(2, 99)
            if new_bomb not in GAME_STATE["used_bombs"]:
                GAME_STATE["bomb"] = new_bomb
                GAME_STATE["used_bombs"].add(new_bomb)
                break
        GAME_STATE["min"], GAME_STATE["max"] = 1, 100
        log_msg += f"\n🔄 **安全壁垒紧急重置！** 全新爆破芯片已暗中激活，**安全防线恢复至：`1 ~ 100`**！杀戮继续！"
        
        # 上帝视角特权：将新一局的隐藏炸弹继续私信通知管理员
        try:
            await context.bot.send_message(chat_id=ADMIN_ID, text=f"👁‍🗨 【上帝提示】血流成河！战场重置，本轮全新的危险炸弹已更新为：`{GAME_STATE['bomb']}`")
        except: pass
    else:
        # 自动缩短范围
        if guess < bomb:
            GAME_STATE["min"] = guess
        else:
            GAME_STATE["max"] = guess
        log_msg = f"⚡ **咔哒。 虚惊一场！**\n【玩家{player['num_id']}号：{player['name']}】打出的 `{guess}` 擦着火星过关！引信在距离炸弹 0.01 毫米处极限刹车！\n" \
                  f"🚨 **但包围网已被疯狂绞杀！新的安全天堑区间已暴缩至：`{GAME_STATE['min']} ~ {GAME_STATE['max']}`** ！留给后面人的活路不多了……\n"

    # 面板同步
    log_msg += "\n📊 **当前血量残留看板：**\n"
    for p in GAME_STATE["players"]:
        heart = "🩸" * p["hp"] if p["hp"] > 0 else "💀 [已被炸飞抹杀]"
        log_msg += f"• 玩家{p['num_id']}号：{p['name']} —— {heart} ({p['hp']}/3 HP)\n"

    # 将高压消息更新覆盖为最终惊悚结果
    await suspense_msg.edit_text(text=log_msg, parse_mode="Markdown")

    # 判定生死大赢家
    final_alives = [p for p in GAME_STATE["players"] if p["hp"] > 0]
    if len(final_alives) == 1:
        winner = final_alives
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"👑👑 **地狱之门合拢！唯一幸存神王诞生！** 👑👑\n\n"
                 f"🏆 踩着所有人的尸体，成功死磕到最后的至尊赢家是：\n"
                 f"👉 🥇 **【玩家{winner['num_id']}号：{winner['name']}】** 🥇\n\n"
                 f"💀 玩弄人心，精巧拆弹！全群的智商与运气，在这一刻被你彻底踩在脚下！"
        )
        GAME_STATE["status"] = "idle"
        return
    elif len(final_alives) == 0:
        await context.bot.send_message(chat_id=chat_id, text="💀 过于残暴！在最后一轮炼狱冲击中，场上所有人全军覆没，无人幸存！")
        GAME_STATE["status"] = "idle"
        return

    # 推进回合：让下一个活着的号码玩家发言
    GAME_STATE["turn_idx"] += 1
    next_alive_players = [p for p in GAME_STATE["players"] if p["hp"] > 0]
    next_player = next_alive_players[GAME_STATE["turn_idx"] % len(next_alive_players)]
    
    await context.bot.send_message(
        chat_id=chat_id,
        text=f"⏳ **下一个受刑者** 👉 **【{next_player['num_id']}号】玩家（{next_player['name']}）** ！请立刻在群里给出你的挣扎数值！否则死神将剥夺你的时间！"
    )

# 6. 伪装极简网页做健康检查，防止免费服务器断线
class HealthServer(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(b"Bot Running Successfully")

def run_health_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthServer)
    server.serve_forever()

if __name__ == "__main__":
    threading.Thread(target=run_health_server, daemon=True).start()
    app = Application.builder().token(BOT_TOKEN).build()