#!/usr/bin/env python3
"""PULKIT Giveaway Bot — single source file.
Install: python3 -m pip install -U python-telegram-bot tzdata
Configure: export BOT_TOKEN='your-token-from-BotFather'
Run: python3 vote.py (keep running on your VPS with a service manager).
/admin or /owner -> Advanced Features -> Giveaways / Prizes -> select giveaway.
1. Set auto-end in IST: YYYY-MM-DD HH:MM.
2. Set rules: MIN_VOTES WINNER_COUNT random|id (defaults: 1 1 id).
3. Set public prize label, then Save Prize -> rank -> private text/code/link/file.
   Winners get a Claim Prize button; unclaimed slots advance through backups
   after the claim period. Bot delivers saved content, not cash or new VPS setups.
   Never put private credentials in public labels.
4. Delivery Status shows sent, missing, failed or uncertain; owner can retry.
   Winner must have started and not blocked the bot. Bot needs channel posting
   permission. Restart recovers deadlines/jobs without redrawing winners.
Main owner can assign manager, broadcast or read-only viewer roles by Telegram ID.
Daily Backup is opt-in. Emergency Pause freezes joins/votes and auto-end;
resume processes overdue giveaways. Schedules use IST and persist progress.
Local bot_data.json contains private prize content: protect file/backups.
Run only one bot process per bot_data.json. Telegram sends cannot be exactly-once:
uncertain sends require review before retry. Previously ended legacy giveaways
are not redrawn. /cancel exits editor flows.
New giveaways publish a SHA-256 seed commitment and reveal the seed after the
draw; random ties use that seed. Optional quiz entry is set per giveaway as
QUESTION | ANSWER. The channel progress post updates on joins and votes.
/profile shows vote and daily-streak badges; badges never add votes. Set a
winner photo/video/GIF in Advanced -> Welcome Editor -> Winner Animation.
"""
from html import escape
import csv
import io
import secrets
import hashlib
import hmac
from zoneinfo import ZoneInfo
import logging
import random
import string
import json
import re
import time
from collections import defaultdict, deque
import os
import asyncio
from datetime import datetime, timezone
from telegram import (
    Bot,
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReactionTypeEmoji,
    ForceReply
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes
)
from telegram.request import HTTPXRequest

# ================= CONFIG ================= #
TOKEN = os.getenv("TOKEN", "")

BOT_USERNAME = "@pulkitvoting_bot"
OWNER_ID = 8925611507

# ================= PREMIUM EMOJIS ================= #
EMOJI_VOTE = "5877485980901971030"
EMOJI_JOIN = "5337080053119336309"
EMOJI_CANCEL = "5978586079370939741"
EMOJI_MAIN_MENU = "5416041192905265756"
EMOJI_BACK = "5875082500023258804"
EMOJI_CREATE = "5877219383691972108"
EMOJI_CONNECT = "5877465816030515018"
EMOJI_MANAGE = "5341715473882955310"
EMOJI_ADD_VOTES = "5877219383691972108"
EMOJI_REMOVE_VOTES = "5879896690210639947"
EMOJI_LEADERBOARD = "5440539497383087970"
EMOJI_END_GIVEAWAY = "5978841844673416652"
EMOJI_ADMIN = "5217822164362739968"
EMOJI_BROADCAST = "5424818078833715060"
EMOJI_STATS = "5877485980901971030"
EMOJI_SETTINGS = "5341715473882955310"
EMOJI_USERS = "5116582462276764538"
EMOJI_BACKUP = "6017174676898321263"
EMOJI_CLEAR = "5879896690210639947"
EMOJI_CHANNEL = "5877465816030515018"
EMOJI_NOTIFICATION = "5458603043203327669"
EMOJI_CONFIRM = "5978820206628178949"
EMOJI_REFRESH = "6005843436479975944"
EMOJI_WELCOME = "5979030024370522700"
EMOJI_FIRE = "5224607267797606837"
EMOJI_ARROW = "5978759780733291780"
EMOJI_CHART = "5244837092042750681"
EMOJI_HEART = "6129913724422593277"
EMOJI_ROCKET = "6129639980387015660"
EMOJI_CROWN = "5217822164362739968"
EMOJI_ERROR = "5978586079370939741"
EMOJI_ENDED = "5978586079370939741"
EMOJI_STAR = "5978812475687046594"
EMOJI_ID = "5116468787377341336"
EMOJI_GIFT = "6032937473162614352"
EMOJI_WINE = "5134186747244053395"
EMOJI_SMILE = "6132198982031513203"
EMOJI_LOVE = "6129913724422593277"
EMOJI_LIGHTNING = "6129695952400820630"
EMOJI_POINTER = "5875082500023258804"
EMOJI_ALERT = "5447644880824181073"
EMOJI_CLOWN = "5978820206628178949"
EMOJI_SEARCH = "5231012545799666522"
EMOJI_SPEAKER = "5424818078833715060"
EMOJI_LINK = "5877465816030515018"
EMOJI_CONFETTI = "5461151367559141950"
EMOJI_LOCATION = "5978563874390022484"
EMOJI_RIGHT = "5978759780733291780"
EMOJI_DIAMOND = "5978643163781271317"
EMOJI_CALENDAR = "5413879192267805083"
EMOJI_WINNER = "6156436440260549720"
EMOJI_MONEY_BAG = "5978857525599014469"
EMOJI_CELEBRATE = "5461151367559141950"
EMOJI_INBOX = "5877307202888273539"
EMOJI_LOCK = "5296369303661067030"
EMOJI_SHIELD = "5251203410396458957"
EMOJI_PURPLE_HEART = "5084974483685507801"
EMOJI_VIDEO = "5118744200921219799"
EMOJI_GOLD_STAR = "6129455898088709012"

# Custom emoji IDs above were matched to their fallback glyphs in the supplied ids.txt file.

# ================= COLOR STYLES ================= #
BUTTON_STYLE_PRIMARY = "primary"
BUTTON_STYLE_SUCCESS = "success"
BUTTON_STYLE_DANGER = "danger"

# ================= LOGGING ================= #
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ================= JSON DATABASE ================= #
# Keep persistent state beside this script so service/screen/nohup restarts from
# a different shell directory still load the same giveaway database.
DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot_data.json")
owner_settings = {}
security_alerts = []

def load_data():
    global giveaways, all_users, channel_history
    try:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                giveaways = data.get("giveaways", {})
                all_users = data.get("all_users", {})
                channel_history = data.get("channel_history", {})
                owner_settings.update(data.get("owner_settings", {}))
                security_alerts.extend(data.get("security_alerts", [])[-100:])
                # Restore runtime-only sets and integer user IDs after JSON load.
                for _gid, _g in giveaways.items():
                    _g["users"] = {int(k): v for k, v in _g.get("users", {}).items()}
                    _g["vote_counts"] = {int(k): int(v) for k, v in _g.get("vote_counts", {}).items()}
                    _g["voted_users"] = {int(k): set(v) for k, v in _g.get("voted_users", {}).items()}
                logger.info(f"Loaded: {len(giveaways)} giveaways, {len(all_users)} users")
        else:
            giveaways = {}
            all_users = {}
            channel_history = {}
    except Exception as e:
        logger.error(f"Error loading: {e}")
        giveaways = {}
        all_users = {}
        channel_history = {}

