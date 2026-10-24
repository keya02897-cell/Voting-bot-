import os
import json
import re
import time
import requests
import subprocess
import tempfile
import shutil
from datetime import datetime

# =========================
# CONFIG
# =========================

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY","")
OWNER_ID = 8925611507  # Fixed owner Telegram user ID

REQUIRED_CHANNEL = "@pulkit_osint"
REQUIRED_CHANNEL_URL = "https://t.me/pulkit_osint"
VYNEX_TALK_GROUP = "@vynexaifamily"
VYNEX_TALK_GROUP_URL = "https://t.me/vynexaifamily"


OWNER_FILE = "vynex_owner.txt"
USERS_FILE = "vynex_users.json"
SETTINGS_FILE = "vynex_settings.json"
LOG_FILE = "vynex_activity.log"
VERIFIED_USERS_FILE = "vynex_verified_users.json"
CHATS_FILE = "vynex_broadcast_chats.json"
SCHEDULE_FILE = "vynex_greetings_schedule.json"
GAMES_FILE = "vynex_games.json"
CHAT_HISTORY_FILE = "vynex_chat_history.json"
CHAT_HISTORY_LIMIT = 12

GROQ_MODEL = "llama-3.3-70b-versatile"  # Faster general-purpose responses

# Smart reactions / voice replies
REACTIONS_ENABLED = True
VOICE_ENABLED = False  # Owner enables with /voice_on
TTS_VOICE = "hi-IN-SwaraNeural"

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"
GROQ_API = "https://api.groq.com/openai/v1/chat/completions"

# =========================
# BASIC CHECK
# =========================

if not BOT_TOKEN or BOT_TOKEN == "PASTE_TELEGRAM_BOT_TOKEN_HERE":
    raise SystemExit("ERROR: File mein BOT_TOKEN set karo ya VYNEX_BOT_TOKEN environment variable set karo.")

if not GROQ_API_KEY or GROQ_API_KEY == "PASTE_GROQ_API_KEY_HERE":
    raise SystemExit("ERROR: File mein GROQ_API_KEY set karo ya GROQ_API_KEY environment variable set karo.")


# =========================
# FILE HELPERS
# =========================

def load_json(filename, default):
    try:
        with open(filename, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(filename, data):
    try:
        temp_name = filename + ".tmp"
        with open(temp_name, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(temp_name, filename)
    except Exception as e:
        print("Save error:", e)


users = load_json(USERS_FILE, {})
verified_users = load_json(VERIFIED_USERS_FILE, {})
broadcast_chats = load_json(CHATS_FILE, {"private": [], "groups": []})
if not isinstance(broadcast_chats, dict):
    broadcast_chats = {"private": [], "groups": []}
game_state = load_json(GAMES_FILE, {"profiles": {}, "ludo": {}, "ttt": {}, "guess": {}, "quiz": {}, "daily": {}})
if not isinstance(game_state, dict):
    game_state = {"profiles": {}, "ludo": {}, "ttt": {}, "guess": {}, "quiz": {}, "daily": {}}
for _k in ("profiles", "ludo", "ttt", "guess", "quiz", "daily", "reminders", "birthdays", "flood"):
    game_state.setdefault(_k, {})

settings = load_json(
    SETTINGS_FILE,
    {
        "maintenance": False,
        "chat": True,
        "verification": False,
        "games": True
    }
)



# =========================
# LOGGING
# =========================

def log(text):
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {text}"

    print(line)

    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


# =========================
# TELEGRAM API
# =========================

def telegram(method, data=None):
    try:
        response = requests.post(
            f"{TELEGRAM_API}/{method}",
            json=data or {},
            timeout=75
        )

        return response.json()

    except Exception as e:
        log(f"Telegram error: {e}")
        return {}


def send_message(chat_id, text, reply_markup=None):
    data = {
        "chat_id": chat_id,
        "text": text
    }

    if reply_markup:
        data["reply_markup"] = reply_markup

    return telegram("sendMessage", data)


def send_typing(chat_id):
    """Show Telegram typing status while AI is preparing a reply."""
    try:
        telegram("sendChatAction", {"chat_id": chat_id, "action": "typing"})
    except Exception:
        pass


def answer_callback(callback_id, text=""):
    return telegram(
        "answerCallbackQuery",
        {
            "callback_query_id": callback_id,
            "text": text
        }
    )


# =========================
# REACTION + VOICE HELPERS
# =========================

def react_to_message(chat_id, message_id, user_text):
    if not REACTIONS_ENABLED:
        return

    text = (user_text or "").lower().strip()
    emoji = "👍"

    if any(x in text for x in ["😂", "🤣", "haha", "hahaha", "lol", "joke", "funny"]):
        emoji = "😂"
    elif any(x in text for x in ["love", "pyar", "pyaar", "❤️", "❤", "ily", "miss you"]):
        emoji = "❤️"
    elif any(x in text for x in ["wow", "amazing", "really", "seriously", "😮", "omg"]):
        emoji = "😮"
    elif any(x in text for x in ["sad", "dukhi", "rona", "ro raha", "ro rahi", "😢", "😭"]):
        emoji = "🥺"
    elif any(x in text for x in ["thanks", "thank you", "shukriya", "dhanyavaad"]):
        emoji = "❤️"
    elif "?" in text or any(x in text for x in ["kaise", "kya", "kyu", "kyon", "why", "how"]):
        emoji = "🤔"
    elif any(x in text for x in ["hi", "hello", "hlo", "hey", "namaste"]):
        emoji = "👋"

    try:
        result = telegram("setMessageReaction", {
            "chat_id": chat_id,
            "message_id": message_id,
            "reaction": [{"type": "emoji", "emoji": emoji}]
        })
        if not result.get("ok"):
            log(f"Reaction skipped | chat={chat_id} | message={message_id}")
    except Exception as e:
        log(f"Reaction error: {e}")


def make_voice_file(text):
    """Create a feminine Hindi/Hinglish voice note. Requires edge-tts + ffmpeg."""
    if not text:
        return None

    temp_dir = tempfile.mkdtemp(prefix="vynex_voice_")
    mp3_path = os.path.join(temp_dir, "reply.mp3")
    ogg_path = os.path.join(temp_dir, "reply.ogg")

    try:
        subprocess.run(
            [
                "edge-tts",
                "--voice", TTS_VOICE,
                "--text", text[:1800],
                "--write-media", mp3_path
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=45
        )

        subprocess.run(
            [
                "ffmpeg", "-y",
                "-i", mp3_path,
                "-vn",
                "-c:a", "libopus",
                "-b:a", "32k",
                "-application", "voip",
                ogg_path
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=45
        )

        return ogg_path

    except Exception as e:
        log(f"TTS error: {e}")
        shutil.rmtree(temp_dir, ignore_errors=True)
        return None


def send_voice(chat_id, voice_path):
    if not voice_path or not os.path.exists(voice_path):
        return {"ok": False, "description": "voice file missing"}

    try:
        with open(voice_path, "rb") as f:
            response = requests.post(
                f"{TELEGRAM_API}/sendVoice",
                data={"chat_id": chat_id},
                files={"voice": ("vynex.ogg", f, "audio/ogg")},
                timeout=45
            )
        return response.json()
    except Exception as e:
        log(f"sendVoice error: {e}")
        return {}


def send_ai_reply(chat_id, answer):
    if VOICE_ENABLED:
        voice_path = make_voice_file(answer)
        if voice_path:
            result = send_voice(chat_id, voice_path)
            shutil.rmtree(os.path.dirname(voice_path), ignore_errors=True)
            if result.get("ok"):
                return result
            log(f"Voice send failed; using text fallback.")

    return send_message(chat_id, answer)


# =========================
# MENU + LUDO DICE
# =========================

def main_menu_keyboard(user_id):
    # Put the games entry and common features in the visible keyboard.
    rows = [
        [{"text": "💬 Chat with Vynex"}, {"text": "🎮 Games"}],
        [{"text": "🔎 Web Search"}, {"text": "👤 My Profile"}],
        [{"text": "🎁 Daily Reward"}, {"text": "🏆 Leaderboard"}],
        [{"text": "ℹ️ Help"}, {"text": "🕒 Time"}],
    ]
    if is_owner(user_id):
        rows.append([{"text": "👑 Owner Panel"}])
    return {"keyboard": rows, "resize_keyboard": True, "is_persistent": True}


def show_menu(chat_id, user_id):
    text = ("🧠 Vynex AI Menu\n\nChoose an option below.\n\n"
            "🎮 Games: /games, /ludo, /ttt, /rps, /guess, /quiz\n"
            "🪙 Rewards: /daily, /profile, /leaderboard\n"
            "🌐 AI: /ask <question> | /search <query>")
    send_message(chat_id, text, main_menu_keyboard(user_id))


def send_ludo_dice(chat_id):
    # Telegram renders this as its native animated dice (1–6).
    result = telegram("sendDice", {"chat_id": chat_id, "emoji": "🎲"})
    if not result.get("ok"):
        send_message(chat_id, "🎲 Dice abhi roll nahi ho paaya. Thodi der baad try karo.")
    return result


# =========================
# MINI GAMES, LUDO ROOMS & VIRTUAL REWARDS
# =========================

def save_games():
    save_json(GAMES_FILE, game_state)


def profile_for(user_id, name="Player"):
    key = str(user_id)
    profiles = game_state["profiles"]
    if key not in profiles:
        profiles[key] = {"name": name or "Player", "coins": 0, "wins": 0, "games": 0, "badges": []}
    profiles[key]["name"] = name or profiles[key].get("name", "Player")
    return profiles[key]


def game_keyboard(rows):
    return {"inline_keyboard": rows}


def show_games(chat_id):
    keyboard = {
        "keyboard": [
            [{"text": "🎲 Ludo"}, {"text": "❌ Tic-Tac-Toe"}],
            [{"text": "✊ Rock Paper Scissors"}, {"text": "🔢 Number Guess"}],
            [{"text": "🧠 Quiz"}, {"text": "🎁 Daily Reward"}],
            [{"text": "👤 My Profile"}, {"text": "🏆 Leaderboard"}],
            [{"text": "🔙 Main Menu"}],
        ], "resize_keyboard": True, "is_persistent": True
    }
    send_message(chat_id,
        "🎮 Vynex Games — choose a game below\n\n"
        "🎲 Multiplayer Ludo: 2–4 players — /ludo, /ludo_join, /ludo_start, /ludo_roll, /ludo_move 1-4\n"
        "❌ Tic-Tac-Toe: /ttt then friend uses /ttt_join\n"
        "✊ RPS: /rps rock, /rps paper, /rps scissors\n"
        "🔢 Number Guess: /guess then /g <number>\n"
        "🧠 Quiz: /quiz\n"
        "🪙 Rewards: /daily, /profile, /leaderboard", keyboard)


def start_ludo(chat_id, user):
    uid=user.get("id"); name=user.get("first_name","Player")
    room=game_state["ludo"].get(str(chat_id))
    if room and not room.get("finished"):
        if any(p["id"]==uid for p in room["players"]):
            send_message(chat_id,f"🎲 Ludo room active ({len(room['players'])}/4). Use /ludo_roll then /ludo_move 1-4.")
        else: send_message(chat_id,"A Ludo room already exists. Join with /ludo_join.")
        return
    game_state["ludo"][str(chat_id)]={"players":[{"id":uid,"name":name,"tokens":[-1,-1,-1,-1]}],"turn":0,"finished":False,"started":False,"last_roll":None,"rolled_by":None}
    save_games(); send_message(chat_id,f"🎲 Ludo room created by {name}!\n👥 Players: 1/4\nSecond player(s), tap Join Ludo below. Creator starts after at least 2 players join.", game_keyboard([[{"text":"🎮 Join Ludo","callback_data":"ludo_join"}], [{"text":"▶️ Start Ludo","callback_data":"ludo_start"}]]))


def join_ludo(chat_id,user):
    room=game_state["ludo"].get(str(chat_id)); uid=user.get("id"); name=user.get("first_name","Player")
    if not room or room.get("finished"):
        send_message(chat_id,"❌ No waiting Ludo room. Create one with /ludo."); return
    if any(p["id"]==uid for p in room["players"]): send_message(chat_id,"You are already in this Ludo room."); return
    if room.get("started"): send_message(chat_id,"Game already started; new players cannot join this round."); return
    if len(room["players"])>=4: send_message(chat_id,"❌ Ludo room is full (4 players)."); return
    room["players"].append({"id":uid,"name":name,"tokens":[-1,-1,-1,-1]}); save_games()
    send_message(chat_id,f"✅ {name} joined! Players: {len(room['players'])}/4. Creator can start with the button below.", game_keyboard([[{"text":"🎮 Join Ludo","callback_data":"ludo_join"}], [{"text":"▶️ Start Ludo","callback_data":"ludo_start"}]]))


def ludo_start(chat_id,user):
    room=game_state["ludo"].get(str(chat_id))
    if not room or room.get("finished"): send_message(chat_id,"Create a room first with /ludo."); return
    if room["players"][0]["id"]!=user.get("id"): send_message(chat_id,"Only the room creator can start the game."); return
    if len(room["players"])<2: send_message(chat_id,"Need at least 2 players. Ask friends to use /ludo_join."); return
    room["started"]=True; room["turn"]=0; room["last_roll"]=None; save_games()
    send_message(chat_id,"🎲 Ludo started! Roll a 6 to bring a token out of the yard. Reach home with an exact roll. Safe squares protect tokens. Tap Roll Dice, then choose a token. First to get all 4 tokens home wins.", game_keyboard([[{"text":"🎲 Roll Dice","callback_data":"ludo_roll"}]]))
    ludo_status(chat_id,room)


def ludo_status(chat_id,room):
    lines=["🎲 Ludo board status:"]
    for p in room["players"]:
        positions=["Yard" if x==-1 else ("Home" if x==57 else str(x+1)+"/57") for x in p["tokens"]]
        lines.append(f"• {p['name']}: " + ", ".join(f"T{i+1}={v}" for i,v in enumerate(positions)))
    if room.get("started") and not room.get("finished"):
        lines.append(f"Current turn: {room['players'][room['turn']]['name']}")
        if room.get("last_roll") is not None: lines.append(f"Roll: {room['last_roll']} — use /ludo_move 1-4")
        else: lines.append("Use /ludo_roll")
    markup = None
    if room.get("started") and not room.get("finished") and room.get("last_roll") is None:
        markup = game_keyboard([[{"text":"🎲 Roll Dice","callback_data":"ludo_roll"}]])
    send_message(chat_id,"\n".join(lines), markup)


def ludo_roll(chat_id,user):
    import random
    room=game_state["ludo"].get(str(chat_id))
    if not room or room.get("finished") or not room.get("started"):
        send_message(chat_id,"No started Ludo game. Use /ludo, /ludo_join, then /ludo_start."); return
    player=room["players"][room["turn"]]
    if player["id"]!=user.get("id"): send_message(chat_id,f"⏳ Abhi {player['name']} ki turn hai."); return
    if room.get("last_roll") is not None: send_message(chat_id,"Move your previous roll first with /ludo_move 1-4."); return
    roll=random.randint(1,6); room["last_roll"]=roll; room["rolled_by"]=player["id"]
    available=[i+1 for i,pos in enumerate(player["tokens"]) if (pos==-1 and roll==6) or (pos>=0 and pos<57 and pos+roll<=57)]
    save_games()
    send_message(chat_id,f"🎲 {player['name']} rolled {roll}!\nMovable tokens: {', '.join(map(str,available)) if available else 'none'}\n" + ("Choose a token below." if available else "No legal move; turn passed."), game_keyboard([[{"text":f"Token {n}","callback_data":f"ludo_move_{n}"} for n in available]] if available else [[{"text":"Next turn","callback_data":"ludo_skip"}]]))
    if not available:
        ludo_skip(chat_id,user)


def ludo_move(chat_id,user,text):
    room=game_state["ludo"].get(str(chat_id))
    if not room or room.get("finished") or not room.get("started"):
        send_message(chat_id,"No active Ludo game."); return
    player=room["players"][room["turn"]]
    if player["id"]!=user.get("id"): send_message(chat_id,f"⏳ Abhi {player['name']} ki turn hai."); return
    roll=room.get("last_roll")
    if roll is None: send_message(chat_id,"First roll the dice with /ludo_roll."); return
    try: idx=int(text.split(maxsplit=1)[1])-1
    except Exception: send_message(chat_id,"Use /ludo_move 1 (token number 1–4)."); return
    if idx not in range(4): send_message(chat_id,"Token number 1–4 choose karo."); return
    old=player["tokens"][idx]
    if old==-1:
        if roll!=6: send_message(chat_id,"Yard se token nikalne ke liye 6 chahiye."); return
        new=0
    else:
        if old+roll>57: send_message(chat_id,"Home pahunchne ke liye exact roll chahiye."); return
        new=old+roll
    player["tokens"][idx]=new; extra=(roll==6)
    captured=[]
    if 0<=new<52:
        global_pos=(room["turn"]*13+new)%52
        safe={0,8,13,21,26,34,39,47}
        if global_pos not in safe:
            for oi,op in enumerate(room["players"]):
                if oi==room["turn"]: continue
                for ti,pos in enumerate(op["tokens"]):
                    if 0<=pos<52 and (oi*13+pos)%52==global_pos:
                        op["tokens"][ti]=-1; captured.append(f"{op['name']} T{ti+1}")
    out=f"🟢 {player['name']} moved token {idx+1} by {roll} (position {new}/57)."
    if captured: out+="\n💥 Captured: "+", ".join(captured)+" — sent back to yard!"
    if all(x==57 for x in player["tokens"]):
        room["finished"]=True; prof=profile_for(player["id"],player["name"]); prof["wins"]+=1; prof["coins"]+=50
        out+=f"\n🏆 {player['name']} wins Ludo and earns 50 virtual coins!"
    else:
        room["last_roll"]=None; room["rolled_by"]=None
        if not extra: room["turn"]=(room["turn"]+1)%len(room["players"])
        else: out+="\n🎉 You rolled a 6 — extra turn!"
    save_games(); send_message(chat_id,out); ludo_status(chat_id,room)


def ludo_skip(chat_id,user):
    room=game_state["ludo"].get(str(chat_id))
    if not room or room.get("finished") or room.get("last_roll") is None: send_message(chat_id,"No Ludo move to skip."); return
    player=room["players"][room["turn"]]
    if player["id"]!=user.get("id"): send_message(chat_id,"Not your turn."); return
    room["last_roll"]=None; room["rolled_by"]=None; room["turn"]=(room["turn"]+1)%len(room["players"]); save_games()
    send_message(chat_id,"Turn passed. Next player: "+room["players"][room["turn"]]["name"]); ludo_status(chat_id,room)


def start_ttt(chat_id, user):
    uid=user.get("id"); name=user.get("first_name","Player"); room=game_state["ttt"].get(str(chat_id))
    if room and not room.get("finished"):
        send_message(chat_id,"A Tic-Tac-Toe room is already open. Another player can use /ttt_join."); return
    game_state["ttt"][str(chat_id)]={"players":[{"id":uid,"name":name,"mark":"❌"}],"board":["⬜"]*9,"turn":0,"finished":False}
    save_games(); send_message(chat_id,f"❌ Tic-Tac-Toe room created by {name}. Another player tap Join Tic-Tac-Toe below.", game_keyboard([[{"text":"⭕ Join Tic-Tac-Toe","callback_data":"ttt_join"}]]))


def ttt_board(room):
    rows=[]
    for r in range(3): rows.append([{"text":room["board"][r*3+c],"callback_data":f"ttt_{r*3+c}"} for c in range(3)])
    return game_keyboard(rows)


def ttt_render(chat_id, room, intro="Tic-Tac-Toe: players take turns."):
    send_message(chat_id,intro+"\n"+" | ".join(room["board"][:3])+"\n"+" | ".join(room["board"][3:6])+"\n"+" | ".join(room["board"][6:9]),ttt_board(room))


def join_ttt(chat_id,user):
    room=game_state["ttt"].get(str(chat_id)); uid=user.get("id")
    if not room or room.get("finished"):
        send_message(chat_id,"No open Tic-Tac-Toe room. Use /ttt first."); return
    if len(room["players"])!=1 or room["players"][0]["id"]==uid:
        send_message(chat_id,"Room needs a different second player."); return
    room["players"].append({"id":uid,"name":user.get("first_name","Player"),"mark":"⭕"}); save_games()
    ttt_render(chat_id,room,f"❌ {room['players'][0]['name']} vs ⭕ {room['players'][1]['name']} — {room['players'][0]['name']} starts.")


def ttt_move(callback, chat_id, user_id, idx):
    room=game_state["ttt"].get(str(chat_id))
    if not room or room.get("finished") or len(room["players"])<2:
        answer_callback(callback,"Game isn't ready."); return
    player=room["players"][room["turn"]]
    if player["id"]!=user_id:
        answer_callback(callback,"Not your turn!"); return
    if idx<0 or idx>8 or room["board"][idx]!="⬜":
        answer_callback(callback,"That square is taken."); return
    room["board"][idx]=player["mark"]
    lines=[(0,1,2),(3,4,5),(6,7,8),(0,3,6),(1,4,7),(2,5,8),(0,4,8),(2,4,6)]
    winner=any(room["board"][a]==room["board"][b]==room["board"][c]==player["mark"] for a,b,c in lines)
    if winner or "⬜" not in room["board"]:
        room["finished"]=True
        if winner:
            prof=profile_for(player["id"],player["name"]); prof["wins"]+=1; prof["coins"]+=10
            intro=f"🏆 {player['name']} ({player['mark']}) wins and gets 10 coins!"
        else: intro="🤝 It's a draw!"
    else:
        room["turn"]=(room["turn"]+1)%2; intro=f"Next turn: {room['players'][room['turn']]['name']} ({room['players'][room['turn']]['mark']})."
    save_games(); answer_callback(callback,"Move saved")
    ttt_render(chat_id,room,intro if room["finished"] else intro)


def play_rps(chat_id,user,text):
    import random
    choice=text.split(maxsplit=1)[1].lower().strip() if len(text.split(maxsplit=1))>1 else ""
    aliases={"rock":"rock","stone":"rock","✊":"rock","paper":"paper","📄":"paper","scissors":"scissors","✂️":"scissors"}
    choice=aliases.get(choice,choice)
    if choice not in ("rock","paper","scissors"):
        send_message(chat_id,"Choose your move:",game_keyboard([[{"text":"✊ Rock","callback_data":"rps_rock"},{"text":"📄 Paper","callback_data":"rps_paper"},{"text":"✂️ Scissors","callback_data":"rps_scissors"}]])); return
    bot=random.choice(["rock","paper","scissors"]); p=profile_for(user["id"],user.get("first_name","Player")); p["games"]+=1
    if choice==bot: result="🤝 Draw!"
    elif (choice,bot) in (("rock","scissors"),("paper","rock"),("scissors","paper")):
        result="🏆 You win! +5 coins"; p["coins"]+=5; p["wins"]+=1
    else: result="🤖 Bot wins this round."
    save_games(); send_message(chat_id,f"✊ You: {choice}\n🤖 Bot: {bot}\n{result}")


def start_guess(chat_id,user):
    import random
    game_state["guess"][str(chat_id)]={"answer":random.randint(1,20),"user":user["id"],"tries":0,"name":user.get("first_name","Player")}; save_games()
    send_message(chat_id,"🔢 I'm thinking of a number from 1 to 20. Send /g <number> to guess!")


def guess_number(chat_id,user,text):
    room=game_state["guess"].get(str(chat_id))
    if not room:
        send_message(chat_id,"Start a game first with /guess."); return
    try: n=int(text.split(maxsplit=1)[1])
    except Exception: send_message(chat_id,"Use /g <number> (1–20)."); return
    if n<1 or n>20: send_message(chat_id,"Choose a number from 1 to 20."); return
    room["tries"]+=1
    if n==room["answer"]:
        p=profile_for(user["id"],user.get("first_name","Player")); p["coins"]+=max(2,12-room["tries"]); p["wins"]+=1
        send_message(chat_id,f"🎉 Correct! {n} was the number. You earned {max(2,12-room['tries'])} coins.")
        game_state["guess"].pop(str(chat_id),None)
    else: send_message(chat_id,"📈 Too low!" if n<room["answer"] else "📉 Too high!")
    save_games()


def play_quiz(chat_id,user):
    import random
    questions=[("Which planet is known as the Red Planet?",["Earth","Mars","Venus"],1),("How many sides does a hexagon have?",["5","6","8"],1),("What is 9 × 7?",["56","63","72"],1),("Which gas do plants absorb?",["Oxygen","Carbon dioxide","Helium"],1)]
    q=random.choice(questions); game_state["quiz"][str(chat_id)]={"answer":q[2],"user":user["id"]}; save_games()
    send_message(chat_id,"🧠 Quiz: "+q[0],game_keyboard([[{"text":a,"callback_data":f"quiz_{i}"} for i,a in enumerate(q[1])]]))


def daily_reward(chat_id,user):
    from datetime import date, timedelta
    uid=str(user["id"]); today=date.today().isoformat()
    p=profile_for(user["id"],user.get("first_name","Player"))
    if game_state["daily"].get(uid)==today:
        send_message(chat_id,"🪙 Aaj ka daily reward le chuke ho. Kal phir aana!"); return
    yesterday=(date.today()-timedelta(days=1)).isoformat()
    p["streak"] = (p.get("streak",0)+1) if p.get("last_daily")==yesterday else 1
    p["last_daily"]=today
    reward=10+min(20,max(0,p["streak"]-1))
    p["coins"]+=reward
    if p["streak"]>=7 and "7-day streak" not in p["badges"]: p["badges"].append("7-day streak")
    game_state["daily"][uid]=today; save_games()
    send_message(chat_id,f"🎁 Daily reward: +{reward} virtual coins!\n🔥 Login streak: {p['streak']} day(s). Real-money value nahi hai.")

def show_profile(chat_id,user):
    p=profile_for(user["id"],user.get("first_name","Player")); save_games()
    send_message(chat_id,f"👤 Profile: {p['name']}\n🪙 Virtual coins: {p['coins']}\n🏆 Wins: {p['wins']}\n🎮 Games played: {p['games']}\n🔥 Daily streak: {p.get('streak',0)} day(s)\n🎖️ Badges: {', '.join(p['badges']) if p['badges'] else 'None yet'}")


def show_leaderboard(chat_id):
    top=sorted(game_state["profiles"].values(),key=lambda p:p.get("coins",0),reverse=True)[:10]
    if not top: send_message(chat_id,"Leaderboard abhi empty hai."); return
    send_message(chat_id,"🏆 Virtual Coins Leaderboard\n"+"\n".join(f"{i}. {p.get('name','Player')} — {p.get('coins',0)} coins" for i,p in enumerate(top,1)))


def weather_lookup(chat_id, city):
    try:
        g=requests.get("https://geocoding-api.open-meteo.com/v1/search",params={"name":city,"count":1,"language":"en","format":"json"},timeout=12).json()
        places=g.get("results",[])
        if not places: send_message(chat_id,"City nahi mili. Use: /weather <city>"); return
        place=places[0]
        w=requests.get("https://api.open-meteo.com/v1/forecast",params={"latitude":place["latitude"],"longitude":place["longitude"],"current":"temperature_2m,relative_humidity_2m,apparent_temperature,wind_speed_10m","timezone":"auto"},timeout=12).json().get("current",{})
        send_message(chat_id,f"🌦️ Weather — {place['name']}, {place.get('country','')}\n🌡️ Temperature: {w.get('temperature_2m','?')}°C\n🤗 Feels like: {w.get('apparent_temperature','?')}°C\n💧 Humidity: {w.get('relative_humidity_2m','?')}%\n💨 Wind: {w.get('wind_speed_10m','?')} km/h")
    except Exception as e:
        log(f"Weather error: {e}"); send_message(chat_id,"Weather abhi available nahi hai. Thodi der baad try karo.")


def set_birthday(chat_id,user,text):
    try:
        value=text.split(maxsplit=1)[1].strip()
        from datetime import datetime as _dt
        parsed=_dt.strptime(value,"%d-%m")
        game_state["birthdays"][str(user["id"]) ]={"name":user.get("first_name","Player"),"date":parsed.strftime("%m-%d")}
        save_games(); send_message(chat_id,"🎂 Birthday saved! Format /birthday DD-MM. Sirf month/day store kiya hai.")
    except Exception: send_message(chat_id,"Use: /birthday DD-MM (example: /birthday 24-12)")


def create_poll(chat_id,text):
    try:
        parts=[x.strip() for x in text.split(maxsplit=1)[1].split("|")]
        if len(parts)<3: raise ValueError()
        question=parts[0]; options=parts[1:11]
        telegram("sendPoll",{"chat_id":chat_id,"question":question[:300],"options":options,"is_anonymous":False})
    except Exception: send_message(chat_id,"Use: /poll Question | Option 1 | Option 2 [| Option 3]")


def set_reminder(chat_id,user,text):
    # /remind 10m message, /remind 2h message, /remind 1d message
    import re
    m=re.match(r"/remind\s+(\d+)(m|h|d)\s+(.+)",text,re.I)
    if not m:
        send_message(chat_id,"Use: /remind 10m pani peena  (m=minutes, h=hours, d=days)"); return
    amount=int(m.group(1)); unit=m.group(2).lower(); body=m.group(3).strip()
    if amount<1 or amount>10080: send_message(chat_id,"Reminder duration 1 se 10080 units tak supported hai."); return
    seconds=amount*({"m":60,"h":3600,"d":86400}[unit])
    game_state["reminders"].append({"chat_id":chat_id,"user_id":user.get("id"),"text":body,"due":time.time()+seconds})
    save_games(); send_message(chat_id,f"⏰ Reminder set! {amount}{unit} baad yaad dilaunga.")


def check_reminders():
    now=time.time(); keep=[]
    for item in game_state.get("reminders",[]):
        if item.get("due",now+1)<=now:
            send_message(item["chat_id"],f"⏰ Reminder: {item.get('text','')}")
        else: keep.append(item)
    if len(keep)!=len(game_state.get("reminders",[])):
        game_state["reminders"]=keep; save_games()


def show_rules(chat_id):
    send_message(chat_id,"📜 Group Rules\n1. Respect everyone.\n2. No spam or flooding.\n3. No scams or harmful links.\n4. Follow Telegram rules and admin instructions.\nAdmins can edit these rules in their group description.")


# =========================
# OWNER SYSTEM
# =========================

def get_owner():
    # The configured owner ID is authoritative; owner file is retained for compatibility.
    return str(OWNER_ID)


def get_owner_legacy():
    try:
        with open(OWNER_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return None


def set_owner(user_id):
    with open(OWNER_FILE, "w", encoding="utf-8") as f:
        f.write(str(user_id))


def is_owner(user_id):
    return str(user_id) == str(OWNER_ID)


# =========================
# USER SYSTEM
# =========================

def register_user(user):
    user_id = str(user["id"])

    if user_id not in users:
        users[user_id] = {
            "id": user["id"],
            "first_name": user.get("first_name", ""),
            "username": user.get("username", ""),
            "joined": datetime.now().isoformat(),
            "messages": 0,
        }

        save_json(USERS_FILE, users)

    else:
        users[user_id]["first_name"] = user.get(
            "first_name",
            users[user_id].get("first_name", "")
        )

        users[user_id]["username"] = user.get(
            "username",
            users[user_id].get("username", "")
        )

        save_json(USERS_FILE, users)


# =========================
# GLOBAL VERIFICATION
# =========================

def is_channel_member(user_id):
    result = telegram("getChatMember", {
        "chat_id": REQUIRED_CHANNEL,
        "user_id": user_id
    })
    if not result.get("ok"):
        return False

    member = result.get("result", {})
    status = member.get("status")

    if status in ["creator", "administrator", "member"]:
        return True
    if status == "restricted" and member.get("is_member") is True:
        return True
    return False


def is_vynex_group_member(user_id):
    result = telegram("getChatMember", {
        "chat_id": VYNEX_TALK_GROUP,
        "user_id": user_id
    })
    if not result.get("ok"):
        return False

    member = result.get("result", {})
    status = member.get("status")

    if status in ["creator", "administrator", "member"]:
        return True
    if status == "restricted" and member.get("is_member") is True:
        return True
    return False


def is_verified(user_id):
    # Always refresh from disk so verification works even if more than one
    # Vynex process is/was running. This also survives bot restarts cleanly.
    global verified_users
    latest = load_json(VERIFIED_USERS_FILE, {})
    if isinstance(latest, dict):
        verified_users = latest
    verified = str(user_id) in verified_users
    if verified:
        log(f"Verification found | user={user_id} | saved=true")
    return verified


def mark_verified(user_id):
    global verified_users
    latest = load_json(VERIFIED_USERS_FILE, {})
    verified_users = latest if isinstance(latest, dict) else {}
    verified_users[str(user_id)] = {"verified_at": datetime.now().isoformat()}
    save_json(VERIFIED_USERS_FILE, verified_users)
    log(f"Verification saved | user={user_id}")


def verification_keyboard():
    return {
        "inline_keyboard": [
            [{"text": "📢 Join Channel", "url": REQUIRED_CHANNEL_URL}],
            [{"text": "👥 Join VynexAITalk", "url": VYNEX_TALK_GROUP_URL}],
            [{"text": "✅ Check Joined", "callback_data": "check_joined"}]
        ]
    }


def require_verification(chat_id, user_id):
    # Verification is globally controlled by the owner.
    if not settings.get("verification", False):
        return True

    # Do not ask the same verified user again after restart.
    if is_verified(user_id):
        log(f"Verification bypass | user={user_id} | already verified")
        return True

    channel_ok = is_channel_member(user_id)
    group_ok = is_vynex_group_member(user_id)

    if channel_ok and group_ok:
        mark_verified(user_id)
        return True

    missing = []
    if not channel_ok:
        missing.append("📢 Channel")
    if not group_ok:
        missing.append("👥 VynexAITalk group")

    send_message(
        chat_id,
        "🔒 Vynex verification required.\n\n"
        "Vynex use karne ke liye pehle ye join karo:\n"
        + "\n".join(missing)
        + "\n\nJoin karne ke baad '✅ Check Joined' dabao.",
        verification_keyboard()
    )
    return False


# Existing calls remain compatible.
def require_channel(chat_id, user_id):
    return require_verification(chat_id, user_id)



# =========================
# GEMINI AI
# =========================

class _SearchHTMLParser(__import__("html.parser", fromlist=["HTMLParser"]).HTMLParser):
    """Small dependency-free parser for DuckDuckGo HTML search results."""
    def __init__(self):
        super().__init__()
        self.results = []
        self._current = None
        self._capture = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = attrs.get("class", "")
        if tag == "a" and ("result__a" in classes or "result-link" in classes):
            self._current = {"title": "", "url": attrs.get("href", ""), "snippet": ""}
            self.results.append(self._current)
            self._capture = "title"
        elif tag in ("a", "div", "td") and ("result__snippet" in classes or "result-snippet" in classes):
            self._capture = "snippet"

    def handle_data(self, data):
        if self._current and self._capture in ("title", "snippet"):
            self._current[self._capture] += data.strip() + " "

    def handle_endtag(self, tag):
        if tag == "a" and self._capture == "title":
            self._capture = None
        elif tag in ("div", "td") and self._capture == "snippet":
            self._capture = None


def web_search(query, limit=5):
    """Search the public web using DuckDuckGo HTML; no separate search API key needed."""
    query = (query or "").strip()
    if not query:
        return []
    try:
        response = requests.get(
            "https://html.duckduckgo.com/html/",
            params={"q": query},
            headers={"User-Agent": "Mozilla/5.0 (compatible; VynexAI/1.0)"},
            timeout=6,
        )
        response.raise_for_status()
        parser = _SearchHTMLParser()
        parser.feed(response.text)
        # Keep unique results and only safe, normal web links.
        results, seen = [], set()
        for item in parser.results:
            url = item.get("url", "")
            if url.startswith("//"):
                url = "https:" + url
            if not url.startswith("http") or url in seen:
                continue
            seen.add(url)
            item["url"] = url
            results.append(item)
            if len(results) >= limit:
                break
        return results
    except Exception as exc:
        log(f"Web search error: {type(exc).__name__}: {exc}")
        return []


def format_search_results(results):
    if not results:
        return "No reliable web results were retrieved. Do not invent sources; answer from existing knowledge and mention that live search was unavailable."
    lines = []
    for i, item in enumerate(results, 1):
        title = item.get("title", "Untitled").strip()
        snippet = item.get("snippet", "").strip()
        url = item.get("url", "")
        lines.append(f"{i}. {title}\n{snippet}\nSource: {url}")
    return "\n\n".join(lines)


def needs_web_search(user_text):
    text = (user_text or "").lower()
    triggers = (
        "latest", "today", "current", "right now", "this week", "breaking", "news",
        "recent", "2026", "weather", "score", "standings", "price today", "update",
        "source", "sources", "search web", "web search", "internet par", "online search",
        "abhi ka", "aaj ka", "taaza", "latest bata", "khabar", "मौसम", "आज की खबर",
    )
    return any(term in text for term in triggers)


def ask_groq(user_text, chat_id=None, force_search=False):
    """General-purpose Vynex AI with conversation context and optional live web results."""
    personality = (
        "You are Vynex AI, a capable general-purpose assistant. You can help with general knowledge, "
        "science, history, maths, study help, coding, writing, translation, reasoning, and everyday questions. "
        "Answer the actual question rather than refusing just because it is not a predefined command. "
        "Use natural Hindi/Hinglish/English matching the user. Be warm and clear, and give detail when asked. "
        "You are an AI, not a real human; be transparent if asked. Never invent facts, citations, or URLs. "
        "For current facts, prioritize the supplied web results, distinguish confirmed facts from uncertainty, "
        "and include useful source URLs. If results are weak or absent, say live verification was unavailable. "
        "Do not claim you can guarantee every answer is correct."
    )
    history_store = load_json(CHAT_HISTORY_FILE, {})
    if not isinstance(history_store, dict):
        history_store = {}
    key = str(chat_id) if chat_id is not None else "default"
    history = history_store.get(key, [])
    if not isinstance(history, list):
        history = []

    search_results = []
    if force_search or needs_web_search(user_text):
        search_results = web_search(user_text, limit=5)

    messages = [{"role": "system", "content": personality}]
    if search_results:
        messages.append({
            "role": "system",
            "content": "Live web search results (treat snippets as evidence, not guaranteed truth):\n\n" + format_search_results(search_results)
        })
    messages.extend(history[-CHAT_HISTORY_LIMIT:])
    messages.append({"role": "user", "content": user_text})

    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {GROQ_API_KEY}"}
    payload = {"model": GROQ_MODEL, "messages": messages, "max_tokens": 700, "temperature": 0.4}
    try:
        response = requests.post(GROQ_API, headers=headers, json=payload, timeout=25)
        try:
            data = response.json()
        except ValueError:
            data = {}
        if response.status_code != 200:
            log(f"Groq API error: {response.status_code} {str(data)[:500]}")
            return "❌ AI API error aaya. API key/model check karo ya thodi der baad try karo."
        choices = data.get("choices", [])
        if not choices:
            return "❌ AI ne koi response nahi diya. Dobara try karo."
        answer = (choices[0].get("message", {}).get("content") or "").strip()
        if not answer:
            return "❌ AI ka response khaali aaya. Dobara try karo."
        # Persist only recent text context to support follow-up questions.
        history.extend([
            {"role": "user", "content": user_text[:4000]},
            {"role": "assistant", "content": answer[:5000]},
        ])
        history_store[key] = history[-CHAT_HISTORY_LIMIT:]
        save_json(CHAT_HISTORY_FILE, history_store)
        return answer
    except requests.exceptions.Timeout:
        return "⏳ AI response mein zyada time lag raha hai. Dobara try karo."
    except Exception as exc:
        log(f"Groq exception: {type(exc).__name__}: {exc}")
        return "❌ AI se connect nahi ho paaya. Internet aur API key check karo."


# =========================
# COMMANDS
# =========================

def start_command(chat_id, user):
    name = user.get("first_name", "User")
    send_message(
        chat_id,
        f"👋 Hello {name}!\n\n"
        "🧠 Welcome to Vynex AI. Main ek friendly AI assistant hoon.\n\n"
        "💬 Private chat mein apna message bhejo. Group mein reply ke liye mujhe mention karo ya mere message par reply karo.\n"
        "🎲 Ludo Dice bhi menu se roll kar sakte ho.",
        main_menu_keyboard(user.get("id"))
    )


def help_command(chat_id, user_id=None):
    text = (
        "🧠 Vynex AI Help\n\n"
        "• /start ya /menu — menu kholo\n"
        "• /help — help\n"
        "• /ping — bot status\n"
        "• /id — Telegram ID\n"
        "• /time — current time\n"
        "• /dice — Ludo dice roll\n"
        "• /games — mini games menu\n"
        "• /ludo, /ludo_join, /ludo_start, /ludo_roll, /ludo_move 1-4 — Ludo\n"
        "• /ttt, /ttt_join — Tic-Tac-Toe\n"
        "• /rps <rock|paper|scissors> — RPS\n"
        "• /guess then /g <number> — number guessing\n"
        "• /quiz — quick quiz\n"
        "• /daily, /profile, /leaderboard — virtual rewards\n"
        "• /weather <city> — current weather\n"
        "• /remind 10m <text> — reminder\n"
        "• /poll Q | A | B — group poll\n"
        "• /birthday DD-MM — save birthday\n"
        "• /rules — group rules\n"
        "• /search <query> — internet par search\n"
        "• /ask <question> — AI se sawaal\n\n"
        "AI kisi bhi topic par sawaal le sakta hai. Latest info ke liye /search <query>; AI ke liye /ask <question>.\n\nGroup mein main sirf tab reply karunga jab aap mujhe mention karoge, mere message par reply karoge, ya seedha Vynex ko bulaoge."
    )
    if user_id is not None and is_owner(user_id):
        text += "\n\n👑 Owner commands: /ownerpanel, /stats, /logs, /chat_on, /chat_off, /maintenance_on, /maintenance_off, /broadcast, /verify_on, /verify_off, /verify_status, /voice_on, /voice_off, /voice_status"
    send_message(chat_id, text, main_menu_keyboard(user_id) if user_id else None)


# =========================
# OWNER COMMANDS
# =========================

def owner_only(chat_id, user_id):
    if not is_owner(user_id):
        send_message(chat_id, "❌ Ye command sirf owner ke liye hai.")
        return False

    return True


def owner_panel(chat_id, user_id):
    # Do not reveal that a private owner panel exists to non-owners.
    if not is_owner(user_id):
        return
    keyboard = {"inline_keyboard": [
        [{"text": "📊 Stats", "callback_data": "owner_stats"}, {"text": "📋 Logs", "callback_data": "owner_logs"}],
        [{"text": "🎮 Games ON", "callback_data": "owner_games_on"}, {"text": "🎮 Games OFF", "callback_data": "owner_games_off"}],
        [{"text": "🤖 Chat ON", "callback_data": "owner_chat_on"}, {"text": "🔕 Chat OFF", "callback_data": "owner_chat_off"}],
        [{"text": "🟢 Maintenance OFF", "callback_data": "owner_maintenance_off"}, {"text": "🔴 Maintenance ON", "callback_data": "owner_maintenance_on"}],
        [{"text": "🔐 Verify ON", "callback_data": "owner_verify_on"}, {"text": "🔓 Verify OFF", "callback_data": "owner_verify_off"}],
        [{"text": "🎙️ Voice ON", "callback_data": "owner_voice_on"}, {"text": "🔇 Voice OFF", "callback_data": "owner_voice_off"}],
    ]}
    send_message(chat_id, "👑 Owner Panel\n\nSirf aapko dikhne wala control menu.", keyboard)


def stats_command(chat_id, user_id):
    if not owner_only(chat_id, user_id):
        return

    total_users = len(users)

    total_messages = sum(
        u.get("messages", 0)
        for u in users.values()
    )


    send_message(
        chat_id,
        f"📊 **Vynex Stats**\n\n"
        f"👥 Users: {total_users}\n"
        f"💬 Messages: {total_messages}\n"
        f"🔴 Maintenance: {settings.get('maintenance', False)}\n"
        f"🤖 Chat: {settings.get('chat', True)}\n"
        f"🔐 Verification: {settings.get('verification', False)}"
    )


def logs_command(chat_id, user_id):
    if not owner_only(chat_id, user_id):
        return

    try:
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()[-20:]

        if not lines:
            send_message(chat_id, "📋 No logs yet.")
            return

        text = "📋 Last 20 logs:\n\n" + "".join(lines)

        if len(text) > 4000:
            text = text[-4000:]

        send_message(chat_id, text)

    except Exception:
        send_message(chat_id, "📋 Log file empty hai.")


def remember_broadcast_chat(chat):
    """Remember private chats and groups for future owner broadcasts/greetings."""
    chat_id = chat.get("id")
    chat_type = chat.get("type")
    if not chat_id:
        return
    bucket = "private" if chat_type == "private" else "groups" if chat_type in ("group", "supergroup") else None
    if not bucket:
        return
    ids = broadcast_chats.setdefault(bucket, [])
    if chat_id not in ids:
        ids.append(chat_id)
        save_json(CHATS_FILE, broadcast_chats)


def broadcast_destinations():
    # Only private chats that have interacted with the bot, plus groups where it has seen messages.
    ids = set(broadcast_chats.get("private", [])) | set(broadcast_chats.get("groups", []))
    # Backward compatibility: include known users, but Telegram may reject DMs not initiated by users.
    ids.update(int(uid) for uid in users.keys() if str(uid).lstrip("-").isdigit())
    return sorted(ids, key=str)


def broadcast_command(chat_id, user_id, message_text="", source_message=None):
    if not owner_only(chat_id, user_id):
        return

    if not message_text and not source_message:
        send_message(chat_id, "Kisi message/photo/video/GIF par reply karke /broadcast likho, ya /broadcast Apna text bhejo.")
        return

    success = 0
    failed = 0
    destinations = broadcast_destinations()
    for destination in destinations:
        if source_message:
            result = telegram("copyMessage", {
                "chat_id": destination,
                "from_chat_id": source_message.get("chat", {}).get("id", chat_id),
                "message_id": source_message.get("message_id")
            })
        else:
            result = send_message(destination, message_text)
        if result.get("ok"):
            success += 1
        else:
            failed += 1
        time.sleep(0.06)

    send_message(chat_id, f"📢 Broadcast complete.\n\n✅ Sent: {success}\n❌ Failed: {failed}\n👥 Targets: {len(destinations)}")


def send_daily_greeting(kind):
    if kind == "morning":
        greeting = "🌞 Good morning everyone! Naya din khushiyon aur positive vibes se bhara ho. 💛"
    else:
        greeting = "🌙 Good night everyone! Achhe se rest karo, sweet dreams. 💜 Kal phir milte hain!"
    sent = failed = 0
    for destination in broadcast_destinations():
        result = send_message(destination, greeting)
        if result.get("ok"):
            sent += 1
        else:
            failed += 1
        time.sleep(0.06)
    log(f"Daily {kind} greeting | sent={sent} | failed={failed}")


def check_daily_greetings():
    """Send once per local calendar day at 08:00 and 22:00 (Termux device timezone)."""
    now = datetime.now()
    state = load_json(SCHEDULE_FILE, {})
    today = now.strftime("%Y-%m-%d")
    if now.hour >= 8 and state.get("morning") != today:
        send_daily_greeting("morning")
        state["morning"] = today
        save_json(SCHEDULE_FILE, state)
    if now.hour >= 22 and state.get("night") != today:
        send_daily_greeting("night")
        state["night"] = today
        save_json(SCHEDULE_FILE, state)
    if state.get("birthdays") != today:
        birthday_key = now.strftime("%m-%d")
        celebrants = [v.get("name", "friend") for v in game_state.get("birthdays", {}).values() if v.get("date") == birthday_key]
        if celebrants:
            for destination in broadcast_destinations():
                send_message(destination, "🎂 Happy Birthday " + ", ".join(celebrants) + "! Wishing you a wonderful day! 🎉")
                time.sleep(0.04)
        state["birthdays"] = today
        save_json(SCHEDULE_FILE, state)


# =========================
# GROUP REPLY FILTER
# =========================

BOT_USERNAME = None

def should_reply_in_group(message, text):
    """Only answer when the message is directed at Vynex, not every group message."""
    if not text or not text.strip():
        return False

    chat = message.get("chat", {})
    if chat.get("type") not in ("group", "supergroup"):
        return True

    user = message.get("from", {})
    if user.get("is_bot"):
        return False

    lowered = text.lower().strip()
    if lowered.startswith("/"):
        # Commands are handled separately; ordinary commands should not trigger AI.
        return False

    # Explicit @mention of this bot.
    if BOT_USERNAME and re.search(r"(?i)(^|\s)@" + re.escape(BOT_USERNAME) + r"\b", text):
        return True

    # A direct reply to one of this bot's messages.
    replied = message.get("reply_to_message", {})
    replied_from = replied.get("from", {}) if isinstance(replied, dict) else {}
    if replied_from.get("is_bot") and BOT_USERNAME and replied_from.get("username", "").lower() == BOT_USERNAME.lower():
        return True

    # Natural direct address by name / common call-outs.
    direct_terms = ("vynex", "vynex ai", "hey ai", "ai sun", "bot sun", "bot bata",
                    "tum batao", "iska jawab", "help chahiye")
    if any(term in lowered for term in direct_terms):
        return True

    # Avoid jumping into unrelated chat. A question alone is not enough.
    return False


def is_flooding(chat_id, user_id):
    # Lightweight in-memory group flood protection: warn and ignore rapid repeats.
    try:
        info=game_state["flood"].setdefault(f"{chat_id}:{user_id}", [])
        now=time.time(); info=[t for t in info if now-t<8]
        info.append(now); game_state["flood"][f"{chat_id}:{user_id}"]=info
        if len(info)>=9:
            game_state["flood"][f"{chat_id}:{user_id}"]=[]
            return True
    except Exception:
        return False
    return False


# =========================
# UPDATE HANDLER
# =========================

def handle_message(message):
    global VOICE_ENABLED
    chat = message.get("chat", {})
    user = message.get("from", {})

    chat_id = chat.get("id")
    user_id = user.get("id")

    if not chat_id or not user_id:
        return

    # Ignore very rapid repeated group messages to reduce bot-triggered flood.
    if chat.get("type") in ("group", "supergroup") and is_flooding(chat_id, user_id):
        send_message(chat_id, f"⚠️ {user.get('first_name','User')}, thoda slow! Anti-flood protection active hai.")
        return

    remember_broadcast_chat(chat)
    register_user(user)

    # Group welcome message for new members
    for member in message.get("new_chat_members", []):
        if member.get("is_bot"):
            continue
        send_message(chat_id, f"👋 Welcome {member.get('first_name','friend')} to {chat.get('title','the group')}!\n🆔 User ID: {member.get('id')}\nPlease check the group rules and enjoy your stay 💜")

    text = message.get("text", "")

    # Reply-keyboard labels are mapped to the same handlers as commands.
    aliases = {
        "🎲 Ludo": "/ludo", "❌ Tic-Tac-Toe": "/ttt",
        "✊ Rock Paper Scissors": "/rps", "🔢 Number Guess": "/guess",
        "🧠 Quiz": "/quiz", "🔙 Main Menu": "/menu",
        "🏆 Leaderboard": "/leaderboard", "🎁 Daily Reward": "/daily",
        "👤 My Profile": "/profile",
    }
    text = aliases.get(text, text)

    # Games and rewards commands
    if (text.startswith(("/ludo", "/ttt", "/rps", "/guess", "/g ", "/quiz"))) and not settings.get("games", True):
        send_message(chat_id,"🎮 Games temporarily OFF hain."); return
    if text == "/games" or text == "🎮 Games":
        if not settings.get("games", True): send_message(chat_id,"🎮 Games temporarily OFF hain.")
        else: show_games(chat_id)
        return
    if text.startswith("/weather"):
        city=text.split(maxsplit=1)[1].strip() if len(text.split(maxsplit=1))>1 else ""
        if city: weather_lookup(chat_id,city)
        else: send_message(chat_id,"Use: /weather <city>")
        return
    if text.startswith("/birthday"): set_birthday(chat_id,user,text); return
    if text.startswith("/poll"): create_poll(chat_id,text); return
    if text.startswith("/remind"): set_reminder(chat_id,user,text); return
    if text.startswith("/rules"): show_rules(chat_id); return
    if text.startswith("/games") and not settings.get("games",True):
        send_message(chat_id,"🎮 Games temporarily OFF hain."); return
    if text.startswith("/ludo_join"): join_ludo(chat_id,user); return
    if text.startswith("/ludo_start"): ludo_start(chat_id,user); return
    if text.startswith("/ludo_roll"): ludo_roll(chat_id,user); return
    if text.startswith("/ludo_move"): ludo_move(chat_id,user,text); return
    if text.startswith("/ludo_skip"): ludo_skip(chat_id,user); return
    if text.startswith("/ludo"): start_ludo(chat_id,user); return
    if text.startswith("/ttt_join"): join_ttt(chat_id,user); return
    if text.startswith("/ttt"): start_ttt(chat_id,user); return
    if text.startswith("/rps"): play_rps(chat_id,user,text); return
    if text.startswith("/guess"): start_guess(chat_id,user); return
    if text.startswith("/g "): guess_number(chat_id,user,text); return
    if text.startswith("/quiz"): play_quiz(chat_id,user); return
    if text.startswith("/daily") or text == "🎁 Daily Reward": daily_reward(chat_id,user); return
    if text.startswith("/profile") or text == "👤 My Profile": show_profile(chat_id,user); return
    if text.startswith("/leaderboard"): show_leaderboard(chat_id); return
    if text == "🔎 Web Search": send_message(chat_id,"🔎 Use /search <your query>"); return

    if text == "/start":
        start_command(chat_id, user)
        return

    if text == "/help" or text == "ℹ️ Help":
        help_command(chat_id, user_id)
        return

    if text.startswith("/search") or text.startswith("/search@"):
        query = text.split(maxsplit=1)[1].strip() if len(text.split(maxsplit=1)) > 1 else ""
        if not query:
            send_message(chat_id, "🔎 Use: /search <aapka search query>")
            return
        send_typing(chat_id)
        results = web_search(query, limit=5)
        if not results:
            send_message(chat_id, "❌ Abhi web search results nahi mil paaye. Thodi der baad try karo.")
            return
        out = [f"🔎 Search results for: {query}"]
        for i, item in enumerate(results, 1):
            out.append(f"\n{i}. {item.get('title', 'Result')}\n{item.get('snippet', '')}\n{item.get('url', '')}")
        send_message(chat_id, "\n".join(out)[:3900])
        return

    if text.startswith("/ask") or text.startswith("/ask@"):
        question = text.split(maxsplit=1)[1].strip() if len(text.split(maxsplit=1)) > 1 else ""
        if not question:
            send_message(chat_id, "💬 Use: /ask <apna question>")
            return
        if not require_channel(chat_id, user_id):
            return
        send_typing(chat_id)
        answer = ask_groq(question, chat_id=chat_id, force_search=needs_web_search(question))
        send_ai_reply(chat_id, answer)
        return

    if text == "/menu" or text == "🔙 Main Menu":
        show_menu(chat_id, user_id)
        return

    if text == "/dice" or text.lower().strip() in ("dice", "ludo", "ludo dice", "🎲"):
        send_ludo_dice(chat_id)
        return

    if text == "💬 Chat with Vynex":
        send_message(chat_id, "Haan bolo 😊 Kya baat hai?")
        return

    if text == "🕒 Time":
        send_message(chat_id, f"🕐 {datetime.now().strftime('%d-%m-%Y %H:%M:%S')}")
        return

    if text == "👑 Owner Panel" or text == "/ownerpanel":
        owner_panel(chat_id, user_id)
        return

    if text == "/claimowner":
        if is_owner(user_id):
            set_owner(user_id)
            send_message(chat_id, "👑 Owner ID verified and saved.")
        else:
            send_message(chat_id, "❌ Owner ID fixed hai; aap ye command use nahi kar sakte.")
        return

    if text == "/owner":
        if is_owner(user_id):
            send_message(chat_id, "👑 Aap bot ke owner ho.")
        return

    if text == "/ping":
        send_message(chat_id, "🏓 Pong! Vynex is online.")
        return

    if text == "/id":
        send_message(chat_id, f"🆔 Your Telegram ID: `{user_id}`")
        return

    if text == "/time":
        send_message(
            chat_id,
            f"🕐 {datetime.now().strftime('%d-%m-%Y %H:%M:%S')}"
        )
        return


    if text == "/stats":
        stats_command(chat_id, user_id)
        return

    if text == "/logs":
        logs_command(chat_id, user_id)
        return

    if text == "/chat_on":
        if not owner_only(chat_id, user_id):
            return

        settings["chat"] = True
        save_json(SETTINGS_FILE, settings)

        send_message(chat_id, "🤖 AI chat ON.")
        return

    if text == "/chat_off":
        if not owner_only(chat_id, user_id):
            return

        settings["chat"] = False
        save_json(SETTINGS_FILE, settings)

        send_message(chat_id, "🤖 AI chat OFF.")
        return

    if text == "/maintenance_on":
        if not owner_only(chat_id, user_id):
            return

        settings["maintenance"] = True
        save_json(SETTINGS_FILE, settings)

        send_message(chat_id, "🔴 Maintenance mode ON.")
        return

    if text == "/maintenance_off":
        if not owner_only(chat_id, user_id):
            return

        settings["maintenance"] = False
        save_json(SETTINGS_FILE, settings)

        send_message(chat_id, "🟢 Maintenance mode OFF.")
        return

    if text == "/verify_on":
        if not owner_only(chat_id, user_id):
            return

        settings["verification"] = True
        save_json(SETTINGS_FILE, settings)
        send_message(
            chat_id,
            "🔐 Global verification ON.\n\n"
            "Ab Vynex ke har group mein Channel + VynexAITalk "
            "verification maangi jayegi."
        )
        return

    if text == "/verify_off":
        if not owner_only(chat_id, user_id):
            return

        settings["verification"] = False
        save_json(SETTINGS_FILE, settings)
        send_message(
            chat_id,
            "🔓 Global verification OFF.\n\n"
            "Ab Vynex kisi group mein verification nahi mangega."
        )
        return

    if text == "/verify_status":
        if not owner_only(chat_id, user_id):
            return

        status = "ON" if settings.get("verification", False) else "OFF"
        send_message(
            chat_id,
            f"🔐 Global verification: {status}\n\n"
            f"📢 Channel: {REQUIRED_CHANNEL}\n"
            f"👥 Group: {VYNEX_TALK_GROUP}"
        )
        return

    if text == "/voice_on":
        if not owner_only(chat_id, user_id):
            return
        VOICE_ENABLED = True
        send_message(
            chat_id,
            "🎙️ Voice replies ON.\n\nAb Vynex AI replies voice message mein bhi aayenge."
        )
        return

    if text == "/voice_off":
        if not owner_only(chat_id, user_id):
            return
        VOICE_ENABLED = False
        send_message(chat_id, "🔇 Voice replies OFF.\n\nAb normal text replies aayenge.")
        return

    if text == "/voice_status":
        if not owner_only(chat_id, user_id):
            return
        status = "ON 🎙️" if VOICE_ENABLED else "OFF 🔇"
        send_message(chat_id, f"🎙️ Voice replies: {status}")
        return

    if text.startswith("/broadcast") or text.startswith("/broadcast@"):
        if not owner_only(chat_id, user_id):
            return
        # /broadcast with text sends text; replying to any message copies that exact message/media.
        command_parts = text.split(maxsplit=1)
        broadcast_text = command_parts[1].strip() if len(command_parts) > 1 else ""
        replied_message = message.get("reply_to_message") if not broadcast_text else None
        broadcast_command(chat_id, user_id, broadcast_text, replied_message)
        return

    # =========================
    # CHANNEL CHECK FOR AI
    # =========================

    if not require_channel(chat_id, user_id):
        return

    # =========================
    # MAINTENANCE
    # =========================

    if settings.get("maintenance", False) and not is_owner(user_id):
        send_message(
            chat_id,
            "🔴 Vynex abhi maintenance mode mein hai."
        )
        return

    # =========================
    # AI CHAT
    # =========================

    if not settings.get("chat", True):
        send_message(
            chat_id,
            "🤖 AI chat currently OFF hai."
        )
        return

    if not text:
        return

    if not should_reply_in_group(message, text):
        return

    users[str(user_id)]["messages"] = (
        users[str(user_id)].get("messages", 0) + 1
    )

    save_json(USERS_FILE, users)

    log(
        f"AI message | user={user_id} | "
        f"text={text[:100]}"
    )

    message_id = message.get("message_id")
    if message_id:
        react_to_message(chat_id, message_id, text)

    send_typing(chat_id)
    answer = ask_groq(text, chat_id=chat_id, force_search=needs_web_search(text))

    send_ai_reply(chat_id, answer)


def set_owner_setting(chat_id, key, value, message):
    settings[key] = value
    save_json(SETTINGS_FILE, settings)
    send_message(chat_id, message)


def set_voice_setting(chat_id, enabled):
    global VOICE_ENABLED
    VOICE_ENABLED = enabled
    send_message(chat_id, "🎙️ Voice replies ON." if enabled else "🔇 Voice replies OFF.")


# =========================
# CALLBACK HANDLER
# =========================

def handle_callback(callback):
    callback_id = callback.get("id")
    data = callback.get("data")
    user = callback.get("from", {})
    user_id = user.get("id")

    message = callback.get("message", {})
    chat = message.get("chat", {})
    chat_id = chat.get("id")

    # Game buttons use the chat where the room was created, so all players
    # in the same group share the same room state.
    if data == "ludo_join":
        join_ludo(chat_id, user); answer_callback(callback_id, "Ludo join request processed"); return
    if data == "ludo_start":
        ludo_start(chat_id, user); answer_callback(callback_id, "Start request processed"); return
    if data == "ludo_roll":
        ludo_roll(chat_id, user); answer_callback(callback_id, "Dice rolled"); return
    if data == "ludo_skip":
        ludo_skip(chat_id, user); answer_callback(callback_id, "Turn passed"); return
    if isinstance(data, str) and data.startswith("ludo_move_"):
        ludo_move(chat_id, user, "/ludo_move " + data.rsplit("_", 1)[1]); answer_callback(callback_id, "Move processed"); return
    if data == "ttt_join":
        join_ttt(chat_id, user); answer_callback(callback_id, "Join request processed"); return
    if isinstance(data, str) and data.startswith("rps_"):
        play_rps(chat_id, user, "/rps " + data.split("_", 1)[1]); answer_callback(callback_id, "Move selected"); return

    if isinstance(data, str) and data.startswith("ttt_"):
        try: ttt_move(callback, chat_id, user_id, int(data.split("_",1)[1]))
        except Exception: answer_callback(callback,"Move failed")
        return
    if isinstance(data, str) and data.startswith("quiz_"):
        room=game_state["quiz"].get(str(chat_id))
        if not room:
            answer_callback(callback,"Quiz expired"); return
        choice=int(data.split("_",1)[1]);
        if choice==room["answer"]:
            prof=profile_for(user_id,user.get("first_name","Player")); prof["coins"]+=5; prof["wins"]+=1
            answer_callback(callback,"Correct! +5 coins")
            send_message(chat_id,"✅ Correct answer! +5 virtual coins.")
        else:
            answer_callback(callback,"Not quite—try the next quiz!")
            send_message(chat_id,"❌ Not quite! Use /quiz for another question.")
        game_state["quiz"].pop(str(chat_id),None); save_games(); return

    owner_actions = {
        "owner_stats": lambda: stats_command(chat_id, user_id),
        "owner_logs": lambda: logs_command(chat_id, user_id),
        "owner_games_on": lambda: set_owner_setting(chat_id, "games", True, "🎮 Games ON."),
        "owner_games_off": lambda: set_owner_setting(chat_id, "games", False, "🎮 Games OFF."),
        "owner_chat_on": lambda: set_owner_setting(chat_id, "chat", True, "🤖 AI chat ON."),
        "owner_chat_off": lambda: set_owner_setting(chat_id, "chat", False, "🤖 AI chat OFF."),
        "owner_maintenance_on": lambda: set_owner_setting(chat_id, "maintenance", True, "🔴 Maintenance mode ON."),
        "owner_maintenance_off": lambda: set_owner_setting(chat_id, "maintenance", False, "🟢 Maintenance mode OFF."),
        "owner_verify_on": lambda: set_owner_setting(chat_id, "verification", True, "🔐 Verification ON."),
        "owner_verify_off": lambda: set_owner_setting(chat_id, "verification", False, "🔓 Verification OFF."),
        "owner_voice_on": lambda: set_voice_setting(chat_id, True),
        "owner_voice_off": lambda: set_voice_setting(chat_id, False),
    }
    if data in owner_actions:
        if not is_owner(user_id):
            answer_callback(callback_id, "")
            return
        answer_callback(callback_id, "Done")
        owner_actions[data]()
        return

    if data == "check_joined":
        if not settings.get("verification", False):
            mark_verified(user_id)
            answer_callback(callback_id, "🟢 Verification OFF hai.")
            send_message(
                chat_id,
                "🟢 Verification abhi OFF hai.\n\n"
                "Ab Vynex use kar sakte ho."
            )
            return

        channel_ok = is_channel_member(user_id)
        group_ok = is_vynex_group_member(user_id)

        if channel_ok and group_ok:
            mark_verified(user_id)
            answer_callback(
                callback_id,
                "✅ Channel + group verified!"
            )
            send_message(
                chat_id,
                "✅ Verification successful!\n\n"
                "Ab Vynex use kar sakte ho. 💜"
            )
        else:
            missing = []
            if not channel_ok:
                missing.append("📢 Channel")
            if not group_ok:
                missing.append("👥 VynexAITalk group")

            answer_callback(
                callback_id,
                "❌ Required joins complete karo."
            )
            send_message(
                chat_id,
                "❌ Verification complete nahi hua.\n\n"
                "Abhi ye join karna baaki hai:\n"
                + "\n".join(missing)
                + "\n\nJoin karke dobara '✅ Check Joined' dabao.",
                verification_keyboard()
            )


# =========================
# MAIN LOOP
# =========================

def main():
    global BOT_USERNAME
    # Publish the slash commands in Telegram's command menu so users can discover games.
    command_list = [
        {"command":"start", "description":"Open main menu"},
        {"command":"help", "description":"Help and all features"},
        {"command":"games", "description":"Open games menu"},
        {"command":"ludo", "description":"Create/join multiplayer Ludo"},
        {"command":"ludo_join", "description":"Join Ludo room"},
        {"command":"ludo_start", "description":"Start Ludo match"},
        {"command":"ludo_roll", "description":"Roll Ludo dice"},
        {"command":"ludo_move", "description":"Move a Ludo token"},
        {"command":"ttt", "description":"Start Tic-Tac-Toe"},
        {"command":"ttt_join", "description":"Join Tic-Tac-Toe"},
        {"command":"rps", "description":"Play Rock Paper Scissors"},
        {"command":"guess", "description":"Start number guessing"},
        {"command":"quiz", "description":"Play a quiz"},
        {"command":"daily", "description":"Claim daily reward"},
        {"command":"profile", "description":"Show your profile"},
        {"command":"leaderboard", "description":"Show leaderboard"},
        {"command":"ask", "description":"Ask Vynex AI"},
        {"command":"search", "description":"Search the web"},
        {"command":"weather", "description":"Check city weather"},
        {"command":"remind", "description":"Set a reminder"},
    ]
    try:
        cmd_result = telegram("setMyCommands", {"commands": command_list})
        if not cmd_result.get("ok"):
            log(f"Could not update Telegram command menu: {cmd_result}")
    except Exception as exc:
        log(f"Could not update Telegram command menu: {exc}")
    me = telegram("getMe")
    if me.get("ok"):
        BOT_USERNAME = me.get("result", {}).get("username")
    log(f"🤖 Bot username: @{BOT_USERNAME}" if BOT_USERNAME else "🤖 Bot username lookup failed")
    log("🚀 Vynex AI starting...")
    log(f"📢 Required channel: {REQUIRED_CHANNEL}")
    log(f"👥 VynexAITalk group: {VYNEX_TALK_GROUP}")
    log(f"🔐 Global verification: {settings.get('verification', False)}")
    log(f"🤖 Groq model: {GROQ_MODEL}")
    log("🔎 Web search: DuckDuckGo HTML (6s timeout; automatic for current-info queries; /search available)")
    log(f"❤️ Smart reactions: {REACTIONS_ENABLED}")
    log(f"🎙️ Voice replies: {VOICE_ENABLED}")

    offset = None

    while True:

        try:
            check_daily_greetings()
            check_reminders()
            params = {
                "timeout": 30
            }

            if offset is not None:
                params["offset"] = offset

            response = requests.get(
                f"{TELEGRAM_API}/getUpdates",
                params=params,
                timeout=40
            )

            data = response.json()

            if not data.get("ok"):
                log(f"getUpdates error: {data}")
                time.sleep(0.2)
                continue

            for update in data.get("result", []):

                offset = update["update_id"] + 1

                if "message" in update:
                    handle_message(update["message"])

                elif "callback_query" in update:
                    handle_callback(update["callback_query"])

        except KeyboardInterrupt:
            log("🛑 Vynex stopped.")
            break

        except Exception as e:
            log(f"Main loop error: {e}")
            time.sleep(0.2)


if __name__ == "__main__":
    main()