def save_data():
    try:
        data = {
            "giveaways": giveaways,
            "all_users": all_users,
            "channel_history": channel_history,
            "owner_settings": owner_settings,
            "security_alerts": security_alerts,
            "last_saved": datetime.now().isoformat()
        }
        def json_safe(obj):
            if isinstance(obj, set):
                return list(obj)
            if isinstance(obj, dict):
                return {str(k): json_safe(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [json_safe(v) for v in obj]
            return obj
        with open(DATA_FILE + ".tmp", 'w', encoding='utf-8') as f:
            json.dump(json_safe(data), f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(DATA_FILE + ".tmp", DATA_FILE)
    except Exception as e:
        logger.error(f"Error saving: {e}")
        raise

def save_user(user_id, username, first_name, last_name=None, source=None):
    if str(user_id) not in all_users:
        all_users[str(user_id)] = {
            "user_id": user_id,
            "username": username,
            "first_name": first_name,
            "last_name": last_name,
            "joined_at": datetime.now().isoformat(),
            "last_active": datetime.now().isoformat(),
            "source": source or "unknown",
            "total_votes_given": 0,
            "total_giveaways_joined": 0
        }
        save_data()
    else:
        all_users[str(user_id)]["last_active"] = datetime.now().isoformat()
        if username:
            all_users[str(user_id)]["username"] = username
        save_data()
    return True

def update_user_stats(user_id, action):
    user_id_str = str(user_id)
    if user_id_str in all_users:
        if action == "vote":
            all_users[user_id_str]["total_votes_given"] = all_users[user_id_str].get("total_votes_given", 0) + 1
        elif action == "join":
            all_users[user_id_str]["total_giveaways_joined"] = all_users[user_id_str].get("total_giveaways_joined", 0) + 1
        save_data()


def record_vote_badges(user_id):
    profile = all_users.setdefault(str(user_id), {"user_id": user_id})
    today = datetime.now(IST).date()
    previous = profile.get("last_vote_day")
    yesterday = (today - __import__("datetime").timedelta(days=1)).isoformat()
    if previous != today.isoformat():
        profile["vote_streak"] = profile.get("vote_streak", 0) + 1 if previous == yesterday else 1
        profile["last_vote_day"] = today.isoformat()
    total = profile.get("total_votes_given", 0)
    streak = profile.get("vote_streak", 0)
    earned = profile.setdefault("badges", [])
    new_badges = []
    for threshold, badge in ((1,"First Vote"),(10,"Vote Starter"),(50,"Vote Pro"),(100,"Vote Legend")):
        if total >= threshold and badge not in earned: earned.append(badge); new_badges.append(badge)
    for threshold, badge in ((3,"3 Day Streak"),(7,"7 Day Streak"),(30,"30 Day Streak")):
        if streak >= threshold and badge not in earned: earned.append(badge); new_badges.append(badge)
    save_data()
    return new_badges

def update_channel_history(channel_identifier, channel_display, channel_id, user_id, user_name, action, giveaway_id=None):
    channel_key = str(channel_identifier)
    
    if channel_key not in channel_history:
        channel_history[channel_key] = {
            "channel_identifier": channel_identifier,
            "channel_display": channel_display,
            "channel_id": channel_id,
            "type": "private" if str(channel_id).startswith('-100') or str(channel_id).startswith('-') else "public",
            "total_giveaways": 0,
            "giveaways": [],
            "created_by": user_id,
            "created_by_name": user_name,
            "first_created": datetime.now().isoformat()
        }
    
    if action == "create":
        channel_history[channel_key]["total_giveaways"] += 1
        channel_history[channel_key]["giveaways"].append({
            "giveaway_id": giveaway_id,
            "created_at": datetime.now().isoformat(),
            "status": "active",
            "participants": 0
        })
        channel_history[channel_key]["last_giveaway"] = datetime.now().isoformat()
    elif action == "end" and giveaway_id:
        for g in channel_history[channel_key]["giveaways"]:
            if g.get("giveaway_id") == giveaway_id:
                g["status"] = "ended"
                g["ended_at"] = datetime.now().isoformat()
                break
    
    save_data()

# ================= INITIALIZE ================= #
giveaways = {}
all_users = {}
user_sessions = {}
admin_sessions = {}
channel_history = {}
vote_messages = {}

# ================= SECURITY / ANTI-ABUSE ================= #
SECURITY_ENABLED = True
AUTO_BAN_ON_ABUSE = True
PROFILE_ABUSE_CHECK_ENABLED = True
AUTO_BAN_ON_PROFILE_ABUSE = True

# Vote anti-abuse thresholds.
VOTE_WINDOW_SECONDS = 30
MAX_VOTES_IN_WINDOW = 8
MAX_TARGETS_IN_WINDOW = 6
SUSPICIOUS_SCORE_LIMIT = 3

# Common abusive/profane terms. Matching is normalized and supports simple obfuscation.
ABUSE_WORDS = {
    "fuck", "fucking", "fucker", "motherfucker", "shit", "bitch", "bastard",
    "asshole", "dick", "piss", "cunt", "whore", "slut", "idiot", "stupid",
    "gaand", "gand", "chutiya", "chutiye", "madarchod", "madharchod",
    "bhosdike", "bhosdi", "bc", "mc", "behenchod", "bhenchod", "randi",
    "harami", "kamina", "kamine", "kutte", "kutta"
}

# Terms indicating explicit/adult content.
ADULT_WORDS = {
    "porn", "porno", "pornography", "xxx", "nsfw", "nudes", "nude",
    "sexcam", "sexvideo", "onlyfans"
}

banned_users = set()
suspicious_scores = defaultdict(int)
vote_activity = defaultdict(deque)


def normalize_security_text(text):
    text = (text or "").lower()
    replacements = {
        "@": "a", "4": "a", "3": "e", "1": "i", "!": "i",
        "0": "o", "$": "s", "5": "s"
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def contains_banned_content(text):
    normalized = normalize_security_text(text)
    words = set(normalized.split())
    compact = normalized.replace(" ", "")

    if words & ABUSE_WORDS:
        return True, "abusive/profane language"
    if words & ADULT_WORDS:
        return True, "18+ / adult content"

    # Catch simple letter/symbol/space obfuscation for longer terms.
    for term in (ABUSE_WORDS | ADULT_WORDS):
        if len(term) >= 5 and term in compact:
            return True, "abusive/profane or prohibited content"

    return False, ""


def check_profile_for_abuse(user):
    """Check username and display-name fields before allowing bot access."""
    if not PROFILE_ABUSE_CHECK_ENABLED or not user:
        return False, ""

    profile_fields = (
        ("username", user.username or ""),
        ("first name", user.first_name or ""),
        ("last name", user.last_name or ""),
    )

    for field_name, value in profile_fields:
        if value:
            found, _reason = contains_banned_content(value)
            if found:
                return True, f"{field_name} contains a banned word"

    return False, ""


def is_security_banned(user_id):
    return int(user_id) in banned_users


def security_ban_user(user_id, reason):
    uid = int(user_id)
    if uid == OWNER_ID:
        return
    security_alerts.append({"user_id": uid, "reason": reason, "time": datetime.now().isoformat()})
    del security_alerts[:-100]
    banned_users.add(uid)
    all_users.setdefault(str(uid), {})
    all_users[str(uid)]["security_banned"] = True
    all_users[str(uid)]["security_ban_reason"] = reason
    all_users[str(uid)]["security_banned_at"] = datetime.now().isoformat()
    save_data()


def register_vote_activity(voter_id, target_id):
    now = time.monotonic()
    q = vote_activity[int(voter_id)]
    q.append((now, int(target_id)))
    while q and now - q[0][0] > VOTE_WINDOW_SECONDS:
        q.popleft()
    votes = len(q)
    targets = len({target for _, target in q})
    suspicious = votes > MAX_VOTES_IN_WINDOW or targets > MAX_TARGETS_IN_WINDOW
    return suspicious, votes, targets


def load_security_state():
    for uid, data in all_users.items():
        if data.get("security_banned"):
            banned_users.add(int(uid))

load_data()
load_security_state()
suspicious_scores.update({int(uid): score for uid, score in owner_settings.get("suspicious_scores", {}).items()})
SECURITY_ENABLED = owner_settings.get("security", True)
AUTO_BAN_ON_ABUSE = owner_settings.get("autoban", True)
AUTO_BAN_ON_PROFILE_ABUSE = AUTO_BAN_ON_ABUSE

request = HTTPXRequest(connect_timeout=30, read_timeout=30, write_timeout=30, pool_timeout=30)

SMALL_CAPS_MAP = str.maketrans({
    **{letter: glyph for letter, glyph in zip(
        "abcdefghijklmnopqrstuvwxyz",
        "ᴀʙᴄᴅᴇꜰɢʜɪᴊᴋʟᴍɴᴏᴘǫʀꜱᴛᴜᴠᴡxʏᴢ",
    )},
    **{letter: glyph for letter, glyph in zip(
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ",
        "ᴀʙᴄᴅᴇꜰɢʜɪᴊᴋʟᴍɴᴏᴘǫʀꜱᴛᴜᴠᴡxʏᴢ",
    )},
})
SMALL_CAPS_PROTECTED = re.compile(
    r"(<(?:code|pre|a|blockquote)\b[^>]*>.*?</(?:code|pre|a|blockquote)\s*>"
    r"|<[^>]+>|&(?:amp|lt|gt|quot);|https?://[^\s<]+|tg://[^\s<]+|www\.[^\s<]+"
    r"|@[A-Za-z0-9_]+|/(?:[A-Za-z][A-Za-z0-9_]*)(?:@[A-Za-z0-9_]+)?)",
    re.IGNORECASE | re.DOTALL,
)

def small_caps_text(value):
    """Style bot UI text while preserving markup, links, commands, and quoted user copy."""
    if not isinstance(value, str) or not value:
        return value
    output=[]
    last=0
    for match in SMALL_CAPS_PROTECTED.finditer(value):
        output.append(value[last:match.start()].translate(SMALL_CAPS_MAP))
        output.append(match.group(0))
        last=match.end()
    output.append(value[last:].translate(SMALL_CAPS_MAP))
    return "".join(output)

def blue_quote_text(value, parse_mode=None):
    """Use Telegram's blockquote presentation, which renders the blue quote rail."""
    if not isinstance(value,str) or not value:
        return value,parse_mode
    if re.search(r"<blockquote\b",value,re.IGNORECASE):
        return value,parse_mode or "HTML"
    mode=str(parse_mode or "").upper()
    if mode and "HTML" not in mode:
        return value,parse_mode
    content=value if mode else escape(value,quote=False)
    return "<blockquote>"+content+"</blockquote>","HTML"

def install_small_caps_bot_text():
    """Apply small caps and the blue quote style at Telegram send/edit boundaries."""
    method_fields={
        "send_message":("text",1),
        "edit_message_text":("text",0),
        "answer_callback_query":("text",1),
        "send_video":("caption",None),
        "send_photo":("caption",None),
        "send_animation":("caption",None),
        "send_document":("caption",None),
    }
    for method_name,(field,positional_index) in method_fields.items():
        original=getattr(Bot,method_name)
        async def wrapped(self,*args,_original=original,_field=field,_position=positional_index,_method=method_name,**kwargs):
            preserve=kwargs.pop("_preserve_smallcaps",False)
            if _field in kwargs and isinstance(kwargs[_field],str):
                value=kwargs[_field]
                if not preserve:value=small_caps_text(value)
                if _method!="answer_callback_query":
                    value,parse_mode=blue_quote_text(value,kwargs.get("parse_mode"))
                    kwargs["parse_mode"]=parse_mode
                kwargs[_field]=value
            elif _position is not None and len(args)>_position and isinstance(args[_position],str):
                changed=list(args)
                value=changed[_position]
                if not preserve:value=small_caps_text(value)
                if _method!="answer_callback_query":
                    value,parse_mode=blue_quote_text(value,kwargs.get("parse_mode"))
                    kwargs["parse_mode"]=parse_mode
                changed[_position]=value
                args=tuple(changed)
            return await _original(self,*args,**kwargs)
        setattr(Bot,method_name,wrapped)

install_small_caps_bot_text()

def premium_button(text, callback_data=None, url=None, emoji_id=None, style=None):
    label = (text or "").upper()
    if emoji_id is None:
        icon_rules = (
            (("CANCEL", "BACK", "PREVIOUS", "HOME"), EMOJI_BACK),
            (("DELETE", "CLEAR", "REMOVE", "END", "BAN", "REVOKE"), EMOJI_CLEAR),
            (("CLAIM", "CONFIRM", "SAVE", "ENABLE", "JOIN"), EMOJI_CONFIRM),
            (("VIDEO", "MEDIA", "PHOTO"), EMOJI_VIDEO),
            (("CREATE", "ADD", "NEW"), EMOJI_CREATE),
            (("GIVEAWAY", "PRIZE", "GIFT"), EMOJI_GIFT),
            (("VOTE",), EMOJI_VOTE),
            (("USER", "MEMBER", "OWNER"), EMOJI_USERS),
            (("STAT", "ANALYTIC", "REPORT"), EMOJI_STATS),
            (("SCHEDULE", "DATE", "DEADLINE"), EMOJI_CALENDAR),
            (("CONNECT", "CHANNEL", "LINK"), EMOJI_CONNECT),
            (("MANAGE", "PANEL", "SETTING", "EDITOR"), EMOJI_SETTINGS),
        )
        emoji_id = next((icon for keys, icon in icon_rules if any(key in label for key in keys)), EMOJI_GOLD_STAR)
    if style is None:
        if any(word in label for word in ("CANCEL", "DELETE", "CLEAR", "REMOVE", "END", "BAN", "REVOKE")):
            style = BUTTON_STYLE_DANGER
        elif any(word in label for word in ("JOIN", "CONNECT", "CREATE", "SAVE", "CONFIRM", "CLAIM", "START", "ENABLE")):
            style = BUTTON_STYLE_SUCCESS
        else:
            style = BUTTON_STYLE_PRIMARY
    kwargs = dict(text=small_caps_text(text))
    kwargs.update(url=url) if url else kwargs.update(callback_data=callback_data)
    try:
        return InlineKeyboardButton(**kwargs, icon_custom_emoji_id=emoji_id, style=style)
    except TypeError:
        return InlineKeyboardButton(**kwargs)

def is_owner(user_id):
    return user_id == OWNER_ID

async def send_notification_to_owner(context, title, message):
    try:
        await context.bot.send_message(
            chat_id=OWNER_ID,
            text=f"<tg-emoji emoji-id='{EMOJI_NOTIFICATION}'>🔔</tg-emoji> <b>{small_caps_text(title)}</b>\n\n{message}",
            parse_mode="HTML",
            _preserve_smallcaps=True,
        )
    except Exception as e:
        logger.error(f"Failed to send: {e}")

async def update_vote_button_in_channel(context, giveaway_id, user_id, new_votes):
    try:
        giveaway = giveaways.get(giveaway_id)
        if not giveaway:
            return False
        
        if giveaway_id in vote_messages and user_id in vote_messages[giveaway_id]:
            message_id = vote_messages[giveaway_id][user_id]
            try:
                new_keyboard = [[
                    premium_button(f"Vote - {new_votes}", callback_data=f"vote_{giveaway_id}_{user_id}", emoji_id=EMOJI_VOTE, style=BUTTON_STYLE_SUCCESS)
                ]]
                await context.bot.edit_message_reply_markup(
                    chat_id=giveaway['channel_id'],
                    message_id=message_id,
                    reply_markup=InlineKeyboardMarkup(new_keyboard)
                )
                return True
            except Exception as e:
                logger.error(f"Failed to edit: {e}")
                return False
        return False
    except Exception as e:
        logger.error(f"Error updating: {e}")
        return False

# ================= START COMMAND ================= #
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    if SECURITY_ENABLED and user and user.id != OWNER_ID:
        if is_security_banned(user.id):
            await update.message.reply_text("🚫 You are banned from using this bot.")
            return

        profile_found, profile_reason = check_profile_for_abuse(user)
        if profile_found and AUTO_BAN_ON_PROFILE_ABUSE:
            security_ban_user(user.id, profile_reason)
            await send_notification_to_owner(
                context,
                "🚨 PROFILE SECURITY AUTO-BAN",
                f"👤 {user.full_name or 'Unknown'}\\n"
                f"🔹 Username: @{user.username or 'N/A'}\\n"
                f"🆔 <code>{user.id}</code>\\n"
                f"⚠️ Reason: {profile_reason}"
            )
            await update.message.reply_text(
                "🚫 Your name/username contains a banned word. You have been banned."
            )
            return

    save_user(user.id, user.username, user.first_name, user.last_name, source="/start")

    # React to /start first, then show Telegram's native animated emoji.
    # Both are best-effort: unsupported clients/chat settings must not block /start.
    start_message = update.message
    if start_message:
        try:
            await context.bot.set_message_reaction(
                chat_id=update.effective_chat.id,
                message_id=start_message.message_id,
                reaction=[ReactionTypeEmoji(owner_settings.get("start_reaction", "❤️"))],
            )
        except Exception as error:
            logger.info("Start reaction unavailable: %s", type(error).__name__)
        try:
            await context.bot.send_dice(
                chat_id=update.effective_chat.id,
                emoji=owner_settings.get("start_animation", "🎲"),
                reply_to_message_id=start_message.message_id,
            )
        except Exception as error:
            logger.info("Start animation unavailable: %s", type(error).__name__)
    
    if context.args and len(context.args) > 0:
        giveaway_id = context.args[0]
        await handle_giveaway_link(update, giveaway_id, context)
        return

    keyboard = [
        [premium_button("CONNECT", url=f"https://t.me/{BOT_USERNAME}?startchannel=true&admin=post_messages", emoji_id=EMOJI_CONNECT, style=BUTTON_STYLE_SUCCESS)],
        [premium_button("CREATE", callback_data="create_giveaway", emoji_id=EMOJI_CREATE, style=BUTTON_STYLE_PRIMARY),
         premium_button("MANAGE", callback_data="my_giveaways", emoji_id=EMOJI_MANAGE, style=BUTTON_STYLE_PRIMARY)],
        [premium_button("MY VOTER BADGES", callback_data="profile", emoji_id=EMOJI_STAR, style=BUTTON_STYLE_PRIMARY)]
    ]

    welcome_text = (
        f"<b><tg-emoji emoji-id='{EMOJI_WELCOME}'>🙂</tg-emoji> WELCOME TO  VOTE GIVEAWAY BOT</b>\n\n"
        f"<i><tg-emoji emoji-id='{EMOJI_FIRE}'>☄️</tg-emoji> Create Powerful Vote Giveaways</i>\n"
        f"<i><tg-emoji emoji-id='{EMOJI_ARROW}'>➡️</tg-emoji> Real Time Vote System</i>\n"
        f"<i><tg-emoji emoji-id='{EMOJI_CHART}'>📈</tg-emoji> Advanced Management Tools</i>\n"
        f"<i><tg-emoji emoji-id='{EMOJI_HEART}'>❤️‍🔥</tg-emoji> Leaderboard & Analytics</i>\n\n"
        f"<b><tg-emoji emoji-id='{EMOJI_ROCKET}'>🚀</tg-emoji> START CREATING NOW!</b>"
    )

    custom = owner_settings.get("welcome_text")
    if custom:
        welcome_text = f"<tg-emoji emoji-id='{EMOJI_PURPLE_HEART}'>💜</tg-emoji> {escape(small_caps_text(custom))}"
    for item in owner_settings.get("welcome_buttons", []):
        keyboard.append([premium_button(item["label"], url=item["url"], emoji_id=EMOJI_LINK, style=BUTTON_STYLE_PRIMARY)])
    media = owner_settings.get("welcome_media")
    welcome_video = owner_settings.get("welcome_video")
    if not welcome_video and media and media.get("kind") == "video":
        welcome_video = media
    if welcome_video:
        await update.message.reply_video(welcome_video["file_id"])
    elif media and media.get("kind") == "photo":
        await update.message.reply_photo(media["file_id"])
    await update.message.reply_text(text=welcome_text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_giveaway_link(update: Update, giveaway_id: str, context):
    if giveaway_id not in giveaways:
        await update.message.reply_text(
            f"<tg-emoji emoji-id='{EMOJI_ERROR}'>❌</tg-emoji> <b>INVALID LINK</b>",
            parse_mode="HTML"
        )
        return

    giveaway = giveaways[giveaway_id]
    user_id = update.effective_user.id
    
    if giveaway.get("ended", False):
        await update.message.reply_text(
            f"<tg-emoji emoji-id='{EMOJI_ENDED}'>❌</tg-emoji> <b>GIVEAWAY ENDED</b>",
            parse_mode="HTML"
        )
        return

    if user_id in giveaway.get("users", {}):
        await update.message.reply_text(
            f"<tg-emoji emoji-id='{EMOJI_STAR}'>🌟</tg-emoji> <b>ALREADY PARTICIPATED!</b>\n\n"
            f"<tg-emoji emoji-id='{EMOJI_ID}'>💬</tg-emoji> <b>Your ID:</b> <code>{user_id}</code>",
            parse_mode="HTML"
        )
        return

    # Check if user is a member of the channel
    channel_id = giveaway.get('channel_id')
    is_member = False
    
    if channel_id:
        try:
            member = await context.bot.get_chat_member(chat_id=channel_id, user_id=user_id)
            if member.status in ['member', 'administrator', 'creator']:
                is_member = True
            elif member.status == 'restricted' and getattr(member, 'is_member', False):
                is_member = True
        except Exception as e:
            logger.error(f"Error checking membership: {e}")
    
    if is_member:
        # User is a member - show join button
        keyboard = [[
            premium_button("JOIN GIVEAWAY", callback_data=f"join_{giveaway_id}", emoji_id=EMOJI_JOIN, style=BUTTON_STYLE_SUCCESS)
        ]]
        channel_display = giveaway.get("channel_display", giveaway.get("channel", "Channel"))
        
        await update.message.reply_text(
            f"<tg-emoji emoji-id='{EMOJI_GIFT}'>🎁</tg-emoji> <b>EXCLUSIVE GIVEAWAY</b>\n\n"
            f"<tg-emoji emoji-id='{EMOJI_WINE}'>🍷</tg-emoji> <b>Hosted By:</b> {channel_display}\n"
            f"<tg-emoji emoji-id='{EMOJI_SMILE}'>😎</tg-emoji> <b>Participants:</b> {len(giveaway['users'])}\n"
            + ("🧩 <b>Optional quest:</b> " + escape(giveaway["quest"]["question"]) + "\n" if giveaway.get("quest") else "") + "\n"
            f"<tg-emoji emoji-id='{EMOJI_CONFIRM}'>✅</tg-emoji> <b>You are a member of the channel!</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        # User is NOT a member - show channel join options
        channel_display = giveaway.get("channel_display", giveaway.get("channel", "Channel"))
        channel_identifier = giveaway.get("channel", "")
        
        # Get channel link
        channel_link = None
        try:
            if channel_identifier.startswith('@'):
                channel_link = f"https://t.me/{channel_identifier[1:]}"
            else:
                # Try to get invite link or use chat link
                chat = await context.bot.get_chat(channel_id)
                if chat.invite_link:
                    channel_link = chat.invite_link
                else:
                    channel_link = f"https://t.me/{BOT_USERNAME}?startchannel=true"
        except:
            channel_link = f"https://t.me/{BOT_USERNAME}?startchannel=true"
        
        keyboard = [
            [premium_button("JOIN CHANNEL", url=channel_link, emoji_id=EMOJI_CHANNEL, style=BUTTON_STYLE_SUCCESS)],
            [premium_button("TRY AGAIN", callback_data=f"retry_join_{giveaway_id}", emoji_id=EMOJI_REFRESH, style=BUTTON_STYLE_PRIMARY)]
        ]
        
        await update.message.reply_text(
            f"<tg-emoji emoji-id='{EMOJI_ALERT}'>⚠️</tg-emoji> <b>CHANNEL MEMBERSHIP REQUIRED</b>\n\n"
            f"<tg-emoji emoji-id='{EMOJI_GIFT}'>🎁</tg-emoji> <b>Giveaway Host:</b> {channel_display}\n\n"
            f"<i>You need to join the channel first to participate in this giveaway!</i>\n\n"
            f"<b>Steps to join:</b>\n"
            f"1️⃣ Click <b>JOIN CHANNEL</b> below\n"
            f"2️⃣ Join the channel\n"
            f"3️⃣ Click <b>TRY AGAIN</b> to verify membership",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

async def retry_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle retry join callback - checks membership again and opens the join link"""
    if owner_settings.get("paused"):
        await update.callback_query.answer("Giveaways are temporarily paused.", show_alert=True)
        return
    query = update.callback_query
    await query.answer()
    
    giveaway_id = query.data.split("_")[2]
    user_id = query.from_user.id
    
    if giveaway_id not in giveaways:
        await query.edit_message_text(
            f"<tg-emoji emoji-id='{EMOJI_ERROR}'>❌</tg-emoji> <b>Giveaway not found!</b>",
            parse_mode="HTML"
        )
        return
    
    giveaway = giveaways[giveaway_id]
    channel_id = giveaway.get('channel_id')
    channel_display = giveaway.get("channel_display", giveaway.get("channel", "Channel"))
    
    # Check membership again
    is_member = False
    if channel_id:
        try:
            member = await context.bot.get_chat_member(chat_id=channel_id, user_id=user_id)
            if member.status in ['member', 'administrator', 'creator']:
                is_member = True
            elif member.status == 'restricted' and getattr(member, 'is_member', False):
                is_member = True
        except Exception as e:
            logger.error(f"Error checking membership on retry: {e}")
    
    if is_member:
        # Now user is a member - show join button
        keyboard = [[
            premium_button("JOIN GIVEAWAY", callback_data=f"join_{giveaway_id}", emoji_id=EMOJI_JOIN, style=BUTTON_STYLE_SUCCESS)
        ]]
        
        await query.edit_message_text(
            f"<tg-emoji emoji-id='{EMOJI_GIFT}'>🎁</tg-emoji> <b>EXCLUSIVE GIVEAWAY</b>\n\n"
            f"<tg-emoji emoji-id='{EMOJI_WINE}'>🍷</tg-emoji> <b>Hosted By:</b> {channel_display}\n"
            f"<tg-emoji emoji-id='{EMOJI_SMILE}'>😎</tg-emoji> <b>Participants:</b> {len(giveaway['users'])}\n\n"
            f"<tg-emoji emoji-id='{EMOJI_CONFIRM}'>✅</tg-emoji> <b>Membership verified! You can now join.</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        # Still not a member - show the channel join options again
        channel_identifier = giveaway.get("channel", "")
        channel_link = None
        
        try:
            if channel_identifier.startswith('@'):
                channel_link = f"https://t.me/{channel_identifier[1:]}"
            else:
                chat = await context.bot.get_chat(channel_id)
                if chat.invite_link:
                    channel_link = chat.invite_link
                else:
                    channel_link = f"https://t.me/{BOT_USERNAME}?startchannel=true"
        except:
            channel_link = f"https://t.me/{BOT_USERNAME}?startchannel=true"
        
        keyboard = [
            [premium_button("JOIN CHANNEL", url=channel_link, emoji_id=EMOJI_CHANNEL, style=BUTTON_STYLE_SUCCESS)],
            [premium_button("TRY AGAIN", callback_data=f"retry_join_{giveaway_id}", emoji_id=EMOJI_REFRESH, style=BUTTON_STYLE_PRIMARY)]
        ]
        
        await query.edit_message_text(
            f"<tg-emoji emoji-id='{EMOJI_ALERT}'>⚠️</tg-emoji> <b>STILL NOT A MEMBER</b>\n\n"
            f"<tg-emoji emoji-id='{EMOJI_GIFT}'>🎁</tg-emoji> <b>Giveaway Host:</b> {channel_display}\n\n"
            f"<i>Please join the channel first!</i>\n\n"
            f"<b>Steps to join:</b>\n"
            f"1️⃣ Click <b>JOIN CHANNEL</b> below\n"
            f"2️⃣ Join the channel\n"
            f"3️⃣ Click <b>TRY AGAIN</b> to verify membership",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

# ================= CREATE GIVEAWAY ================= #
async def create_giveaway_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user_sessions[user_id] = {"step": "waiting_channel"}
    keyboard = [[premium_button("CANCEL", callback_data="cancel_creation", emoji_id=EMOJI_CANCEL, style=BUTTON_STYLE_DANGER)]]
    await query.edit_message_text(
        text=f"<b><tg-emoji emoji-id='{EMOJI_LIGHTNING}'>⚡</tg-emoji> CREATE GIVEAWAY</b>\n\n"
             f"<i><tg-emoji emoji-id='{EMOJI_POINTER}'>⬅️</tg-emoji> Send your channel information:</i>\n\n"
             f"<b>Public:</b> <code>@username</code>\n<b>Private:</b> <code>-1001234567890</code>",
        parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def cancel_creation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    if user_id in user_sessions:
        del user_sessions[user_id]
    
    keyboard = [
        [premium_button("CONNECT", url=f"https://t.me/{BOT_USERNAME}?startchannel=true&admin=post_messages", emoji_id=EMOJI_CONNECT, style=BUTTON_STYLE_SUCCESS)],
        [premium_button("CREATE", callback_data="create_giveaway", emoji_id=EMOJI_CREATE, style=BUTTON_STYLE_PRIMARY),
         premium_button("MANAGE", callback_data="my_giveaways", emoji_id=EMOJI_MANAGE, style=BUTTON_STYLE_PRIMARY)]
    ]
    
    await query.edit_message_text(
        text="✅ <b>Cancelled!</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def process_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name
    
    if user_id not in user_sessions or user_sessions[user_id].get("step") != "waiting_channel":
        return
    
    channel_input = update.message.text.strip()
    loading_msg = await update.message.reply_text(
        f"<tg-emoji emoji-id='{EMOJI_LIGHTNING}'>⚡</tg-emoji> <b>Verifying...</b>",
        parse_mode="HTML"
    )
    
    try:
        if channel_input.startswith('@'):
            chat = await context.bot.get_chat(chat_id=channel_input)
            channel_info = {"identifier": channel_input, "display_name": channel_input, "chat_id": chat.id, "type": "public"}
        else:
            chat = await context.bot.get_chat(chat_id=int(channel_input))
            channel_info = {"identifier": str(channel_input), "display_name": chat.title or f"Channel {channel_input}", "chat_id": chat.id, "type": "private"}
    except Exception as e:
        await loading_msg.delete()
        error = str(e).lower()
        if "bot is not a member" in error or "not enough rights" in error:
            await update.message.reply_text(
                f"🤖 <b>Bot is not admin!</b>\n\nPlease add @{BOT_USERNAME} as an admin in the channel first.",
                parse_mode="HTML"
            )
        else:
            await update.message.reply_text(
                f"<tg-emoji emoji-id='{EMOJI_ERROR}'>❌</tg-emoji> <b>Invalid channel!</b>",
                parse_mode="HTML"
            )
        del user_sessions[user_id]
        return
    
    for gid, gdata in giveaways.items():
        if gdata.get("channel") == channel_info["identifier"] and not gdata.get("ended", False):
            await loading_msg.delete()
            existing_link = f"https://t.me/{BOT_USERNAME}?start={gid}"
            await update.message.reply_text(
                f"<tg-emoji emoji-id='{EMOJI_ALERT}'>⚠️</tg-emoji> <b>GIVEAWAY ALREADY ACTIVE!</b>\n\n"
                f"<b>Channel:</b> {channel_info['display_name']}\n\n"
                f"<b>Active Link:</b>\n<code>{existing_link}</code>",
                parse_mode="HTML"
            )
            del user_sessions[user_id]
            return
    
    try:
        test_msg = await context.bot.send_message(chat_id=channel_info["chat_id"], text="✅ Bot connected!")
        await test_msg.delete()
    except:
        await loading_msg.delete()
        await update.message.reply_text(
            f"🤖 <b>Bot is not admin!</b>\n\nPlease add @{BOT_USERNAME} as an admin in the channel first.",
            parse_mode="HTML"
        )
        del user_sessions[user_id]
        return
    
    giveaway_id = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
    link = f"https://t.me/{BOT_USERNAME}?start={giveaway_id}"
    
    giveaways[giveaway_id] = {
        "channel": channel_info["identifier"], "channel_display": channel_info["display_name"],
        "channel_id": channel_info["chat_id"], "users": {}, "vote_counts": {}, "voted_users": {},
        "creator": user_id, "creator_name": user_name, "ended": False, "created_at": datetime.now().isoformat()
    }
    seed = secrets.token_hex(32)
    giveaways[giveaway_id]["fair_seed"] = seed
    giveaways[giveaway_id]["fair_commit"] = hashlib.sha256(seed.encode()).hexdigest()
    giveaways[giveaway_id]["winner_rules"] = {"minimum": 1, "count": 1, "tie": "random"}
    
    update_channel_history(
        channel_identifier=channel_info["identifier"],
        channel_display=channel_info["display_name"],
        channel_id=channel_info["chat_id"],
        user_id=user_id,
        user_name=user_name,
        action="create",
        giveaway_id=giveaway_id
    )
    
    vote_messages[giveaway_id] = {}
    save_data()
    
    if user_id != OWNER_ID:
        await send_notification_to_owner(context, "🔔 NEW GIVEAWAY CREATED!",
            f"👤 {user_name}\n🆔 <code>{user_id}</code>\n📢 {channel_info['display_name']}\n🔗 <code>{link}</code>")
    
    try:
        progress = await context.bot.send_message(
            chat_id=channel_info["chat_id"],
            text=f"🎉 <b>NEW GIVEAWAY STARTED!</b>\n\n🔗 JOIN: {link}\n👥 Participants: 0\n🗳 Votes: 0\n\n🔐 Fair draw commitment: <code>{giveaways[giveaway_id]['fair_commit']}</code>",
            parse_mode="HTML",
            disable_web_page_preview=True
        )
        giveaways[giveaway_id]["progress_message_id"] = progress.message_id
        save_data()
    except: pass
    
    await loading_msg.delete()
    
    success_text = (
        f"<b><tg-emoji emoji-id='{EMOJI_CLOWN}'>✅</tg-emoji> GIVEAWAY CREATED!</b>\n\n"
        f"<b><tg-emoji emoji-id='{EMOJI_SEARCH}'>🔍</tg-emoji> ID:</b> <code>{giveaway_id}</code>\n"
        f"<b><tg-emoji emoji-id='{EMOJI_SPEAKER}'>📣</tg-emoji> Channel:</b> {channel_info['display_name']}\n\n"
        f"<b><tg-emoji emoji-id='{EMOJI_LINK}'>🔗</tg-emoji> LINK:</b>\n<code>{link}</code>"
    )
    
    keyboard = [[
        premium_button("MANAGE", callback_data=f"manage_{giveaway_id}", emoji_id=EMOJI_MANAGE, style=BUTTON_STYLE_PRIMARY),
        premium_button("MAIN MENU", callback_data="main_menu", emoji_id=EMOJI_MAIN_MENU, style=BUTTON_STYLE_PRIMARY)
    ]]
    
    await update.message.reply_text(success_text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
    del user_sessions[user_id]

# ================= MANAGE ================= #
async def my_giveaways(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    text = f"<b><tg-emoji emoji-id='{EMOJI_CROWN}'>👑</tg-emoji> YOUR GIVEAWAYS</b>\n\n"
    keyboard = []
    found = False
    
    for gid, gdata in giveaways.items():
        if gdata.get("creator") == user_id and not gdata.get("ended", False):
            found = True
            keyboard.append([premium_button(
                text=f"📢 {gdata.get('channel_display', gdata.get('channel'))}",
                callback_data=f"manage_{gid}",
                emoji_id=EMOJI_MANAGE,
                style=BUTTON_STYLE_PRIMARY
            )])
    
    if not found:
        text = f"<tg-emoji emoji-id='{EMOJI_ERROR}'>❌</tg-emoji> <b>No active giveaways!</b>"
        keyboard.append([premium_button("CREATE NEW", callback_data="create_giveaway", emoji_id=EMOJI_CREATE, style=BUTTON_STYLE_PRIMARY)])
    
    keyboard.append([premium_button("MAIN MENU", callback_data="main_menu", emoji_id=EMOJI_MAIN_MENU, style=BUTTON_STYLE_PRIMARY)])
    
    await query.edit_message_text(text=text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))

async def manage_giveaway(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    giveaway_id = query.data.split("_")[1]
    if giveaway_id not in giveaways:
        await query.edit_message_text(f"<tg-emoji emoji-id='{EMOJI_ERROR}'>❌</tg-emoji> Not found!", parse_mode="HTML")
        return
    
    giveaway = giveaways[giveaway_id]
    status = "🟢 ACTIVE" if not giveaway.get("ended") else "🔴 ENDED"
    
    keyboard = [
        [
            premium_button("ADD VOTES", callback_data=f"addvotes_{giveaway_id}", emoji_id=EMOJI_ADD_VOTES, style=BUTTON_STYLE_PRIMARY),
            premium_button("REMOVE VOTES", callback_data=f"removevotes_{giveaway_id}", emoji_id=EMOJI_REMOVE_VOTES, style=BUTTON_STYLE_DANGER)
        ],
        [
            premium_button("LEADERBOARD", callback_data=f"leaderboard_{giveaway_id}", emoji_id=EMOJI_LEADERBOARD, style=BUTTON_STYLE_PRIMARY)
        ],
        [
            premium_button("END GIVEAWAY", callback_data=f"endgiveaway_{giveaway_id}", emoji_id=EMOJI_END_GIVEAWAY, style=BUTTON_STYLE_DANGER)
        ],
        [
            premium_button("BACK", callback_data="my_giveaways", emoji_id=EMOJI_BACK, style=BUTTON_STYLE_PRIMARY)
        ]
    ]
    
    await query.edit_message_text(
        text=f"<b><tg-emoji emoji-id='{EMOJI_ARROW}'>➡️</tg-emoji> MANAGEMENT PANEL</b>\n\n"
             f"<b>Status:</b> {status}\n"
             f"<b>Channel:</b> {giveaway.get('channel_display', giveaway.get('channel'))}\n"
             f"<b>Joined:</b> {len(giveaway.get('users', {}))}",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ================= VOTE MANAGEMENT ================= #
async def add_votes_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    giveaway_id = query.data.split("_")[1]
    context.user_data["vote_giveaway"] = giveaway_id
    context.user_data["vote_action"] = "add"
    await query.edit_message_text(
        text=f"<b><tg-emoji emoji-id='{EMOJI_DIAMOND}'>💎</tg-emoji> ADD VOTES</b>\n\nSend: <code>USER_ID VOTES</code>\nExample: <code>12345678 10</code>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[premium_button("BACK", callback_data=f"manage_{giveaway_id}", emoji_id=EMOJI_BACK, style=BUTTON_STYLE_PRIMARY)]])
    )

async def remove_votes_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    giveaway_id = query.data.split("_")[1]
    context.user_data["vote_giveaway"] = giveaway_id
    context.user_data["vote_action"] = "remove"
    await query.edit_message_text(
        text=f"<b><tg-emoji emoji-id='{EMOJI_DIAMOND}'>💎</tg-emoji> REMOVE VOTES</b>\n\nSend: <code>USER_ID VOTES</code>\nExample: <code>12345678 5</code>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[premium_button("BACK", callback_data=f"manage_{giveaway_id}", emoji_id=EMOJI_BACK, style=BUTTON_STYLE_PRIMARY)]])
    )

async def process_vote_change(update: Update, context: ContextTypes.DEFAULT_TYPE):
    giveaway_id = context.user_data.get("vote_giveaway")
    action = context.user_data.get("vote_action")
    if not giveaway_id or giveaway_id not in giveaways:
        return
    
    try:
        parts = update.message.text.strip().split()
        target_uid = int(parts[0])
        votes = int(parts[1])
    except:
        await update.message.reply_text(f"<tg-emoji emoji-id='{EMOJI_ALERT}'>⚠️</tg-emoji> Invalid! Send <code>USER_ID VOTES</code>.", parse_mode="HTML")
        return
    
    giveaway = giveaways[giveaway_id]
    if target_uid not in giveaway['users']:
        await update.message.reply_text(f"<tg-emoji emoji-id='{EMOJI_ERROR}'>❌</tg-emoji> User not found!", parse_mode="HTML")
        return
    
    if votes <= 0:
        await update.message.reply_text("Votes must be a positive number.")
        return
    if not can_manage(update.effective_user.id, giveaway):
        context.user_data.clear()
        await update.message.reply_text("Access denied.")
        return
    if giveaway.get('ended'):
        await update.message.reply_text('Ended giveaway votes are locked.')
        return
    old_votes = giveaway['vote_counts'].get(target_uid, 0)
    
    if action == "add":
        giveaway['vote_counts'][target_uid] = old_votes + votes
        msg = f"<tg-emoji emoji-id='{EMOJI_DIAMOND}'>💎</tg-emoji> Added +{votes} votes!"
    else:
        giveaway['vote_counts'][target_uid] = max(0, old_votes - votes)
        msg = f"<tg-emoji emoji-id='{EMOJI_DIAMOND}'>💎</tg-emoji> Removed {votes} votes!"
    
    new_votes = giveaway['vote_counts'][target_uid]
    audit(update.effective_user.id, 'vote_change', giveaway_id, user_id=target_uid, before=old_votes, after=new_votes)
    save_data()
    
    await update_vote_button_in_channel(context, giveaway_id, target_uid, new_votes)
    
    await update.message.reply_text(
        f"{msg}\n<b>New Total:</b> {new_votes} votes",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[premium_button("BACK", callback_data=f"manage_{giveaway_id}", emoji_id=EMOJI_BACK, style=BUTTON_STYLE_PRIMARY)]])
    )
    
    del context.user_data["vote_giveaway"]
    del context.user_data["vote_action"]

async def show_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    giveaway_id = query.data.split("_")[1]
    giveaway = giveaways[giveaway_id]
    
    sorted_users = sorted(giveaway['vote_counts'].items(), key=lambda x: x[1], reverse=True)[:10]
    
    text = f"<b><tg-emoji emoji-id='{EMOJI_CALENDAR}'>🗓</tg-emoji> LEADERBOARD</b>\n\n"
    if not sorted_users:
        text += "<i>No votes yet.</i>"
    else:
        for idx, (uid, votes) in enumerate(sorted_users, 1):
            name = giveaway['users'].get(uid, f"User {uid}")
            text += f"<b>{idx}.</b> {name} - <b>{votes} votes</b>\n"
    
    await query.edit_message_text(
        text=text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[premium_button("BACK", callback_data=f"manage_{giveaway_id}", emoji_id=EMOJI_BACK, style=BUTTON_STYLE_PRIMARY)]])
    )

async def end_giveaway(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    giveaway_id = query.data.split("_")[1]
    await query.edit_message_text(
        text=f"<b><tg-emoji emoji-id='{EMOJI_LOCK}'>🔒</tg-emoji> End this giveaway?</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [premium_button("CONFIRM", callback_data=f"confirm_end_{giveaway_id}", emoji_id=EMOJI_CONFIRM, style=BUTTON_STYLE_DANGER)],
            [premium_button("CANCEL", callback_data=f"manage_{giveaway_id}", emoji_id=EMOJI_CANCEL, style=BUTTON_STYLE_PRIMARY)]
        ])
    )

async def confirm_end_giveaway(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    gid = query.data[len("confirm_end_"):]
    g = giveaways.get(gid)
    if not g or not can_manage(update.effective_user.id, g):
        await query.edit_message_text("Access denied or giveaway expired.")
        return
    await finish_giveaway(context.bot, gid, update.effective_user.id)
    await query.edit_message_text("Giveaway ended. Announcement/prize status is in Advanced → Delivery Status.")

# ================= JOIN HANDLER (WITH CHANNEL CHECK) ================= #
async def handle_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if owner_settings.get("paused"):
        await update.callback_query.answer("Giveaways are temporarily paused.", show_alert=True)
        return
    query = update.callback_query
    await query.answer()
    
    giveaway_id = query.data.split("_")[1]
    user = query.from_user

    if is_security_banned(user.id):
        await query.answer("🚫 You are banned from this bot.", show_alert=True)
        return
    
    save_user(user.id, user.username, user.first_name, user.last_name, source="join")
    
    if giveaway_id not in giveaways:
        await query.answer("Giveaway not found!", show_alert=True)
        return

    giveaway = giveaways[giveaway_id]
    
    if giveaway.get("ended"):
        await query.answer("❌ This giveaway has already ended!", show_alert=True)
        return
        
    if user.id in giveaway["users"]:
        await query.answer("⚠️ Already Joined!", show_alert=True)
        return
    
    # Double-check membership before allowing join
    channel_id = giveaway.get('channel_id')
    is_member = False
    
    if channel_id:
        try:
            member = await context.bot.get_chat_member(chat_id=channel_id, user_id=user.id)
            if member.status in ['member', 'administrator', 'creator']:
                is_member = True
            elif member.status == 'restricted' and getattr(member, 'is_member', False):
                is_member = True
        except Exception as e:
            logger.error(f"Error checking membership: {e}")
    
    if not is_member:
        # User is not a member - redirect to membership flow
        channel_display = giveaway.get("channel_display", giveaway.get("channel", "Channel"))
        channel_identifier = giveaway.get("channel", "")
        
        channel_link = None
        try:
            if channel_identifier.startswith('@'):
                channel_link = f"https://t.me/{channel_identifier[1:]}"
            else:
                chat = await context.bot.get_chat(channel_id)
                if chat.invite_link:
                    channel_link = chat.invite_link
                else:
                    channel_link = f"https://t.me/{BOT_USERNAME}?startchannel=true"
        except:
            channel_link = f"https://t.me/{BOT_USERNAME}?startchannel=true"
        
        keyboard = [
            [premium_button("JOIN CHANNEL", url=channel_link, emoji_id=EMOJI_CHANNEL, style=BUTTON_STYLE_SUCCESS)],
            [premium_button("TRY AGAIN", callback_data=f"retry_join_{giveaway_id}", emoji_id=EMOJI_REFRESH, style=BUTTON_STYLE_PRIMARY)]
        ]
        
        await query.edit_message_text(
            f"<tg-emoji emoji-id='{EMOJI_ALERT}'>⚠️</tg-emoji> <b>CHANNEL MEMBERSHIP REQUIRED</b>\n\n"
            f"<tg-emoji emoji-id='{EMOJI_GIFT}'>🎁</tg-emoji> <b>Giveaway Host:</b> {channel_display}\n\n"
            f"<i>You need to join the channel first to participate!</i>\n\n"
            f"<b>Steps to join:</b>\n"
            f"1️⃣ Click <b>JOIN CHANNEL</b> below\n"
            f"2️⃣ Join the channel\n"
            f"3️⃣ Click <b>TRY AGAIN</b> to verify membership",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
        
    quest = giveaway.get("quest")
    if quest and not giveaway.get("quest_results", {}).get(str(user.id)):
        context.user_data["giveaway_quest"] = {"gid": giveaway_id, "attempts": 0}
        await query.edit_message_text(
            "🧩 <b>Optional giveaway quest</b>\n\n" + escape(quest["question"]) + "\n\nReply with your answer to verify entry.",
            parse_mode="HTML",
        )
        return
    await register_giveaway_participant(context.bot, giveaway_id, user)
    await query.answer("✅ Registration Successful!", show_alert=True)
    await query.edit_message_text(
        text=f"✅ <b>Registration Successful!</b>\n\n😎 {escape(user.full_name or user.first_name)}\n💌 <code>{user.id}</code>\n\n📥 Profile shared in channel!",
        parse_mode="HTML"
    )


async def register_giveaway_participant(bot, giveaway_id, user):
    giveaway = giveaways[giveaway_id]
    giveaway["users"][user.id] = user.full_name or user.first_name
    giveaway["vote_counts"][user.id] = 0
    giveaway["voted_users"][user.id] = set()
    update_user_stats(user.id, "join")
    save_data()
    keyboard = [[premium_button("Vote - 0", callback_data=f"vote_{giveaway_id}_{user.id}", emoji_id=EMOJI_VOTE, style=BUTTON_STYLE_SUCCESS)]]
    try:
        sent_msg = await bot.send_message(
            chat_id=giveaway["channel_id"],
            text=f"😎 <b>Name:</b> {escape(user.full_name or user.first_name)}\n💌 <b>ID:</b> <code>{user.id}</code>",
            parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard)
        )
        vote_messages.setdefault(giveaway_id, {})[user.id] = sent_msg.message_id
    except Exception as error:
        logger.error("Could not publish participant card: %s", type(error).__name__)
    await update_progress_card(bot, giveaway_id)


async def profile_command(update, context):
    user = update.effective_user
    profile = all_users.get(str(user.id), {})
    badges = profile.get("badges", [])
    await update.effective_message.reply_text(
        f"🏅 <b>VOTER PROFILE</b>\n\nVotes cast: <code>{profile.get('total_votes_given', 0)}</code>\n"
        f"Vote streak: <code>{profile.get('vote_streak', 0)} days</code>\nGiveaways joined: <code>{profile.get('total_giveaways_joined', 0)}</code>\n\n"
        + ("Badges: " + escape(", ".join(badges)) if badges else "Badges: Cast votes to earn badges."),
        parse_mode="HTML",
    )


async def demo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Preview a hypothetical draw without changing or ending the giveaway."""
    if not context.args:
        await update.effective_message.reply_text("Usage: /demo GIVEAWAY_ID")
        return
    gid = context.args[0].strip()
    g = giveaways.get(gid)
    if not g:
        await update.effective_message.reply_text("Giveaway not found.")
        return
    if not can_manage(update.effective_user.id, g):
        await update.effective_message.reply_text("You cannot manage this giveaway.")
        return

    await update.effective_message.reply_text(demo_draw_text(gid), parse_mode="HTML")


def demo_draw_text(gid):
    g = giveaways[gid]
    # Use a temporary seed so the preview cannot reveal or consume the actual draw.
    preview = dict(g, fair_seed=secrets.token_hex(32))
    winners = select_winners(preview)
    lines = ["<b>DEMO DRAW · PREVIEW ONLY</b>", f"Giveaway: <code>{escape(gid)}</code>"]
    if winners:
        for winner in winners:
            uid = winner["user_id"]
            name = escape(str(g.get("users", {}).get(uid, f"User {uid}"))[:80])
            lines.append(f"{winner['rank']}. {name} · {winner['votes']} votes")
    else:
        lines.append("No eligible entries meet the minimum vote rule.")
    lines.append("This preview does not end the giveaway or deliver prizes.")
    return "\n".join(lines)


async def process_quest_answer(update, context):
    state = context.user_data.get("giveaway_quest")
    if not state or not update.message or not update.message.text:
        return False
    gid = state["gid"]
    g = giveaways.get(gid)
    if not g or g.get("ended") or not g.get("quest"):
        context.user_data.pop("giveaway_quest", None)
        await update.message.reply_text("This quest is no longer active.")
        return True
    user = update.effective_user
    state["attempts"] += 1
    answer_hash = hashlib.sha256(update.message.text.strip().casefold().encode()).hexdigest()
    if not hmac.compare_digest(answer_hash, g["quest"]["answer_hash"]):
        if state["attempts"] >= 3:
            context.user_data.pop("giveaway_quest", None)
            await update.message.reply_text("Quest attempts used up. You can start the giveaway again later.")
        else:
            await update.message.reply_text("That answer did not match. Try again, or /cancel to stop.")
        return True
    try:
        member = await context.bot.get_chat_member(chat_id=g["channel_id"], user_id=user.id)
        if member.status in ("left", "kicked") or (member.status == "restricted" and not getattr(member, "is_member", False)):
            await update.message.reply_text("Join the giveaway channel first, then restart the giveaway link.")
            context.user_data.pop("giveaway_quest", None)
            return True
    except Exception:
        await update.message.reply_text("I could not verify channel membership. Please try the giveaway link again.")
        context.user_data.pop("giveaway_quest", None)
        return True
    g.setdefault("quest_results", {})[str(user.id)] = True
    context.user_data.pop("giveaway_quest", None)
    await register_giveaway_participant(context.bot, gid, user)
    await update.message.reply_text("✅ Quest complete. Your entry is registered!")
    return True


async def update_progress_card(bot, giveaway_id):
    g = giveaways.get(giveaway_id, {})
    message_id = g.get("progress_message_id")
    if not message_id:
        return
    total_votes = sum(g.get("vote_counts", {}).values())
    text = (f"🎉 <b>GIVEAWAY {'ENDED' if g.get('ended') else 'LIVE'}</b>\n\n"
            f"🔗 Join: https://t.me/{BOT_USERNAME}?start={giveaway_id}\n"
            f"👥 Participants: {len(g.get('users', {}))}\n🗳 Votes: {total_votes}")
    leaderboard = sorted(g.get("vote_counts", {}).items(), key=lambda item: (-item[1], int(item[0])))[:5]
    if leaderboard:
        text += "\n\n<b>LIVE TOP 5</b>"
        for rank, (uid, votes) in enumerate(leaderboard, 1):
            name = escape(str(g.get("users", {}).get(uid, f"User {uid}"))[:35])
            text += f"\n{rank}. {name} · {votes} votes"
    try:
        await bot.edit_message_text(chat_id=g["channel_id"], message_id=message_id,
                                    text=text, parse_mode="HTML", disable_web_page_preview=True)
    except Exception:
        pass

# ================= VOTE HANDLER (WITH POPUP) ================= #
async def handle_vote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if owner_settings.get("paused"):
        await update.callback_query.answer("Giveaways are temporarily paused.", show_alert=True)
        return
    query = update.callback_query
    await query.answer()
    
    parts = query.data.split("_")
    giveaway_id = parts[1]
    target_user_id = int(parts[2])
    voter_id = query.from_user.id

    if is_security_banned(voter_id):
        await query.answer("🚫 You are banned from this bot.", show_alert=True)
        return
    
    voter = query.from_user
    if voter.is_bot:
        await query.answer("Bot accounts cannot cast votes.", show_alert=True)
        return
    save_user(voter.id, voter.username, voter.first_name, voter.last_name, source="vote")
    
    if giveaway_id not in giveaways:
        await query.answer("❌ Giveaway not active!", show_alert=True)
        return
        
    giveaway = giveaways[giveaway_id]
    
    if giveaway.get("ended"):
        await query.answer("❌ This giveaway has ended!", show_alert=True)
        return

    try:
        member = await context.bot.get_chat_member(chat_id=giveaway['channel_id'], user_id=voter_id)
        if member.status in ['left', 'kicked']:
            await query.answer("⚠️ Only channel members can vote! Please join the channel first.", show_alert=True)
            return
        if member.status == 'restricted' and not getattr(member, 'is_member', False):
            await query.answer("⚠️ Only channel members can vote! Please join the channel first.", show_alert=True)
            return
    except:
        await query.answer("⚠️ Please join the channel first to vote!", show_alert=True)
        return

    suspicious, vote_count, target_count = register_vote_activity(voter_id, target_user_id)
    if SECURITY_ENABLED and suspicious:
        suspicious_scores[voter_id] += 1
        owner_settings["suspicious_scores"] = dict(suspicious_scores)
        save_data()
        if AUTO_BAN_ON_ABUSE and suspicious_scores[voter_id] >= SUSPICIOUS_SCORE_LIMIT:
            security_ban_user(voter_id, "suspicious multi/fake voting activity")
            await send_notification_to_owner(
                context,
                "🚨 SECURITY AUTO-BAN",
                f"👤 {voter.full_name or 'Unknown'}\n🆔 <code>{voter_id}</code>\n⚠️ Reason: suspicious voting ({vote_count} votes / {target_count} targets in {VOTE_WINDOW_SECONDS}s)"
            )
            await query.answer("🚫 Suspicious voting detected. You are banned.", show_alert=True)
            return
        await query.answer("⚠️ Voting too quickly. Please slow down.", show_alert=True)
        return

    if target_user_id not in giveaway["voted_users"]:
        giveaway["voted_users"][target_user_id] = set()

    if voter_id in giveaway["voted_users"][target_user_id]:
        await query.answer("⚠️ You have already voted for this user!", show_alert=True)
        return

    giveaway["voted_users"][target_user_id].add(voter_id)
    giveaway['vote_counts'][target_user_id] = giveaway['vote_counts'].get(target_user_id, 0) + 1
    new_votes = giveaway['vote_counts'][target_user_id]
    update_user_stats(voter_id, "vote")
    badges = record_vote_badges(voter_id)
    save_data()
    
    await update_vote_button_in_channel(context, giveaway_id, target_user_id, new_votes)
    await update_progress_card(context.bot, giveaway_id)
    earned = [badge for badge in badges if badge in ("First Vote", "Vote Starter", "Vote Pro", "Vote Legend", "3 Day Streak", "7 Day Streak", "30 Day Streak")]
    await query.answer("🎉 Vote recorded!" + (" 🏅 " + ", ".join(earned) if earned else ""), show_alert=bool(earned))

# ================= ADMIN COMMANDS ================= #
async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        if staff_role(update.effective_user.id):
            await extra_view(update, context, "home")
            return
        await update.effective_message.reply_text("Owner access only.")
        return
    await owner_view(update, context, "home")

async def bc_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/bc {msg} - Send message to all channels where bot has active giveaways"""
    user_id = update.effective_user.id
    if not is_owner(user_id):
        await update.message.reply_text("❌ You are not the owner!")
        return
    
    if not context.args:
        await update.message.reply_text("❌ Usage: /bc <message>")
        return
    
    msg = ' '.join(context.args)
    await update.message.reply_text(f"🚀 <b>Sending to all channels...</b>\n\nMessage: {msg[:100]}...", parse_mode="HTML", _preserve_smallcaps=True)
    
    success = 0
    fail = 0
    channels_sent = set()
    
    for gid, gdata in giveaways.items():
        channel_id = gdata.get('channel_id')
        if channel_id and channel_id not in channels_sent and not gdata.get('ended', False):
            channels_sent.add(channel_id)
            try:
                await context.bot.send_message(chat_id=channel_id, text=msg, parse_mode="HTML", disable_web_page_preview=True, _preserve_smallcaps=True)
                success += 1
            except Exception as e:
                logger.error(f"Failed to send to channel {channel_id}: {e}")
                fail += 1
            await asyncio.sleep(0.5)
    
    await update.message.reply_text(
        f"<b>✅ BROADCAST TO CHANNELS COMPLETED!</b>\n\n"
        f"<b>✅ Sent:</b> <code>{success}</code>\n"
        f"<b>❌ Failed:</b> <code>{fail}</code>\n"
        f"<b>📊 Total Channels:</b> <code>{len(channels_sent)}</code>",
        parse_mode="HTML"
    )

async def ball_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/ball {msg} - Send message to all users AND all channels"""
    user_id = update.effective_user.id
    if not is_owner(user_id):
        await update.message.reply_text("❌ You are not the owner!")
        return
    
    if not context.args:
        await update.message.reply_text("❌ Usage: /ball <message>")
        return
    
    msg = ' '.join(context.args)
    await update.message.reply_text(f"🚀 <b>Sending to ALL USERS + ALL CHANNELS...</b>\n\nMessage: {msg[:100]}...", parse_mode="HTML", _preserve_smallcaps=True)
    
    # Send to all users
    user_success = 0
    user_fail = 0
    for uid in all_users.keys():
        try:
            await context.bot.send_message(chat_id=int(uid), text=msg, parse_mode="HTML", disable_web_page_preview=True, _preserve_smallcaps=True)
            user_success += 1
        except:
            user_fail += 1
        await asyncio.sleep(0.05)
    
    # Send to all channels
    channel_success = 0
    channel_fail = 0
    channels_sent = set()
    
    for gid, gdata in giveaways.items():
        channel_id = gdata.get('channel_id')
        if channel_id and channel_id not in channels_sent and not gdata.get('ended', False):
            channels_sent.add(channel_id)
            try:
                await context.bot.send_message(chat_id=channel_id, text=msg, parse_mode="HTML", disable_web_page_preview=True, _preserve_smallcaps=True)
                channel_success += 1
            except Exception as e:
                logger.error(f"Failed to send to channel {channel_id}: {e}")
                channel_fail += 1
            await asyncio.sleep(0.5)
    
    await update.message.reply_text(
        f"<b>✅ BALL BROADCAST COMPLETED!</b>\n\n"
        f"<b>📱 USERS:</b>\n"
        f"   ✅ Sent: <code>{user_success}</code>\n"
        f"   ❌ Failed: <code>{user_fail}</code>\n"
        f"   📊 Total: <code>{len(all_users)}</code>\n\n"
        f"<b>📺 CHANNELS:</b>\n"
        f"   ✅ Sent: <code>{channel_success}</code>\n"
        f"   ❌ Failed: <code>{channel_fail}</code>\n"
        f"   📊 Total: <code>{len(channels_sent)}</code>",
        parse_mode="HTML"
    )

async def g_management_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/g_management {giveaway_id} - Open management panel for any giveaway (owner only)"""
    user_id = update.effective_user.id
    if not is_owner(user_id):
        await update.message.reply_text("❌ You are not the owner!")
        return
    
    if not context.args:
        await update.message.reply_text("❌ Usage: /g_management <giveaway_id>")
        return
    
    giveaway_id = context.args[0]
    if giveaway_id not in giveaways:
        await update.message.reply_text(f"❌ Giveaway '{giveaway_id}' not found!")
        return
    
    giveaway = giveaways[giveaway_id]
    status = "🟢 ACTIVE" if not giveaway.get("ended") else "🔴 ENDED"
    
    keyboard = [
        [
            premium_button("ADD VOTES", callback_data=f"addvotes_{giveaway_id}", emoji_id=EMOJI_ADD_VOTES, style=BUTTON_STYLE_PRIMARY),
            premium_button("REMOVE VOTES", callback_data=f"removevotes_{giveaway_id}", emoji_id=EMOJI_REMOVE_VOTES, style=BUTTON_STYLE_DANGER)
        ],
        [
            premium_button("LEADERBOARD", callback_data=f"leaderboard_{giveaway_id}", emoji_id=EMOJI_LEADERBOARD, style=BUTTON_STYLE_PRIMARY)
        ],
        [
            premium_button("END GIVEAWAY", callback_data=f"endgiveaway_{giveaway_id}", emoji_id=EMOJI_END_GIVEAWAY, style=BUTTON_STYLE_DANGER)
        ]
    ]
    
    await update.message.reply_text(
        text=f"<b><tg-emoji emoji-id='{EMOJI_ARROW}'>➡️</tg-emoji> MANAGEMENT PANEL (ADMIN)</b>\n\n"
             f"<b>Giveaway ID:</b> <code>{giveaway_id}</code>\n"
             f"<b>Status:</b> {status}\n"
             f"<b>Channel:</b> {giveaway.get('channel_display', giveaway.get('channel'))}\n"
             f"<b>Creator:</b> {giveaway.get('creator_name', 'Unknown')}\n"
             f"<b>Joined:</b> {len(giveaway.get('users', {}))}\n"
             f"<b>Total Votes:</b> {sum(giveaway.get('vote_counts', {}).values())}",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def add_vote_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/add_vote {giveaway_id} {user_id} {votes}"""
    user_id = update.effective_user.id
    if not is_owner(user_id):
        await update.message.reply_text("❌ You are not the owner!")
        return
    
    if len(context.args) != 3:
        await update.message.reply_text("❌ Usage: /add_vote <giveaway_id> <user_id> <votes>")
        return
    
    giveaway_id = context.args[0]
    try:
        target_uid = int(context.args[1])
    except ValueError:
        await update.message.reply_text("Invalid user ID.")
        return
    try:
        votes = int(context.args[2])
        if votes <= 0: raise ValueError()
    except ValueError:
        await update.message.reply_text("Votes must be a positive integer.")
        return
    
    if giveaway_id not in giveaways:
        await update.message.reply_text(f"❌ Giveaway '{giveaway_id}' not found!")
        return
    
    giveaway = giveaways[giveaway_id]
    if target_uid not in giveaway['users']:
        await update.message.reply_text(f"❌ User {target_uid} not found in this giveaway!")
        return
    
    if giveaway.get('ended'):
        await update.message.reply_text('Ended giveaway votes are locked.')
        return
    old_votes = giveaway['vote_counts'].get(target_uid, 0)
    giveaway['vote_counts'][target_uid] = old_votes + votes
    new_votes = giveaway['vote_counts'][target_uid]
    audit(update.effective_user.id, 'vote_change', giveaway_id, user_id=target_uid, before=old_votes, after=new_votes)
    save_data()
    
    await update_vote_button_in_channel(context, giveaway_id, target_uid, new_votes)
    
    await update.message.reply_text(
        f"✅ <b>Votes Added!</b>\n\n"
        f"<b>Giveaway:</b> <code>{giveaway_id}</code>\n"
        f"<b>User:</b> <code>{target_uid}</code> ({giveaway['users'][target_uid]})\n"
        f"<b>Added:</b> +{votes} votes\n"
        f"<b>New Total:</b> {new_votes} votes",
        parse_mode="HTML"
    )

async def remove_vote_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/remove_vote {giveaway_id} {user_id} {votes}"""
    user_id = update.effective_user.id
    if not is_owner(user_id):
        await update.message.reply_text("❌ You are not the owner!")
        return
    
    if len(context.args) != 3:
        await update.message.reply_text("❌ Usage: /remove_vote <giveaway_id> <user_id> <votes>")
        return
    
    giveaway_id = context.args[0]
    try:
        target_uid = int(context.args[1])
    except ValueError:
        await update.message.reply_text("Invalid user ID.")
        return
    try:
        votes = int(context.args[2])
        if votes <= 0: raise ValueError()
    except ValueError:
        await update.message.reply_text("Votes must be a positive integer.")
        return
    
    if giveaway_id not in giveaways:
        await update.message.reply_text(f"❌ Giveaway '{giveaway_id}' not found!")
        return
    
    giveaway = giveaways[giveaway_id]
    if target_uid not in giveaway['users']:
        await update.message.reply_text(f"❌ User {target_uid} not found in this giveaway!")
        return
    
    if giveaway.get('ended'):
        await update.message.reply_text('Ended giveaway votes are locked.')
        return
    old_votes = giveaway['vote_counts'].get(target_uid, 0)
    giveaway['vote_counts'][target_uid] = max(0, old_votes - votes)
    new_votes = giveaway['vote_counts'][target_uid]
    audit(update.effective_user.id, 'vote_change', giveaway_id, user_id=target_uid, before=old_votes, after=new_votes)
    save_data()
    
    await update_vote_button_in_channel(context, giveaway_id, target_uid, new_votes)
    
    await update.message.reply_text(
        f"✅ <b>Votes Removed!</b>\n\n"
        f"<b>Giveaway:</b> <code>{giveaway_id}</code>\n"
        f"<b>User:</b> <code>{target_uid}</code> ({giveaway['users'][target_uid]})\n"
        f"<b>Removed:</b> -{votes} votes\n"
        f"<b>New Total:</b> {new_votes} votes",
        parse_mode="HTML"
    )

async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_owner(user_id):
        await update.message.reply_text("❌ You are not the owner!")
        return
    
    if not context.args:
        admin_sessions[OWNER_ID] = {"step": "waiting_broadcast"}
        await update.message.reply_text(
            "<b>📢 BROADCAST SYSTEM</b>\n\n"
            "Send your message below.\n\n"
            "<b>Supported HTML Tags:</b>\n"
            "<code>&lt;b&gt;bold&lt;/b&gt;</code>\n"
            "<code>&lt;i&gt;italic&lt;/i&gt;</code>\n"
            "<code>&lt;u&gt;underline&lt;/u&gt;</code>\n"
            "<code>&lt;s&gt;strikethrough&lt;/s&gt;</code>\n"
            "<code>&lt;a href='URL'&gt;link&lt;/a&gt;</code>\n"
            "<code>&lt;tg-emoji emoji-id='ID'&gt;🎁&lt;/tg-emoji&gt;</code>\n\n"
            f"<b>Total Users:</b> <code>{len(all_users)}</code>\n\n"
            "Send /cancel to abort.",
            parse_mode="HTML"
        )
        return
    
    msg = ' '.join(context.args)
    await update.message.reply_text(f"🚀 <b>Broadcast started!</b>\n\nTotal users: <code>{len(all_users)}</code>\nThis may take some time...", parse_mode="HTML")
    
    success = 0
    fail = 0
    for uid in all_users.keys():
        try:
            await context.bot.send_message(chat_id=int(uid), text=msg, parse_mode="HTML", disable_web_page_preview=True, _preserve_smallcaps=True)
            success += 1
        except:
            fail += 1
        await asyncio.sleep(0.05)
    
    await update.message.reply_text(
        f"<b>✅ BROADCAST COMPLETED!</b>\n\n"
        f"<b>✅ Sent:</b> <code>{success}</code>\n"
        f"<b>❌ Failed:</b> <code>{fail}</code>\n"
        f"<b>📊 Total:</b> <code>{len(all_users)}</code>",
        parse_mode="HTML"
    )

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_owner(user_id):
        await update.message.reply_text("❌ You are not the owner!")
        return
    
    active = sum(1 for g in giveaways.values() if not g.get("ended", False))
    participants = sum(len(g.get("users", {})) for g in giveaways.values())
    votes = sum(sum(g.get("vote_counts", {}).values()) for g in giveaways.values())
    
    text = (
        f"<b><tg-emoji emoji-id='{EMOJI_STATS}'>📊</tg-emoji> BOT STATISTICS</b>\n\n"
        f"<b>👥 Users:</b> <code>{len(all_users)}</code>\n"
        f"<b>🎁 Giveaways:</b> <code>{len(giveaways)}</code>\n"
        f"<b>🟢 Active:</b> <code>{active}</code>\n"
        f"<b>📺 Channels:</b> <code>{len(channel_history)}</code>\n"
        f"<b>👤 Participants:</b> <code>{participants}</code>\n"
        f"<b>🗳️ Votes:</b> <code>{votes}</code>"
    )
    await update.message.reply_text(text, parse_mode="HTML")

async def users_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_owner(user_id):
        await update.message.reply_text("❌ You are not the owner!")
        return
    
    users_list = list(all_users.values())[-15:]
    users_list.reverse()
    text = f"<b><tg-emoji emoji-id='{EMOJI_USERS}'>👤</tg-emoji> RECENT USERS</b>\n\n"
    for u in users_list:
        text += f"<b>👤 {u.get('first_name', 'Unknown')}</b>\n   🆔 <code>{u.get('user_id')}</code>\n   📝 @{u.get('username', 'no')}\n   📍 {u.get('source', '?')}\n\n"
    text += f"\n<b>Total Users:</b> <code>{len(all_users)}</code>"
    await update.message.reply_text(text, parse_mode="HTML")

async def channels_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_owner(user_id):
        await update.message.reply_text("❌ You are not the owner!")
        return
    
    text = f"<b><tg-emoji emoji-id='{EMOJI_CHANNEL}'>🔗</tg-emoji> CHANNEL GIVEAWAY HISTORY</b>\n\n"
    
    text += "<b>🟢 ACTIVE GIVEAWAYS</b>\n"
    text += "<code>─────────────────</code>\n"
    active_found = False
    
    for ch_key, ch_data in channel_history.items():
        active_giveaways = [g for g in ch_data.get("giveaways", []) if g.get("status") == "active"]
        if active_giveaways:
            active_found = True
            text += f"\n<b>📢 {ch_data.get('channel_display', 'Unknown')}</b>\n"
            text += f"   🔍 Type: <code>{ch_data.get('type', 'unknown').upper()}</code>\n"
            text += f"   🆔 ID: <code>{ch_data.get('channel_id', 'N/A')}</code>\n"
            text += f"   👤 Owner: {ch_data.get('created_by_name', 'Unknown')}\n"
            for g in active_giveaways:
                text += f"      • ID: <code>{g.get('giveaway_id', 'N/A')}</code>\n"
                text += f"        📅 Created: {g.get('created_at', '')[:10]}\n"
    
    if not active_found:
        text += "<i>No active giveaways</i>\n"
    
    text += "\n<b>🔴 GIVEAWAY HISTORY</b>\n"
    text += "<code>─────────────────</code>\n"
    ended_found = False
    
    for ch_key, ch_data in list(channel_history.items())[-10:]:
        ended_giveaways = [g for g in ch_data.get("giveaways", []) if g.get("status") == "ended"]
        if ended_giveaways:
            ended_found = True
            text += f"\n<b>📢 {ch_data.get('channel_display', 'Unknown')}</b>\n"
            text += f"   🔍 Type: <code>{ch_data.get('type', 'unknown').upper()}</code>\n"
            text += f"   🆔 ID: <code>{ch_data.get('channel_id', 'N/A')}</code>\n"
            text += f"   👤 Owner: {ch_data.get('created_by_name', 'Unknown')}\n"
            text += f"   🎁 Total: <code>{ch_data.get('total_giveaways', 0)}</code> giveaways\n"
    
    if not ended_found:
        text += "<i>No giveaway history yet</i>\n"
    
    await update.message.reply_text(text, parse_mode="HTML")

async def backup_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_owner(user_id):
        await update.message.reply_text("❌ You are not the owner!")
        return
    
    save_data()
    await update.message.reply_text(
        f"<b>✅ BACKUP CREATED!</b>\n\n"
        f"<b>💾 File:</b> <code>{DATA_FILE}</code>\n"
        f"<b>👥 Users:</b> <code>{len(all_users)}</code>\n"
        f"<b>🎁 Giveaways:</b> <code>{len(giveaways)}</code>\n"
        f"<b>📺 Channels:</b> <code>{len(channel_history)}</code>\n\n"
        "<i>Data is automatically saved on every change.</i>",
        parse_mode="HTML"
    )

async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_owner(user_id):
        await update.message.reply_text("❌ You are not the owner!")
        return
    
    await update.message.reply_text(
        f"<b><tg-emoji emoji-id='{EMOJI_SETTINGS}'>⚙️</tg-emoji> SETTINGS</b>\n\n"
        f"<b>Bot Username:</b> @{BOT_USERNAME}\n"
        f"<b>Owner ID:</b> <code>{OWNER_ID}</code>\n"
        f"<b>Data File:</b> <code>{DATA_FILE}</code>\n"
        f"<b>Auto Save:</b> ✅ Enabled\n"
        f"<b>User Tracking:</b> ✅ Enabled\n"
        f"<b>Channel History:</b> ✅ Enabled\n"
        f"<b>Auto Vote Update:</b> ✅ Enabled\n\n"
        "<i>Settings are managed via bot configuration.</i>",
        parse_mode="HTML"
    )

async def testnotify_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_owner(user_id):
        await update.message.reply_text("❌ You are not the owner!")
        return
    
    await send_notification_to_owner(context, "🔔 TEST NOTIFICATION", "This is a test notification from your bot!\n\nAll systems working fine.")
    await update.message.reply_text("✅ Test notification sent to owner!", parse_mode="HTML")

async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_owner(user_id):
        await update.message.reply_text("❌ You are not the owner!")
        return
    
    keyboard = InlineKeyboardMarkup([[
        premium_button("CONFIRM CLEAR", callback_data="confirm_clear", emoji_id=EMOJI_CLEAR, style=BUTTON_STYLE_DANGER),
        premium_button("CANCEL", callback_data="main_menu", emoji_id=EMOJI_CANCEL, style=BUTTON_STYLE_PRIMARY)
    ]])
    
    await update.message.reply_text(
        f"<b><tg-emoji emoji-id='{EMOJI_ALERT}'>⚠️</tg-emoji> DANGER ZONE</b>\n\n"
        f"Are you sure you want to clear ALL data?\n\n"
        f"This will delete:\n"
        f"• <code>{len(all_users)}</code> users\n"
        f"• <code>{len(giveaways)}</code> giveaways\n"
        f"• <code>{len(channel_history)}</code> channel histories\n\n"
        f"<b>This action cannot be undone!</b>",
        parse_mode="HTML",
        reply_markup=keyboard
    )

async def confirm_clear_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    if not is_owner(user_id):
        await query.edit_message_text("❌ You are not the owner!", parse_mode="HTML")
        return
    
    global giveaways, all_users, channel_history, vote_messages, banned_users, suspicious_scores, vote_activity
    giveaways = {}
    all_users = {}
    channel_history = {}
    vote_messages = {}
    banned_users.clear()
    suspicious_scores.clear()
    vote_activity.clear()
    user_sessions.clear()
    admin_sessions.clear()
    for worker in broadcast_tasks.values(): worker.cancel()
    owner_settings.pop("broadcast_jobs", None)
    owner_settings.pop("suspicious_scores", None)
    audit(user_id, "all_data_cleared")
    save_data()
    
    await query.edit_message_text(
        "✅ <b>All data cleared successfully!</b>\n\nBot data has been reset.",
        parse_mode="HTML"
    )

async def process_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != OWNER_ID or admin_sessions.get(OWNER_ID, {}).get("step") != "waiting_broadcast":
        return
    
    if update.message.text == "/cancel":
        del admin_sessions[OWNER_ID]
        await update.message.reply_text("❌ Broadcast cancelled!", parse_mode="HTML")
        return
    
    msg = update.message.text
    await update.message.reply_text(f"🚀 <b>Broadcast started!</b>\n\nTotal users: <code>{len(all_users)}</code>\nThis may take some time...", parse_mode="HTML")
    
    success = 0
    fail = 0
    for uid in all_users.keys():
        try:
            await context.bot.send_message(chat_id=int(uid), text=msg, parse_mode="HTML", disable_web_page_preview=True, _preserve_smallcaps=True)
            success += 1
        except:
            fail += 1
        await asyncio.sleep(0.05)
    
    del admin_sessions[OWNER_ID]
    
    await update.message.reply_text(
        f"<b>✅ BROADCAST COMPLETED!</b>\n\n"
        f"<b>✅ Sent:</b> <code>{success}</code>\n"
        f"<b>❌ Failed:</b> <code>{fail}</code>\n"
        f"<b>📊 Total:</b> <code>{len(all_users)}</code>",
        parse_mode="HTML"
    )


async def ban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Owner-only manual security ban."""
    if not is_owner(update.effective_user.id):
        await update.message.reply_text("❌ You are not the owner!")
        return

    if not context.args:
        await update.message.reply_text("❌ Usage: /ban <user_id> [reason]")
        return

    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID.")
        return

    reason = " ".join(context.args[1:]).strip() or "manual owner ban"
    security_ban_user(target_id, reason)
    await update.message.reply_text(
        f"🚫 <b>User banned.</b>\n\n🆔 <code>{target_id}</code>\n⚠️ {reason}",
        parse_mode="HTML"
    )


async def unban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Owner-only manual security unban."""
    if not is_owner(update.effective_user.id):
        await update.message.reply_text("❌ You are not the owner!")
        return

    if not context.args:
        await update.message.reply_text("❌ Usage: /unban <user_id>")
        return

    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID.")
        return

    banned_users.discard(target_id)
    if str(target_id) in all_users:
        all_users[str(target_id)]["security_banned"] = False
        all_users[str(target_id)]["security_unbanned_at"] = datetime.now().isoformat()
    save_data()

    await update.message.reply_text(
        f"✅ <b>User unbanned.</b>\n\n🆔 <code>{target_id}</code>",
        parse_mode="HTML"
    )


async def security_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        await update.message.reply_text("❌ You are not the owner!")
        return
    active_bans = len(banned_users)
    suspicious = sum(suspicious_scores.values())
    await update.message.reply_text(
        f"<b>🛡 SECURITY STATUS</b>\n\n"
        f"<b>Auto-ban:</b> {'ON' if AUTO_BAN_ON_ABUSE else 'OFF'}\n"
        f"<b>Banned users:</b> <code>{active_bans}</code>\n"
        f"<b>Suspicious score:</b> <code>{suspicious}</code>\n"
        f"<b>Vote window:</b> <code>{VOTE_WINDOW_SECONDS}s</code>\n"
        f"<b>Max votes/window:</b> <code>{MAX_VOTES_IN_WINDOW}</code>",
        parse_mode="HTML"
    )

# ================= MAIN MENU ================= #
async def main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [premium_button("CONNECT", url=f"https://t.me/{BOT_USERNAME}?startchannel=true&admin=post_messages", emoji_id=EMOJI_CONNECT, style=BUTTON_STYLE_SUCCESS)],
        [premium_button("CREATE", callback_data="create_giveaway", emoji_id=EMOJI_CREATE, style=BUTTON_STYLE_PRIMARY),
         premium_button("MANAGE", callback_data="my_giveaways", emoji_id=EMOJI_MANAGE, style=BUTTON_STYLE_PRIMARY)]
    ]
    
    await query.edit_message_text(text="<b>🌐 MAIN MENU</b>", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))

# ================= BUTTON ROUTER ================= #
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    user = query.from_user
    logger.info(f"Button: {data}")
    for prefix in ("manage_", "addvotes_", "removevotes_", "leaderboard_", "endgiveaway_", "confirm_end_"):
        if data.startswith(prefix):
            gid = data[len(prefix):]
            g = giveaways.get(gid)
            if not g or not can_manage(user.id, g):
                await query.answer("Giveaway access denied or expired.", show_alert=True)
                return
            if prefix == "confirm_end_" and g.get("ended"):
                await query.answer("Already ended.", show_alert=True)
                return
    if data == "main_menu":
        context.user_data.pop("extra_input", None)
    if data == "main_menu" and is_owner(user.id):
        context.user_data.pop("owner_input", None)
        context.user_data.pop("owner_broadcast", None)
        context.user_data.pop("vote_giveaway", None)
        context.user_data.pop("vote_action", None)
        admin_sessions.pop(OWNER_ID, None)


    if SECURITY_ENABLED and user and user.id != OWNER_ID:
        if is_security_banned(user.id):
            await query.answer("🚫 You are banned from this bot.", show_alert=True)
            return

        profile_found, profile_reason = check_profile_for_abuse(user)
        if profile_found and AUTO_BAN_ON_PROFILE_ABUSE:
            security_ban_user(user.id, profile_reason)
            await send_notification_to_owner(
                context,
                "🚨 PROFILE SECURITY AUTO-BAN",
                f"👤 {user.full_name or 'Unknown'}\\n"
                f"🔹 Username: @{user.username or 'N/A'}\\n"
                f"🆔 <code>{user.id}</code>\\n"
                f"⚠️ Reason: {profile_reason}"
            )
            await query.answer(
                "🚫 Your name/username contains a banned word. You are banned.",
                show_alert=True
            )
            return

    if data == "confirm_clear":
        await confirm_clear_callback(update, context)
    elif data == "create_giveaway":
        await create_giveaway_flow(update, context)
    elif data == "cancel_creation":
        await cancel_creation(update, context)
    elif data == "my_giveaways":
        await my_giveaways(update, context)
    elif data == "main_menu":
        await main_menu(update, context)
    elif data == "profile":
        await profile_command(update, context)
    elif data.startswith("retry_join_"):
        await retry_join(update, context)
    elif data.startswith("manage_"):
        await manage_giveaway(update, context)
    elif data.startswith("addvotes_"):
        await add_votes_flow(update, context)
    elif data.startswith("removevotes_"):
        await remove_votes_flow(update, context)
    elif data.startswith("leaderboard_"):
        await show_leaderboard(update, context)
    elif data.startswith("endgiveaway_"):
        await end_giveaway(update, context)
    elif data.startswith("confirm_end_"):
        await confirm_end_giveaway(update, context)
    elif data.startswith("join_"):
        await handle_join(update, context)
    elif data.startswith("vote_"):
        await handle_vote(update, context)

async def security_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not SECURITY_ENABLED or not update.effective_user or not update.message:
        return False

    user = update.effective_user
    user_id = user.id

    if user_id == OWNER_ID:
        return False

    if is_security_banned(user_id):
        try:
            await update.message.reply_text("🚫 You are banned from using this bot.")
        except Exception:
            pass
        return True

    profile_found, profile_reason = check_profile_for_abuse(user)
    if profile_found and AUTO_BAN_ON_PROFILE_ABUSE:
        security_ban_user(user_id, profile_reason)
        await send_notification_to_owner(
            context,
            "🚨 PROFILE SECURITY AUTO-BAN",
            f"👤 {user.full_name or 'Unknown'}\\n"
            f"🔹 Username: @{user.username or 'N/A'}\\n"
            f"🆔 <code>{user_id}</code>\\n"
            f"⚠️ Reason: {profile_reason}"
        )
        await update.message.reply_text(
            "🚫 Your name/username contains a banned word. You have been banned."
        )
        return True

    text = update.message.text or ""
    found, reason = contains_banned_content(text)
    if found and AUTO_BAN_ON_ABUSE:
        security_ban_user(user_id, reason)
        await send_notification_to_owner(
            context,
            "🚨 SECURITY AUTO-BAN",
            f"👤 {user.full_name or 'Unknown'}\n"
            f"🆔 <code>{user_id}</code>\n"
            f"⚠️ Reason: {reason}"
        )
        await update.message.reply_text(
            "🚫 Your message contained prohibited content. You have been banned from using this bot."
        )
        return True
    return False


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await security_message_handler(update, context):
        return

    user_id = update.effective_user.id
    if await process_quest_answer(update, context):
        return
    if await extra_input(update, context):
        return
    if await owner_input(update, context):
        return
    
    if not update.message.text:
        return
    if user_id == OWNER_ID and admin_sessions.get(OWNER_ID, {}).get("step") == "waiting_broadcast":
        await process_broadcast(update, context)
        return
    
    if user_id in user_sessions and user_sessions[user_id].get("step") == "waiting_channel":
        await process_channel(update, context)
        return
    
    if "vote_giveaway" in context.user_data:
        await process_vote_change(update, context)
        return


# ================= KD OWNER CONTROL CENTER ================= #
def owner_button(label, action, danger=False):
    return premium_button(label, callback_data="op:" + action,
                          style=BUTTON_STYLE_DANGER if danger else None)

async def owner_render(update, text, rows=None):
    rows = rows or []
    text = small_caps_text(text)
    rows.append([owner_button("OWNER HOME", "home"),
                 premium_button("MAIN MENU", callback_data="main_menu", emoji_id=EMOJI_MAIN_MENU, style=BUTTON_STYLE_PRIMARY)])
    kwargs = dict(text=f"<blockquote><tg-emoji emoji-id='{EMOJI_SETTINGS}'>⚙️</tg-emoji> {text}</blockquote>", parse_mode="HTML",
                  reply_markup=InlineKeyboardMarkup(rows))
    if update.callback_query:
        await update.callback_query.edit_message_text(**kwargs)
    else:
        await update.effective_message.reply_text(**kwargs)

async def owner_view(update, context, action):
    global SECURITY_ENABLED, AUTO_BAN_ON_ABUSE, AUTO_BAN_ON_PROFILE_ABUSE
    if not is_owner(update.effective_user.id):
        if update.callback_query:
            await update.callback_query.answer("Owner access only.", show_alert=True)
        return
    context.user_data.pop("extra_input", None)
    context.user_data.pop("owner_input", None)
    context.user_data.pop("vote_giveaway", None)
    context.user_data.pop("vote_action", None)
    admin_sessions.pop(OWNER_ID, None)
    parts = action.split(":")
    cmd = parts[0]
    if cmd == "home":
        active = sum(not g.get("ended") for g in giveaways.values())
        votes = sum(sum(g.get("vote_counts", {}).values()) for g in giveaways.values())
        text = (f"<b>👑 KD OWNER PANEL</b>\n\nUsers: {len(all_users)}\nActive giveaways: {active}"
                f"\nChannels: {len(channel_history)}\nTotal votes: {votes}\nBanned users: {len(banned_users)}")
        rows = [[owner_button(a,b) for a,b in pair] for pair in [
            [("GIVEAWAYS","giveaways"),("USERS","users:0")],
            [("STATISTICS","stats"),("BROADCAST","input:broadcast")],
            [("CHANNELS","channels:0"),("SECURITY","security")],
            [("BAN USER","input:ban"),("UNBAN USER","input:unban")],
            [("SEARCH USER","input:searchuser"),("SEARCH GIVEAWAY","input:searchgiveaway")],
            [("BACKUP","backup"),("SETTINGS","settings")]]]
        rows.append([extra_button("ADVANCED FEATURES", "home")])
        rows.append([owner_button("DANGER ZONE","danger", True)])
    elif cmd == "giveaways":
        text = "<b>🎁 GIVEAWAY MANAGEMENT</b>"
        rows = [[owner_button("ACTIVE", "list:active:0"),owner_button("ENDED", "list:ended:0")],
                [owner_button("ALL GIVEAWAYS","list:all:0"),owner_button("SEARCH","input:searchgiveaway")]]
    elif cmd in ("list", "users", "channels", "banned", "suspects", "alerts"):
        page = max(0, int(parts[-1]))
        rows = []
        if cmd == "list":
            status = parts[1]
            entries = [(gid,g) for gid,g in giveaways.items() if status == "all" or bool(g.get("ended")) == (status == "ended")]
            text = "<b>🎁 GIVEAWAYS</b>\n"
            for gid,g in entries[page*8:page*8+8]:
                rows.append([owner_button(str(g.get("channel_display",gid))[:40],"g:"+gid)])
            base = "list:"+status
        else:
            base = cmd
            if cmd == "users": entries = list(all_users.items())[::-1]
            elif cmd == "channels": entries = list(channel_history.items())
            elif cmd == "banned": entries = [(str(uid),all_users.get(str(uid),{})) for uid in sorted(banned_users)]
            elif cmd == "suspects": entries = [(str(uid),{"first_name": "Suspicion score: " + str(score)}) for uid,score in sorted(suspicious_scores.items(), key=lambda x:x[1], reverse=True)]
            else: entries = list(enumerate(reversed(security_alerts)))
            text = "<b>"+cmd.upper()+"</b>\n\n"
            for key,value in entries[page*8:page*8+8]:
                if cmd == "channels":
                    text += escape(str(value.get("channel_display",key)))+" | "+escape(str(value.get("channel_id","?")))+"\n"
                elif cmd == "alerts":
                    text += escape(str(value.get("time","")))+" | "+escape(str(value.get("user_id")))+"\n"+escape(str(value.get("reason","")))[:200]+"\n"
                else:
                    rows.append([owner_button(str(value.get("first_name",key))[:35]+" · "+str(key),"u:"+str(key))])
        text += f"\nTotal: {len(entries)} · Page {page+1}"
        nav=[]
        if page: nav.append(owner_button("PREVIOUS",base+":"+str(page-1)))
        if (page+1)*8 < len(entries): nav.append(owner_button("NEXT",base+":"+str(page+1)))
        if nav: rows.append(nav)
    elif cmd == "u":
        uid=parts[1]; u=all_users.get(uid,{})
        text = (f"<b>👤 USER DETAILS</b>\nID: <code>{escape(uid)}</code>\nName: {escape(str(u.get('first_name','Unknown')))}"
                f"\nUsername: @{escape(str(u.get('username') or 'none'))}\nBanned: {int(uid) in banned_users}"
                f"\nReason: {escape(str(u.get('security_ban_reason','—')))}\nVotes given: {u.get('total_votes_given',0)}")
        rows=[[owner_button("BAN","input:ban:"+uid,True),owner_button("UNBAN","input:unban:"+uid)]]
    elif cmd in ("g","participants","leader"):
        gid=parts[1]; g=giveaways.get(gid)
        if not g:
            await owner_render(update,"Giveaway no longer exists."); return
        text=(f"<b>🎁 GIVEAWAY INFO</b>\nID: <code>{escape(gid)}</code>\nChannel: {escape(str(g.get('channel_display',g.get('channel'))))}"
              f"\nCreator: {g.get('creator')}\nStatus: {'ENDED' if g.get('ended') else 'ACTIVE'}"
              f"\nParticipants: {len(g.get('users',{}))}\nVotes: {sum(g.get('vote_counts',{}).values())}")
        rows=[]
        if cmd in ("participants","leader"):
            page=max(0,int(parts[2]) if len(parts)>2 else 0)
            entries=list(g.get("users",{}).items())
            if cmd == "leader": entries.sort(key=lambda item:g.get("vote_counts",{}).get(item[0],0),reverse=True)
            text += "\n\n<b>"+cmd.upper()+"</b>\n"
            for rank,(uid,name) in enumerate(entries[page*10:page*10+10],page*10+1):
                text+=f"{rank}. {escape(str(name))[:70]} · <code>{uid}</code> · {g.get('vote_counts',{}).get(uid,0)} votes\n"
            nav=[]
            if page: nav.append(owner_button("PREVIOUS",f"{cmd}:{gid}:{page-1}"))
            if (page+1)*10<len(entries):nav.append(owner_button("NEXT",f"{cmd}:{gid}:{page+1}"))
            if nav:rows.append(nav)
        rows += [[owner_button("PARTICIPANTS","participants:"+gid+":0"),owner_button("LEADERBOARD","leader:"+gid+":0")],
                 [owner_button("ADD VOTES","input:add:"+gid),owner_button("REMOVE VOTES","input:remove:"+gid,True)]]
        if not g.get("ended"):rows.append([owner_button("END GIVEAWAY","end:"+gid,True)])
        rows.append([extra_button("ADVANCED / PRIZES", "g:"+gid)])
        rows.append([owner_button("GIVEAWAYS","giveaways")])
    elif cmd == "end":
        gid=parts[1]
        if gid not in giveaways or giveaways[gid].get("ended"):
            await owner_render(update,"Giveaway unavailable or already ended.");return
        text="<b>End giveaway?</b>\nWinner will be announced in its channel."
        rows=[[premium_button("CONFIRM END",callback_data="confirm_end_"+gid,emoji_id=EMOJI_CONFIRM,style=BUTTON_STYLE_DANGER),owner_button("CANCEL","g:"+gid)]]
    elif cmd == "input":
        mode=parts[1]; target=parts[2] if len(parts)>2 else None
        context.user_data["owner_input"]={"mode":mode,"target":target}
        prompts={"ban":"Send USER_ID [reason].", "unban":"Send USER_ID.","searchuser":"Send user ID, name or username.",
                 "searchgiveaway":"Send giveaway ID or channel name.","add":"Send USER_ID VOTES (positive integer).",
                 "remove":"Send USER_ID VOTES (positive integer).","broadcast":"Send broadcast text. A preview appears before sending."}
        text="<b>"+mode.upper()+"</b>\n"+prompts[mode]+("\nSelected: "+escape(target) if target else "")
        rows=[[owner_button("CANCEL","home")]]
    elif cmd in ("security","settings","toggle"):
        if cmd == "toggle":
            key=parts[1]
            if key == "security": SECURITY_ENABLED=not SECURITY_ENABLED
            elif key == "autoban": AUTO_BAN_ON_ABUSE=not AUTO_BAN_ON_ABUSE;AUTO_BAN_ON_PROFILE_ABUSE=AUTO_BAN_ON_ABUSE
            owner_settings.update(security=SECURITY_ENABLED,autoban=AUTO_BAN_ON_ABUSE);save_data()
        text=f"<b>🛡 SETTINGS & SECURITY</b>\nBot: @{BOT_USERNAME}\nOwner: {OWNER_ID}\nSecurity: {'ON' if SECURITY_ENABLED else 'OFF'}\nAuto-ban: {'ON' if AUTO_BAN_ON_ABUSE else 'OFF'}\nBanned: {len(banned_users)}\nVote window: {VOTE_WINDOW_SECONDS}s\nMax votes/window: {MAX_VOTES_IN_WINDOW}"
        rows=[[owner_button("TOGGLE SECURITY","toggle:security"),owner_button("TOGGLE AUTO-BAN","toggle:autoban")],
              [owner_button("BANNED USERS","banned:0"),owner_button("SUSPICIOUS VOTERS","suspects:0")],
              [owner_button("RECENT ALERTS","alerts:0")]]
    elif cmd == "stats":
        text=f"<b>📊 STATISTICS</b>\nUsers: {len(all_users)}\nGiveaways: {len(giveaways)}\nActive: {sum(not g.get('ended') for g in giveaways.values())}\nParticipants: {sum(len(g.get('users',{})) for g in giveaways.values())}\nVotes: {sum(sum(g.get('vote_counts',{}).values()) for g in giveaways.values())}\nChannels: {len(channel_history)}\nBanned: {len(banned_users)}"
        rows=[[owner_button("REFRESH","stats")]]
    elif cmd == "backup":
        save_data()
        with open(DATA_FILE,"rb") as backup:
            await context.bot.send_document(chat_id=OWNER_ID, document=backup, filename="KD_vote_backup.json",caption="KD bot data backup")
        text="<b>💾 Backup sent.</b>"; rows=[]
    elif cmd == "danger":
        text="<b>🚨 DANGER ZONE</b>\nClear deletes all users, giveaways and channel history. Download a backup first."
        rows=[[owner_button("BACKUP","backup")],[owner_button("CLEAR ALL DATA","clear",True)]]
    elif cmd == "clear":
        text="<b>Confirm deleting ALL bot data?</b>\nThis cannot be undone."
        rows=[[premium_button("CONFIRM CLEAR",callback_data="confirm_clear",emoji_id=EMOJI_CLEAR,style=BUTTON_STYLE_DANGER),owner_button("CANCEL","home")]]
    else:
        await owner_render(update,"Unknown or expired action.");return
    await owner_render(update,text,rows)

async def owner_input(update, context):
    if not is_owner(update.effective_user.id):return False
    state=context.user_data.get("owner_input")
    if not state:return False
    mode=state["mode"]; target=state.get("target"); value=(update.message.text or "").strip()
    try:
        if mode in ("ban","unban"):
            fields=value.split(maxsplit=1);uid=int(target or fields[0])
            if uid<=0 or uid==OWNER_ID:raise ValueError("Invalid target user ID.")
            if mode=="ban":security_ban_user(uid,value if target else (fields[1] if len(fields)>1 else "manual owner ban"))
            else:
                banned_users.discard(uid)
                all_users.get(str(uid),{})["security_banned"]=False
                suspicious_scores.pop(uid,None);vote_activity.pop(uid,None);save_data()
            context.user_data.pop("owner_input",None)
            await owner_render(update,"<b>"+mode.upper()+" successful.</b>")
        elif mode in ("add","remove"):
            g=giveaways.get(target)
            if not g:raise ValueError("Giveaway no longer exists.")
            if g.get("ended"):raise ValueError("Ended giveaway votes are locked.")
            fields=value.split()
            if len(fields)!=2:raise ValueError("Send USER_ID VOTES.")
            uid,count=map(int,fields)
            if uid not in g.get("users",{}) or count<=0:raise ValueError("Use a participant ID and a positive vote count.")
            old=g["vote_counts"].get(uid,0);g["vote_counts"][uid]=old+count if mode=="add" else max(0,old-count)
            audit(update.effective_user.id,"vote_change",target,user_id=uid,before=old,after=g["vote_counts"][uid])
            save_data();await update_vote_button_in_channel(context,target,uid,g["vote_counts"][uid])
            context.user_data.pop("owner_input",None)
            await owner_render(update,f"Votes updated: {g['vote_counts'][uid]}",[[owner_button("GIVEAWAY","g:"+target)]])
        elif mode in ("searchuser","searchgiveaway"):
            needle=value.lower().lstrip("@");rows=[]
            source=all_users if mode=="searchuser" else giveaways
            for key,item in source.items():
                fields=(key,str(item.get("username","")),str(item.get("first_name",""))) if mode=="searchuser" else (key,str(item.get("channel_display","")),str(item.get("channel","")))
                if any(needle in field.lower() for field in fields):
                    rows.append([owner_button(str(item.get("first_name",item.get("channel_display",key)))[:40],("u:" if mode=="searchuser" else "g:")+key)])
                    if len(rows)==12:break
            context.user_data.pop("owner_input",None)
            await owner_render(update,"<b>SEARCH RESULTS</b>\n"+("First 12 matches." if rows else "No matches."),rows)
        elif mode=="broadcast":
            context.user_data.pop("owner_input",None);context.user_data["owner_broadcast"]=value
            await owner_render(update,"<b>📢 BROADCAST PREVIEW</b>\n"+escape(value[:3000])+f"\n\nRecipients: {len(all_users)}",
                               [[owner_button("CONFIRM SEND","sendbroadcast"),owner_button("CANCEL","cancelbroadcast")]])
    except (ValueError,TypeError) as error:
        await update.message.reply_text(str(error))
    return True

async def owner_callback(update,context):
    query=update.callback_query
    if not is_owner(query.from_user.id):
        await query.answer("Owner access only.",show_alert=True);return
    await query.answer()
    action=query.data[3:]
    if action=="cancelbroadcast":context.user_data.pop("owner_broadcast",None);await owner_view(update,context,"home");return
    if action=="sendbroadcast":
        text=context.user_data.pop("owner_broadcast",None)
        if not text:await owner_render(update,"Preview expired. Create another broadcast.");return
        await owner_render(update,"Broadcast started.")
        success=failed=0
        for uid in list(all_users):
            if int(uid) in banned_users:continue
            try:
                await context.bot.send_message(chat_id=int(uid),text=text,_preserve_smallcaps=True)
                success+=1
            except Exception:failed+=1
            await asyncio.sleep(0.05)
        await context.bot.send_message(chat_id=OWNER_ID,text=f"Broadcast complete. Sent: {success}; failed: {failed}.",reply_markup=InlineKeyboardMarkup([[owner_button("OWNER HOME","home")]]))
        return
    try:await owner_view(update,context,action)
    except (ValueError,IndexError,KeyError):await owner_render(update,"Invalid or expired action.")

async def owner_cancel(update,context):
    if context.user_data.pop("giveaway_quest", None):
        await update.effective_message.reply_text("Quest entry canceled.")
        return
    if is_owner(update.effective_user.id) or staff_role(update.effective_user.id):
        context.user_data.pop("extra_input",None)
        context.user_data.pop("owner_input",None);context.user_data.pop("owner_broadcast",None)
        await extra_view(update,context,"home")


# ================= ADVANCED GIVEAWAY AUTOMATION ================= #
# All times are persisted as Unix UTC seconds; panel inputs use Asia/Kolkata.
# Text/code/link/file prizes are delivered through Telegram. Cash, VPS provisioning,
# subscriptions and physical goods require an external fulfillment provider.
# A crash between Telegram accepting a send and local saving is ambiguous: uncertain
# sends require owner review instead of automatically sending a unique prize twice.
IST = ZoneInfo("Asia/Kolkata")
finish_lock = asyncio.Lock()


def audit(actor, action, giveaway=None, **details):
    events = owner_settings.setdefault("audit", [])
    events.append(dict(time=time.time(), actor=actor, action=action, giveaway=giveaway, **details))
    del events[:-1000]


def staff_role(uid):
    return owner_settings.get("staff", {}).get(str(uid))


def can_manage(uid, g):
    return is_owner(uid) or g.get("creator") == uid or staff_role(uid) == "manager"


def extra_allowed(uid, action):
    if is_owner(uid): return True
    role = staff_role(uid)
    cmd = action.split(":")[0]
    if cmd == "home": return bool(role)
    if role == "viewer": return cmd in ("stats", "audit", "review", "export", "g", "list", "delivery")
    if role == "broadcast": return cmd in ("schedules", "schedulecancel", "input") and (cmd != "input" or action.split(":")[1] == "schedule")
    if role == "manager":
        return cmd in ("list", "g", "demo", "stats", "audit", "review", "export", "delivery", "retry", "confirmretry", "end", "confirmend", "input") and (cmd != "input" or action.split(":")[1] in ("deadline","rules","prize","prizename","quest"))
    return False


def extra_button(label, action):
    return premium_button(label, callback_data="xp:"+action)


async def extra_render(update, text, rows=None):
    rows = list(rows or [])
    text = small_caps_text(text)
    rows.append([extra_button("ADVANCED HOME", "home")])
    if is_owner(update.effective_user.id): rows.append([owner_button("OWNER PANEL", "home")])
    kwargs=dict(text=f"<blockquote><tg-emoji emoji-id='{EMOJI_SETTINGS}'>⚙️</tg-emoji> {text}</blockquote>",parse_mode="HTML",reply_markup=InlineKeyboardMarkup(rows))
    if update.callback_query: await update.callback_query.edit_message_text(**kwargs)
    else: await update.effective_message.reply_text(**kwargs)


def local_time(ts):
    return datetime.fromtimestamp(ts,IST).strftime("%Y-%m-%d %H:%M IST") if ts else "Not set"


def parse_deadline(value):
    parsed=datetime.strptime(value.strip(),"%Y-%m-%d %H:%M").replace(tzinfo=IST).timestamp()
    if parsed <= time.time(): raise ValueError("Choose a future time (IST).")
    return parsed


def select_winners(g, limit=None):
    minimum=g.get("winner_rules",{}).get("minimum",1)
    limit=g.get("winner_rules",{}).get("count",1) if limit is None else limit
    tie=g.get("winner_rules",{}).get("tie","id")
    eligible=[(int(uid),int(votes)) for uid,votes in g.get("vote_counts",{}).items()
              if int(uid) in g.get("users",{}) and votes >= minimum and int(uid) not in banned_users]
    eligible.sort(key=lambda item:(-item[1], item[0]))
    if tie == "random":
        seed=g.get("fair_seed")
        if seed:
            eligible.sort(key=lambda item:(-item[1], hashlib.sha256((seed+":"+str(item[0])).encode()).hexdigest()))
        else:
            by_score=defaultdict(list)
            for row in eligible:by_score[row[1]].append(row)
            eligible=[]
            for score in sorted(by_score,reverse=True):
                group=by_score[score];secrets.SystemRandom().shuffle(group);eligible.extend(group)
    chosen = eligible if limit == 0 else eligible[:limit]
    return [{"user_id":uid,"votes":votes,"rank":rank} for rank,(uid,votes) in enumerate(chosen,1)]


async def report_owner(bot, text):
    try: await bot.send_message(chat_id=OWNER_ID,text=text)
    except Exception: logger.warning("Could not deliver owner notification")


async def notify_claim_candidates(bot, gid):
    g=giveaways.get(gid,{})
    claimed={int(w["user_id"]) for w in g.get("winners",[])}
    for rank,slot in g.get("claim_slots",{}).items():
        if slot.get("status")!="pending" or slot.get("notified") or time.time()<slot.get("notify_after",0):continue
        candidates=slot.get("candidates",[])
        while slot.get("index",0)<len(candidates) and candidates[slot["index"]]["user_id"] in claimed:
            slot["index"]+=1
        if slot.get("index",0)>=len(candidates):
            slot["status"]="unfilled";save_data();continue
        candidate=candidates[slot["index"]]
        keyboard=InlineKeyboardMarkup([[premium_button("CLAIM PRIZE",callback_data=f"claim:{gid}:{rank}:{candidate['user_id']}",emoji_id=EMOJI_GIFT,style=BUTTON_STYLE_SUCCESS)]])
        try:
            await bot.send_message(chat_id=candidate["user_id"],
                text=f"🏆 You placed rank {rank} in giveaway {gid}. Claim within {owner_settings.get('claim_hours',24)} hours. If you do not claim, a backup winner will be invited.",reply_markup=keyboard)
            slot["notified"]=True
        except Exception as error:
            slot["notify_after"]=time.time()+300
            logger.info("Could not notify potential winner: %s",type(error).__name__)
        save_data()


async def send_claim_announcement(bot,g,gid,rank,slot):
    public_state=slot.setdefault("public_announcement",{})
    if public_state.get("status")=="sending":
        public_state["status"]="uncertain";save_data();return
    if public_state.get("status") in ("sent","uncertain"):return
    winner=slot.get("winner",{})
    uid=winner.get("user_id")
    username=escape(str(g.get("users",{}).get(uid,"Winner"))[:100])
    seed=g.get("fair_seed_revealed")
    receipt=(f"\nFair seed: <code>{seed}</code>\nCommit: <code>{g.get('fair_commit')}</code>" if seed else "")
    caption=(f"🎉 <b>WINNER ANNOUNCED</b>\nRank {rank}: <a href='tg://user?id={uid}'>{username}</a> — {winner.get('votes',0)} votes\n"
             f"Prize: {escape(g.get('prize_name','Giveaway prize'))}{receipt}")
    public_state.update(status="sending",caption=caption);save_data()
    try:
        media=owner_settings.get("winner_media")
        sender={"video":bot.send_video,"photo":bot.send_photo,"animation":bot.send_animation}.get(media["kind"]) if media else None
        if sender:
            msg=await sender(chat_id=g["channel_id"],**{media["kind"]:media["file_id"]},caption=caption,parse_mode="HTML")
        else:
            # Purple hologram reveal: animate one channel post, then leave the
            # complete winner announcement in place. A configured owner media
            # file continues to take precedence over this text animation.
            channel_id=g["channel_id"]
            frames=[
                "💜 <b>PURPLE HOLOGRAM</b>\n\n🟣 ▱▱▱▱\n🔮 Initializing winner scan…",
                "💜 <b>PURPLE HOLOGRAM</b>\n\n🟣 ▰▱▱▱\n🔮 Scanning giveaway entries…",
                "💜 <b>PURPLE HOLOGRAM</b>\n\n🟣 ▰▰▰▱\n✨ Winner signal detected…",
                "💜 <b>PURPLE HOLOGRAM WINNER REVEAL</b>\n\n"+caption,
            ]
            msg=await bot.send_message(chat_id=channel_id,parse_mode="HTML",text=frames[0])
            public_state["message_id"]=msg.message_id
            save_data()
            for frame in frames[1:]:
                await asyncio.sleep(0.65)
                await bot.edit_message_text(chat_id=channel_id,message_id=msg.message_id,
                                            parse_mode="HTML",text=frame)
        public_state.update(status="sent",message_id=msg.message_id)
    except Exception as error:
        # Once the first post exists, a partial reveal must be reviewed instead
        # of automatically sending a duplicate announcement.
        uncertain=bool(public_state.get("message_id")) or type(error).__name__ in ("TimedOut","NetworkError")
        public_state.update(status="uncertain" if uncertain else "failed",error=type(error).__name__,retry_at=time.time()+300)
        await report_owner(bot,f"Giveaway {gid} winner announcement needs review: {type(error).__name__}.")
    save_data()


async def process_claim(update,context):
    query=update.callback_query
    try:
        _,gid,rank,uid=query.data.split(":")
        uid=int(uid);g=giveaways.get(gid);slot=g and g.get("claim_slots",{}).get(rank)
        if not g or not slot:await query.answer("This claim is unavailable.",show_alert=True);return
        async with finish_lock:
            candidates=slot.get("candidates",[])
            current=candidates[slot.get("index",0)] if slot.get("index",0)<len(candidates) else None
            if current is None or current["user_id"]!=uid or query.from_user.id!=uid:
                await query.answer("This claim belongs to another user or backup rank.",show_alert=True);return
            if slot.get("status")!="pending" or time.time()>slot.get("deadline",0):
                await query.answer("Claim window expired. The next backup is being notified.",show_alert=True);return
            if any(int(w["user_id"])==uid for w in g.get("winners",[])):
                await query.answer("You already claimed a winner slot.",show_alert=True);return
            winner={"user_id":uid,"votes":current["votes"],"rank":int(rank)}
            slot.update(status="claimed",winner=winner,claimed_at=time.time())
            g.setdefault("winners",[]).append(winner);g["winners"].sort(key=lambda w:w["rank"])
            prize=g.get("prizes",{}).get(rank)
            g.setdefault("deliveries",{})[str(uid)]={"status":"pending" if prize else "missing","prize":prize}
            audit(uid,"winner_claimed",gid,rank=int(rank));save_data()
        await query.answer("Prize claim confirmed!")
        await query.edit_message_text(f"🏆 Claim confirmed for giveaway {gid}, rank {rank}. Your prize will arrive here privately.")
        await send_claim_announcement(context.bot,g,gid,rank,slot)
        await deliver_results(context.bot,gid)
    except (ValueError,KeyError,IndexError):
        await query.answer("Invalid claim link.",show_alert=True)


async def deliver_results(bot, gid, manual_uncertain=False):
    g=giveaways[gid]
    if not g.get("finalized"):return
    announcement=g.setdefault("announcement",{"status":"pending"})
    if announcement.get("status") == "sending":
        announcement["status"]="uncertain";save_data()
    if manual_uncertain and announcement.get("status") == "uncertain":
        announcement["status"]="pending";announcement.pop("retry_at",None)
    if announcement.get("status") in ("pending","failed") and time.time() >= announcement.get("retry_at",0):
        announcement.update(status="sending");save_data()
        lines=["🏆 KD GIVEAWAY ENDED", "Giveaway: "+gid]
        if g.get("prize_name"):lines.append("Prize: "+escape(g["prize_name"]))
        for w in g["winners"]:
            uid=w["user_id"]; name=escape(str(g["users"].get(uid,uid))[:100])
            lines.append(f"{w['rank']}. <a href='tg://user?id={uid}'>{name}</a> — {w['votes']} votes")
        if not g.get("winners") and not any(slot.get("status")=="pending" for slot in g.get("claim_slots",{}).values()):
            lines.append("No eligible winner met the configured rules.")
        elif g.get("claim_slots"):
            lines.append("Potential winners: open your bot messages and claim within the deadline. Backup winners will be invited if a claim expires.")
        else:lines.append("Winners: open the bot privately to receive your saved prize.")
        if g.get("fair_commit"):
            lines.append("Fair draw SHA-256 commitment: <code>"+g["fair_commit"]+"</code>")
            if g.get("fair_seed_revealed"):
                lines.append("Revealed seed: <code>"+g["fair_seed_revealed"]+"</code>")
        try:
            msg=await bot.send_message(chat_id=g["channel_id"],text="\n".join(lines),parse_mode="HTML")
            announcement.update(status="sent",message_id=msg.message_id)
        except Exception as error:
            uncertain = type(error).__name__ in ("TimedOut", "NetworkError")
            announcement.update(status="uncertain" if uncertain else "failed",error=type(error).__name__,retry_at=time.time()+300)
            await report_owner(bot,f"Giveaway {gid}: channel announcement failed ({type(error).__name__}). Check channel permission.")
        save_data()
    for w in g["winners"]:
        delivery=g.setdefault("deliveries",{}).setdefault(str(w["user_id"]),{"status":"pending"})
        if delivery["status"] == "sending":delivery["status"]="uncertain";save_data()
        if manual_uncertain and delivery["status"] == "uncertain":
            delivery["status"]="pending";delivery.pop("retry_at",None)
        prize=delivery.get("prize")
        if not prize:
            delivery["status"]="missing";save_data();continue
        if delivery["status"] not in ("pending","failed") or time.time()<delivery.get("retry_at",0):continue
        delivery["status"]="sending";save_data()
        try:
            if prize["kind"] == "text":
                msg=await bot.send_message(chat_id=w["user_id"],text=f"🏆 KD Giveaway {gid}\nRank: {w['rank']}\nYour prize:\n{prize['value']}",_preserve_smallcaps=True)
            else:
                method={"document":bot.send_document,"photo":bot.send_photo,"video":bot.send_video}[prize["kind"]]
                msg=await method(chat_id=w["user_id"],**{prize["kind"]:prize["value"]},caption=f"🏆 KD giveaway {gid} · Rank {w['rank']}\nYour prize")
            delivery.update(status="sent",message_id=msg.message_id,sent_at=time.time())
            audit("bot","prize_sent",gid,user_id=w["user_id"],rank=w["rank"])
        except Exception as error:
            uncertain = type(error).__name__ in ("TimedOut", "NetworkError")
            delivery.update(status="uncertain" if uncertain else "failed",error=type(error).__name__,retry_at=time.time()+3600)
            await report_owner(bot,f"Giveaway {gid}: prize delivery to {w['user_id']} failed ({type(error).__name__}). User must start/unblock the bot; retry from Delivery Status.")
        save_data()


async def finish_giveaway(bot, gid, actor="scheduler"):
    async with finish_lock:
        g=giveaways.get(gid)
        if not g:return
        if not g.get("finalized"):
            # Older giveaways already ended by a previous version are never redrawn.
            if g.get("ended"):return
            count=g.get("winner_rules",{}).get("count",1)
            ranked=select_winners(g,limit=0)
            g["winners"]=[]
            g.update(ended=True,finalized=True,ended_at=time.time())
            if g.get("fair_seed"):
                g["fair_seed_revealed"]=g["fair_seed"]
            claim_seconds=max(1,int(owner_settings.get("claim_hours",24)))*3600
            slots={}
            reserved=set()
            for rank in range(1,count+1):
                candidates=[w.copy() for w in ranked if w["user_id"] not in reserved]
                if candidates:
                    reserved.add(candidates[0]["user_id"])
                slots[str(rank)]={"candidates":candidates,"index":0,"status":"pending" if candidates else "unfilled",
                                  "deadline":time.time()+claim_seconds,"notified":False}
            g["claim_slots"]=slots
            g["announcement"]={"status":"pending"}
            update_channel_history(g.get("channel"),g.get("channel_display"),g.get("channel_id"),g.get("creator"),g.get("creator_name","Unknown"),"end",gid)
            vote_messages.pop(gid,None)
            audit(actor,"giveaway_finalized",gid,commit=g.get("fair_commit"),winners=[slot["candidates"][0]["user_id"] for slot in slots.values() if slot["candidates"]])
            save_data()
            await notify_claim_candidates(bot,gid)
            await update_progress_card(bot,gid)
            if any(not g.get("prizes",{}).get(rank) for rank,slot in slots.items() if slot["candidates"]):
                await report_owner(bot,f"Giveaway {gid}: save a prize for each rank in Advanced → Giveaway → Save Prize. Winners must claim within {owner_settings.get('claim_hours',24)} hours.")
        await deliver_results(bot,gid)


async def extra_view(update,context,action):
    uid=update.effective_user.id
    if not extra_allowed(uid,action):await extra_render(update,"Access denied.");return
    context.user_data.pop("extra_input",None)
    context.user_data.pop("owner_input",None)
    parts=action.split(":");cmd=parts[0];rows=[]
    if cmd=="home":
        text="<b>👑 KD ADVANCED CONTROL</b>\nRole: "+("owner" if is_owner(uid) else staff_role(uid))
        candidates=[("GIVEAWAYS / PRIZES","list:0"),("EMERGENCY PAUSE / RESUME","pause"),("AUDIT LOGS","audit:0"),
                    ("VOTE REVIEW","review:0"),("STATISTICS","stats"),("SCHEDULED BROADCASTS","schedules:0"),
                    ("ADD SCHEDULE","input:schedule"),("WELCOME EDITOR","welcome"),("START REACTION / ANIMATION","input:startstyle"),
                    ("CO-OWNER ROLES","roles"),("DAILY BACKUP","autobackup"),("WINNER CLAIM HOURS","input:claimhours")]
        rows=[[extra_button(label,a)] for label,a in candidates if extra_allowed(uid,a)]
    elif cmd=="list":
        page=max(0,int(parts[1]));entries=list(giveaways.items())
        text=f"<b>GIVEAWAYS</b>\nPage {page+1}"
        rows=[[extra_button(str(g.get('channel_display',gid))[:35],"g:"+gid)] for gid,g in entries[page*8:page*8+8]]
        if page:rows.append([extra_button("PREVIOUS",f"list:{page-1}")])
        if (page+1)*8<len(entries):rows.append([extra_button("NEXT",f"list:{page+1}")])
    elif cmd=="g":
        gid=parts[1];g=giveaways[gid];rules=g.get("winner_rules",{})
        text=(f"<b>GIVEAWAY AUTOMATION</b>\nID: {escape(gid)}\nEnd: {local_time(g.get('deadline'))}\n"
              f"Minimum votes: {rules.get('minimum',1)}\nWinners: {rules.get('count',1)}\nTie: {rules.get('tie','id')}\n"
              f"Prize label: {escape(g.get('prize_name','Not set'))}\nSaved prize ranks: {', '.join(g.get('prizes',{})) or 'None'}")
        options=[("AUTO-END TIME","input:deadline:"+gid),("WINNER RULES","input:rules:"+gid),
                 ("PRIZE LABEL","input:prizename:"+gid),("SAVE PRIZE","input:prize:"+gid),
                 ("OPTIONAL QUIZ QUEST","input:quest:"+gid),
                 ("DEMO DRAW","demo:"+gid),("DELIVERY STATUS","delivery:"+gid),("EXPORT CSV","export:"+gid)]
        if not g.get("ended"):options.append(("END NOW","end:"+gid))
        rows=[[extra_button(label,a)] for label,a in options if extra_allowed(uid,a)]
    elif cmd=="input":
        mode=parts[1];gid=parts[2] if len(parts)>2 else None
        if gid and gid not in giveaways:raise ValueError("Giveaway not found.")
        if gid and giveaways[gid].get("ended") and mode in ("rules","deadline","prizename"):raise ValueError("Finalized settings are locked.")
        prompts={"deadline":"Send YYYY-MM-DD HH:MM in IST, or OFF to remove auto-end.",
                 "rules":"Send MIN_VOTES WINNER_COUNT TIE_RULE\nExample: 50 1 random\nTie rules: random or id (lower user ID first). Max 20 winners.",
                 "prizename":"Send public prize label, e.g. Powerful VPS. Keep redeem codes in SAVE PRIZE.",
                 "prize":"First send winner rank (1–20). Then send prize text/code/link, document, photo or video. A separate prize is stored for each rank.",
                 "schedule":"Send YYYY-MM-DD HH:MM | message (IST). This saves and schedules the broadcast to all current non-banned users.",
                 "role":"Send USER_ID manager/broadcast/viewer/remove. Only the main owner can manage roles.",
                 "welcometext":"Send welcome text (max 3000 characters), or RESET.",
                 "welcomemedia":"Send photo or video, or RESET.",
                 "welcomephoto":"Send a welcome photo, or RESET.",
                 "welcomevideo":"Send a welcome video, or RESET. It appears with the welcome text on /start.",
                 "welcomebuttons":"Send one Label | https://URL per line (max 6), or RESET.",
                 "winneranimation":"Send photo, video, GIF animation or RESET. It appears in the channel when winners claim.",
                 "startstyle":"Send REACTION | ANIMATION. Example: ❤️ | 🎲\nReactions: ❤️ 🔥 👍 🎉. Animated dice: 🎲 🎯 🎳 🏀 ⚽ 🎰"}
        prompts["quest"]="Send QUESTION | ANSWER to require an optional quiz before entry, or OFF to disable. Answers are case-insensitive; participants get three tries."
        prompts["claimhours"]="Send how many hours winners have to claim their prize (1–168). A backup is invited when the time expires."
        context.user_data["extra_input"]={"mode":mode,"gid":gid,"action":action}
        text="<b>"+mode.upper()+"</b>\n"+prompts[mode]
    elif cmd in ("pause","autobackup"):
        key="paused" if cmd=="pause" else "daily_backup"
        owner_settings[key]=not owner_settings.get(key,False);audit(uid,"toggle_"+key,value=owner_settings[key]);save_data()
        text=key.upper()+": "+("ON" if owner_settings[key] else "OFF")
        if cmd=="pause":text+="\nJoining, voting and automatic endings pause together. Resume processes overdue deadlines."
    elif cmd=="roles":
        text="<b>CO-OWNER ROLES</b>\nmanager: giveaway rules, prizes, end, export\nbroadcast: scheduled broadcasts\nviewer: stats, export, logs (no private prizes)\n\n"
        for target,role in owner_settings.get("staff",{}).items():text+=escape(target)+" · "+escape(role)+"\n"
        rows=[[extra_button("SET / REMOVE ROLE","input:role")]]
    elif cmd=="welcome":
        text="<b>WELCOME EDITOR</b>\nText, media and URL buttons apply on /start."
        rows=[[extra_button("TEXT","input:welcometext"),extra_button("PHOTO","input:welcomephoto")],
              [extra_button("VIDEO","input:welcomevideo"),extra_button("URL BUTTONS","input:welcomebuttons")],
              [extra_button("WINNER ANIMATION","input:winneranimation")]]
    elif cmd in ("audit","review"):
        page=max(0,int(parts[1]));entries=list(reversed(owner_settings.get("audit",[]))) if cmd=="audit" else list(sorted(suspicious_scores.items(),key=lambda x:-x[1]))
        text="<b>"+cmd.upper()+"</b>\n"
        if cmd=="review":text+="Flags show activity patterns, not proof of fake votes.\n"
        for item in entries[page*8:page*8+8]:
            if cmd=="audit":text+=escape(f"{local_time(item['time'])} · {item['actor']} · {item['action']} · {item.get('giveaway') or ''}")+"\n"+escape(str({k:v for k,v in item.items() if k in ('user_id','before','after','rank')}))+"\n"
            else:text+=f"User {item[0]} · suspicion score {item[1]} · banned: {item[0] in banned_users}\n"
        if page:rows.append([extra_button("PREVIOUS",f"{cmd}:{page-1}")])
        if (page+1)*8<len(entries):rows.append([extra_button("NEXT",f"{cmd}:{page+1}")])
    elif cmd=="stats":
        text=f"<b>STATISTICS</b>\nUsers: {len(all_users)}\nGiveaways: {len(giveaways)}\nFinalized: {sum(bool(g.get('finalized')) for g in giveaways.values())}\nPaused: {bool(owner_settings.get('paused'))}"
    elif cmd=="export":
        gid=parts[1];g=giveaways[gid];buf=io.StringIO();writer=csv.writer(buf)
        writer.writerow(["giveaway_id","user_id","name","votes","winner_rank","prize_status"])
        ranks={w["user_id"]:w["rank"] for w in g.get("winners",[])}
        for target,name in g.get("users",{}).items():
            name=str(name)
            if name.startswith(("=","+","-","@","\t","\r")):name="'"+name
            writer.writerow([gid,target,name,g.get("vote_counts",{}).get(target,0),ranks.get(target,""),g.get("deliveries",{}).get(str(target),{}).get("status","")])
        await context.bot.send_document(chat_id=uid,document=io.BytesIO(buf.getvalue().encode("utf-8-sig")),filename=f"giveaway_{gid}.csv")
        audit(uid,"csv_export",gid);save_data();text="CSV export sent."
    elif cmd=="demo":
        gid=parts[1];g=giveaways.get(gid)
        if not g or not can_manage(uid,g):raise ValueError("You cannot preview this giveaway.")
        text=demo_draw_text(gid)
        audit(uid,"demo_draw",gid);save_data()
    elif cmd=="delivery":
        gid=parts[1];g=giveaways[gid];text=f"<b>DELIVERY STATUS</b>\nAnnouncement: {escape(g.get('announcement',{}).get('status','Not finalized'))}\n"
        for rank,slot in g.get("claim_slots",{}).items():
            candidates=slot.get("candidates",[]);index=slot.get("index",0)
            current=candidates[index] if index<len(candidates) else None
            text+=f"Claim rank {rank}: {escape(slot.get('status','pending'))} · "+(f"candidate {current['user_id']} · deadline {local_time(slot.get('deadline'))}" if current else "no backup left")+"\n"
            if slot.get("public_announcement"):
                text+=f"Winner announcement rank {rank}: {escape(slot['public_announcement'].get('status','pending'))}\n"
        for w in g.get("winners",[]):text+=f"Rank {w['rank']} · User {w['user_id']} · {escape(g.get('deliveries',{}).get(str(w['user_id']),{}).get('status','missing'))}\n"
        if extra_allowed(uid,"retry:"+gid):rows=[[extra_button("RETRY FAILED / UNCERTAIN","retry:"+gid)]]
    elif cmd=="retry":
        gid=parts[1];text="Retry failed sends? If a send is marked UNCERTAIN, Telegram may already have delivered it. Confirming can duplicate that prize; check the winner first."
        rows=[[extra_button("CONFIRM RETRY","confirmretry:"+gid)]]
    elif cmd=="confirmretry":
        gid=parts[1]
        async with finish_lock:
            for state in [giveaways[gid].get("announcement",{})]+list(giveaways[gid].get("deliveries",{}).values()):state.pop("retry_at",None)
            audit(uid,"manual_delivery_retry",gid);save_data();await deliver_results(context.bot,gid,manual_uncertain=True)
        text="Retry completed. Check Delivery Status.";rows=[[extra_button("STATUS","delivery:"+gid)]]
    elif cmd in ("end","confirmend"):
        gid=parts[1]
        if cmd=="end":text="End giveaway now and deliver saved prizes?";rows=[[extra_button("CONFIRM END","confirmend:"+gid)]]
        else:await finish_giveaway(context.bot,gid,uid);text="Finalized. Winners announced and prize delivery attempted.";rows=[[extra_button("STATUS","delivery:"+gid)]]
    elif cmd=="schedules":
        page=max(0,int(parts[1]));entries=list(owner_settings.get("broadcast_jobs",{}).items())[::-1]
        text="<b>SCHEDULED BROADCASTS</b>\n"
        for jobid,job in entries[page*8:page*8+8]:
            text+=escape(f"{jobid} · {local_time(job['at'])} · {job['status']} · sent {job.get('sent',0)} / failed {job.get('failed',0)} / uncertain {job.get('uncertain',0)}")+"\n"
            if job["status"]=="pending":rows.append([extra_button("CANCEL "+jobid,"schedulecancel:"+jobid)])
        if page:rows.append([extra_button("PREVIOUS",f"schedules:{page-1}")])
        if (page+1)*8<len(entries):rows.append([extra_button("NEXT",f"schedules:{page+1}")])
    elif cmd=="schedulecancel":
        job=owner_settings.get("broadcast_jobs",{})[parts[1]]
        if job["status"]!="pending":raise ValueError("Only pending schedules can be canceled.")
        job["status"]="canceled";audit(uid,"broadcast_canceled",job_id=parts[1]);save_data();text="Schedule canceled."
    else:raise ValueError("Unknown action.")
    await extra_render(update,text,rows)


async def extra_callback(update,context):
    action=update.callback_query.data[3:]
    if not extra_allowed(update.effective_user.id,action):
        await update.callback_query.answer("Access denied.",show_alert=True);return
    await update.callback_query.answer()
    try:await extra_view(update,context,action)
    except (ValueError,KeyError,IndexError) as error:await extra_render(update,escape(str(error)))


async def extra_input(update,context):
    state=context.user_data.get("extra_input")
    if not state:return False
    uid=update.effective_user.id
    if not extra_allowed(uid,state["action"]):context.user_data.pop("extra_input",None);return True
    msg=update.message;value=(msg.text or "").strip();mode=state["mode"];gid=state.get("gid")
    try:
        g=giveaways.get(gid) if gid else None
        if gid and not g:raise ValueError("Giveaway no longer exists.")
        if g and g.get("ended") and mode in ("rules","deadline","prizename"):raise ValueError("Finalized settings are locked.")
        if mode=="deadline":g["deadline"]=None if value.upper()=="OFF" else parse_deadline(value)
        elif mode=="rules":
            minimum,count,tie=value.split();minimum=int(minimum);count=int(count)
            if minimum<1 or not 1<=count<=20 or tie not in ("random","id"):raise ValueError("Use minimum ≥1, winners 1–20, tie random/id.")
            g["winner_rules"]={"minimum":minimum,"count":count,"tie":tie}
        elif mode=="prizename":
            if not value or len(value)>150:raise ValueError("Prize label must be 1–150 characters.")
            g["prize_name"]=value
        elif mode=="prize":
            if "rank" not in state:
                rank=int(value)
                if not 1<=rank<=20:raise ValueError("Rank must be 1–20.")
                if g.get("finalized") and rank not in [w["rank"] for w in g.get("winners",[])]:raise ValueError("No finalized winner at this rank.")
                if g.get("finalized"):
                    winner=next(w for w in g["winners"] if w["rank"]==rank)
                    status=g.get("deliveries",{}).get(str(winner["user_id"]),{}).get("status")
                    if status in ("sent","uncertain","sending"):raise ValueError("Cannot replace a sent or uncertain prize.")
                state["rank"]=rank
                await msg.reply_text(f"Now send prize for rank {rank}: text/code/link, document, photo or video. Never put private prizes in the public prize label.");return True
            if msg.document:prize={"kind":"document","value":msg.document.file_id}
            elif msg.photo:prize={"kind":"photo","value":msg.photo[-1].file_id}
            elif msg.video:prize={"kind":"video","value":msg.video.file_id}
            elif value and len(value)<=3000:prize={"kind":"text","value":value}
            else:raise ValueError("Send supported media or text up to 3000 characters.")
            rank=state["rank"]
            if g.get("finalized"):
                winner=next(w for w in g["winners"] if w["rank"]==rank)
                existing=g.get("deliveries",{}).get(str(winner["user_id"]),{})
                if existing.get("status") in ("sent","sending","uncertain"):
                    raise ValueError("Cannot replace a sent or uncertain prize.")
            g.setdefault("prizes",{})[str(rank)]=prize
            if g.get("finalized"):
                winner=next(w for w in g["winners"] if w["rank"]==rank)
                g.setdefault("deliveries",{})[str(winner["user_id"])]=dict(status="pending",prize=prize)
        elif mode=="schedule":
            stamp,body=value.split("|",1);body=body.strip()
            if not body or len(body)>4000:raise ValueError("Broadcast text must be 1–4000 characters.")
            jobid=secrets.token_hex(4)
            owner_settings.setdefault("broadcast_jobs",{})[jobid]={"at":parse_deadline(stamp),"text":body,"status":"pending","actor":uid,"results":{},"sent":0,"failed":0,"uncertain":0}
        elif mode=="role":
            target,role=value.split();target=int(target)
            if target<=0 or target==OWNER_ID or role not in ("manager","broadcast","viewer","remove"):raise ValueError("Invalid role or ID.")
            staff=owner_settings.setdefault("staff",{})
            if role=="remove":staff.pop(str(target),None)
            else:staff[str(target)]=role
        elif mode=="welcometext":
            if value.upper()=="RESET":owner_settings.pop("welcome_text",None)
            elif value and len(value)<=3000:owner_settings["welcome_text"]=value
            else:raise ValueError("Send 1–3000 characters.")
        elif mode in ("welcomemedia","welcomephoto"):
            if value.upper()=="RESET":
                owner_settings.pop("welcome_media",None)
                owner_settings.pop("welcome_video",None)
            elif msg.photo:
                owner_settings["welcome_media"]={"kind":"photo","file_id":msg.photo[-1].file_id}
                owner_settings.pop("welcome_video",None)
            elif mode=="welcomemedia" and msg.video:
                owner_settings["welcome_media"]={"kind":"video","file_id":msg.video.file_id}
                owner_settings.pop("welcome_video",None)
            else:raise ValueError("Send a photo or RESET.")
        elif mode=="welcomevideo":
            if value.upper()=="RESET":owner_settings.pop("welcome_video",None)
            elif msg.video:
                owner_settings["welcome_video"]={"kind":"video","file_id":msg.video.file_id}
                owner_settings.pop("welcome_media",None)
            else:raise ValueError("Send a Telegram video or RESET.")
        elif mode=="welcomebuttons":
            buttons=[]
            if value.upper()!="RESET":
                for line in value.splitlines():
                    label,url=map(str.strip,line.split("|",1))
                    if not label or len(label)>40 or not re.match(r'^https://[^\s]+$',url):raise ValueError("Use Label | https://URL.")
                    buttons.append(dict(label=label,url=url))
                if len(buttons)>6:raise ValueError("Maximum 6 buttons.")
            owner_settings["welcome_buttons"]=buttons
        elif mode=="startstyle":
            reaction,animation=map(str.strip,value.split("|",1))
            if reaction not in ("❤️","🔥","👍","🎉") or animation not in ("🎲","🎯","🎳","🏀","⚽","🎰"):
                raise ValueError("Choose a listed reaction and Telegram animated emoji.")
            owner_settings["start_reaction"]=reaction
            owner_settings["start_animation"]=animation
        elif mode=="quest":
            if value.upper()=="OFF":g.pop("quest",None)
            else:
                question,answer=map(str.strip,value.split("|",1))
                if not question or not answer or len(question)>300 or len(answer)>120:raise ValueError("Quest question max 300 chars; answer max 120.")
                g["quest"]={"question":question,"answer_hash":hashlib.sha256(answer.casefold().encode()).hexdigest()}
        elif mode=="claimhours":
            hours=int(value)
            if not 1<=hours<=168:raise ValueError("Choose 1–168 hours.")
            owner_settings["claim_hours"]=hours
        elif mode=="winneranimation":
            if value.upper()=="RESET":owner_settings.pop("winner_media",None)
            elif msg.animation:owner_settings["winner_media"]={"kind":"animation","file_id":msg.animation.file_id}
            elif msg.photo:owner_settings["winner_media"]={"kind":"photo","file_id":msg.photo[-1].file_id}
            elif msg.video:owner_settings["winner_media"]={"kind":"video","file_id":msg.video.file_id}
            else:raise ValueError("Send a photo, video, GIF animation or RESET.")
        audit(uid,"set_"+mode,gid);save_data();context.user_data.pop("extra_input",None)
        await extra_render(update,"Saved."+ (" Prize delivery runs automatically for finalized winners." if mode=="prize" else ""),[[extra_button("GIVEAWAY","g:"+gid)]] if gid else None)
    except (ValueError,TypeError,KeyError,StopIteration):
        await msg.reply_text("Invalid input or locked prize/settings. Follow the format shown above; /cancel to exit.")
    return True


async def run_broadcast_job(bot,jobid,job):
    if job["status"]=="pending":
        job.update(status="running",recipients=[uid for uid in all_users if int(uid) not in banned_users]);save_data()
    for uid in job.get("recipients",[]):
        old=job.setdefault("results",{}).get(uid)
        if old=="sending":job["results"][uid]="uncertain";job["uncertain"]+=1;save_data();continue
        if old:continue
        if int(uid) in banned_users:job["results"][uid]="skipped";save_data();continue
        job["results"][uid]="sending";save_data()
        try:await bot.send_message(chat_id=int(uid),text=job["text"],_preserve_smallcaps=True);job["results"][uid]="sent";job["sent"]+=1
        except Exception as error:
            if type(error).__name__ in ("TimedOut", "NetworkError"):
                job["results"][uid]="uncertain";job["uncertain"]+=1
            else:job["results"][uid]="failed";job["failed"]+=1
        save_data();await asyncio.sleep(.05)
    job["status"]="done";audit("scheduler","broadcast_completed",job_id=jobid);save_data()
    await report_owner(bot,f"Scheduled broadcast {jobid} complete: sent {job['sent']}, failed {job['failed']}, uncertain {job['uncertain']}.")


broadcast_tasks = {}


async def send_due_giveaway_reminders(bot, gid, g, now):
    deadline = g.get("deadline")
    if not deadline or g.get("ended"):
        return
    remaining = float(deadline) - now
    reminders = g.setdefault("reminders", {})
    for key, lead_seconds, label in (("24h", 86400, "about 24 hours"), ("1h", 3600, "about 1 hour")):
        if remaining <= 0 or remaining > lead_seconds:
            continue
        if key == "24h" and remaining <= 3600:
            continue
        state = reminders.get(key, {})
        if state.get("status") in ("sent", "sending", "uncertain"):
            continue
        if now < state.get("retry_at", 0):
            continue
        reminders[key] = {"status": "sending", "started_at": now}
        save_data()
        try:
            msg = await bot.send_message(
                chat_id=g["channel_id"],
                text=(f"⏰ <b>GIVEAWAY ENDING SOON</b>\n\n"
                      f"This giveaway ends in {label}. Join or cast your votes now:\n"
                      f"https://t.me/{BOT_USERNAME}?start={gid}"),
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
            reminders[key] = {"status": "sent", "message_id": msg.message_id, "sent_at": time.time()}
        except Exception as error:
            uncertain = type(error).__name__ in ("TimedOut", "NetworkError")
            reminders[key] = {
                "status": "uncertain" if uncertain else "failed",
                "error": type(error).__name__,
                "retry_at": time.time() + 300,
            }
            logger.warning("Giveaway %s %s reminder failed: %s", gid, key, type(error).__name__)
        save_data()


async def background_tick(bot):
    now=time.time()
    heartbeat = owner_settings.get("last_heartbeat_at")
    if not heartbeat or now - float(heartbeat) >= 60:
        owner_settings["last_heartbeat_at"] = now
        save_data()
    for gid,g in list(giveaways.items()):
        if not owner_settings.get("paused") and not g.get("ended") and g.get("deadline") and now>=g["deadline"]:
            await finish_giveaway(bot,gid)
        elif not owner_settings.get("paused") and not g.get("ended") and g.get("deadline"):
            await send_due_giveaway_reminders(bot, gid, g, now)
        elif g.get("finalized"):
            async with finish_lock:
                for rank,slot in g.get("claim_slots",{}).items():
                    public_state=slot.get("public_announcement",{})
                    if public_state.get("status")=="sending":public_state["status"]="uncertain";save_data()
                    elif public_state.get("status")=="failed" and now>=public_state.get("retry_at",0):
                        public_state["status"]="pending";await send_claim_announcement(bot,g,gid,rank,slot)
                    if slot.get("status")!="pending":continue
                    candidates=slot.get("candidates",[])
                    index=slot.get("index",0)
                    already_claimed={int(w["user_id"]) for w in g.get("winners",[])}
                    while index<len(candidates) and candidates[index]["user_id"] in already_claimed:index+=1
                    slot["index"]=index
                    if index>=len(candidates):slot["status"]="unfilled";save_data();continue
                    if now>=slot.get("deadline",0):
                        audit("scheduler","claim_expired",gid,rank=int(rank),user_id=candidates[index]["user_id"])
                        slot["index"]=index+1;slot["notified"]=False
                        slot["deadline"]=now+max(1,int(owner_settings.get("claim_hours",24)))*3600
                        save_data()
                await notify_claim_candidates(bot,gid)
                await deliver_results(bot,gid)
    for jobid,job in list(owner_settings.get("broadcast_jobs",{}).items()):
        if job["status"]=="running" or (job["status"]=="pending" and now>=job["at"]):
            task = broadcast_tasks.get(jobid)
            if task is None or task.done():
                if task is not None:
                    try: task.result()
                    except Exception: logger.exception("Scheduled broadcast worker failed")
                broadcast_tasks[jobid] = asyncio.create_task(run_broadcast_job(bot, jobid, job))
    if owner_settings.get("daily_backup") and now>=owner_settings.get("next_backup",0):
        save_data()
        try:
            with open(DATA_FILE,"rb") as backup:await bot.send_document(chat_id=OWNER_ID,document=backup,filename="KD_daily_backup.json")
            owner_settings["next_backup"]=time.time()+86400;audit("scheduler","daily_backup");save_data()
        except Exception:
            owner_settings["next_backup"]=time.time()+600;save_data()


async def background_loop(application):
    while True:
        try:await background_tick(application.bot)
        except asyncio.CancelledError:raise
        except Exception:logger.exception("Automation tick failed")
        await asyncio.sleep(15)


async def recover_persisted_work(bot):
    """Resume saved deadlines/jobs and protect interrupted sends from duplicates."""
    recovered = 0
    now = time.time()
    last_heartbeat = owner_settings.get("last_heartbeat_at")
    downtime = max(0, now - float(last_heartbeat)) if last_heartbeat else 0
    if downtime > 0:
        for g in giveaways.values():
            if not g.get("ended") and g.get("deadline"):
                g["deadline"] = float(g["deadline"]) + downtime
            if g.get("finalized"):
                for slot in g.get("claim_slots", {}).values():
                    if slot.get("status") == "pending" and slot.get("deadline"):
                        slot["deadline"] = float(slot["deadline"]) + downtime
        recovered += 1
    heartbeat_needs_save = not last_heartbeat or downtime > 0
    owner_settings["last_heartbeat_at"] = now

    for g in giveaways.values():
        if not g.get("finalized"):
            for reminder in g.get("reminders", {}).values():
                if reminder.get("status") == "sending":
                    reminder["status"] = "uncertain"
                    recovered += 1
            continue
        announcement = g.get("announcement", {})
        if announcement.get("status") == "sending":
            announcement["status"] = "uncertain"
            recovered += 1
        for delivery in g.get("deliveries", {}).values():
            if delivery.get("status") == "sending":
                delivery["status"] = "uncertain"
                recovered += 1
        for slot in g.get("claim_slots", {}).values():
            public = slot.get("public_announcement", {})
            if public.get("status") == "sending":
                public["status"] = "uncertain"
                recovered += 1

    if recovered or heartbeat_needs_save:
        save_data()
        logger.info("Restart recovery extended deadlines by %.0f seconds and repaired %s saved state item(s)", downtime, recovered)

    # Processes overdue giveaways, expired claims, and due/running broadcasts
    # immediately; the regular loop then keeps checking every 15 seconds.
    await background_tick(bot)


async def background_start(application):
    try:
        await recover_persisted_work(application.bot)
    except Exception:
        logger.exception("Could not fully recover persisted giveaway work; periodic recovery will continue")
    application.bot_data["automation_task"]=asyncio.create_task(background_loop(application))


async def background_stop(application):
    task=application.bot_data.pop("automation_task",None)
    if task:
        task.cancel()
        try:await task
        except asyncio.CancelledError:pass
    for worker in broadcast_tasks.values(): worker.cancel()
    if broadcast_tasks:
        await asyncio.gather(*broadcast_tasks.values(), return_exceptions=True)
    broadcast_tasks.clear()
    owner_settings["last_heartbeat_at"] = time.time()
    save_data()


def main():
    if not TOKEN:
        raise SystemExit("BOT_TOKEN is missing. Set it in the environment before starting the bot.")
    app = Application.builder().token(TOKEN).request(request).post_init(background_start).post_stop(background_stop).build()
    
    # User commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("profile", profile_command))
    app.add_handler(CommandHandler("demo", demo_command))
    
    # Admin commands
    app.add_handler(CommandHandler(["admin", "owner"], admin_command))
    app.add_handler(CommandHandler("cancel", owner_cancel))
    app.add_handler(CommandHandler("broadcast", broadcast_command))
    app.add_handler(CommandHandler("bc", bc_command))
    app.add_handler(CommandHandler("ball", ball_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("users", users_command))
    app.add_handler(CommandHandler("channels", channels_command))
    app.add_handler(CommandHandler("backup", backup_command))
    app.add_handler(CommandHandler("settings", settings_command))
    app.add_handler(CommandHandler("security", security_command))
    app.add_handler(CommandHandler("ban", ban_command))
    app.add_handler(CommandHandler("unban", unban_command))
    app.add_handler(CommandHandler("testnotify", testnotify_command))
    app.add_handler(CommandHandler("clear", clear_command))
    app.add_handler(CommandHandler("g_management", g_management_command))
    app.add_handler(CommandHandler("add_vote", add_vote_command))
    app.add_handler(CommandHandler("remove_vote", remove_vote_command))
    
    app.add_handler(CallbackQueryHandler(process_claim, pattern=r"^claim:"))
    app.add_handler(CallbackQueryHandler(extra_callback, pattern=r"^xp:"))
    app.add_handler(CallbackQueryHandler(owner_callback, pattern=r"^op:"))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler((filters.TEXT | filters.PHOTO | filters.VIDEO | filters.ANIMATION | filters.Document.ALL) & ~filters.COMMAND, handle_message))
    
    print("=" * 60)
    print("🤖 PREMIUM VOTE-GIVEAWAY BOT IS ACTIVE!")
    print(f"📌 Bot Username: @{BOT_USERNAME}")
    print(f"👑 Owner ID: {OWNER_ID}")
    print(f"💾 Data File: {DATA_FILE}")
    print("=" * 60)
    print("\n✅ ADMIN COMMANDS:")
    print("   /admin - Show all admin commands")
    print("   /broadcast <msg> - Send to all users")
    print("   /bc <msg> - Send to all channels")
    print("   /ball <msg> - Send to all users + all channels")
    print("   /stats - Bot statistics")
    print("   /users - Recent users list")
    print("   /channels - Channel history")
    print("   /backup - Manual backup")
    print("   /settings - Bot settings")
    print("   /security - Security status")
    print("   /ban <user_id> [reason] - Manual ban")
    print("   /unban <user_id> - Remove security ban")
    print("   /testnotify - Test notification")
    print("   /clear - Delete all data")
    print("   /g_management <id> - Open giveaway panel")
    print("   /add_vote <id> <user_id> <votes> - Add votes")
    print("   /remove_vote <id> <user_id> <votes> - Remove votes")
    print("   /demo <giveaway_id> - Preview a draw without ending the giveaway")
    print("=" * 60)
    print("\n✅ CHANNEL MEMBERSHIP SYSTEM ADDED:")
    print("   • Checks if user is a channel member before joining")
    print("   • Shows JOIN CHANNEL button if not a member")
    print("   • Shows TRY AGAIN button to re-check membership")
    print("=" * 60)
    
    app.run_polling(allowed_updates=["message", "callback_query"])

if __name__ == "__main__":
    main()
