import os
import sys
import gc
import sqlite3
import logging
import asyncio
from datetime import datetime
from collections import defaultdict

try:
    import uvloop
    uvloop.install()
    print("🚀 UVLOOP ACTIVATED")
except ImportError:
    pass

from pyrogram import Client, filters, enums
from pyrogram.errors import (
    FloodWait, InputUserDeactivated, PeerIdInvalid,
    UserIsBlocked, ChannelInvalid
)
from pyrogram.types import (
    InputMediaPhoto, InputMediaVideo,
    InputMediaDocument, InputMediaAudio,
    BotCommand, BotCommandScopeDefault, BotCommandScopeChat,
    InlineKeyboardMarkup, InlineKeyboardButton
)

from config import *
from database import (
    setup_database, add_approved_user, remove_approved_user,
    is_authorized, update_user_activity, get_user_details,
    get_all_approved_users, get_active_users_for_broadcast,
    set_user_vip_status, set_user_admin_status, get_vip_users_count,
    ban_user_permanent, unban_user_permanent, is_user_banned,
    get_banned_users_count, get_all_banned_users,
    get_users_to_warn_71h, get_users_to_notify_72h,
    add_media_to_history, get_media_stats,
    save_message_mapping, get_message_id_for_user,
    increment_inactivity_warning,
    is_duplicate_media,
    increment_user_duplicate_count,
    get_user_duplicate_count,
    get_top_duplicate_users,
    search_users_by_name,
    add_pending_approval, is_pending_approval, remove_pending_approval,
    get_all_pending_approvals,
    mark_user_72h_notified,
    get_user_media_stats,
    get_all_broadcast_recipients,
    get_inactive_users_3days,
    get_manual_approval_mode, set_manual_approval_mode,
    get_protect_content, set_protect_content,
    get_rules_photo_file_id, set_rules_photo_file_id,
    get_rules_text, set_rules_text,
    get_start_photo_file_id, set_start_photo_file_id,
    get_start_text, set_start_text,
    get_auth_group, set_auth_group, del_auth_group,
    get_sync_channel, set_sync_channel, del_sync_channel,
    get_capacity_limit, set_capacity_limit, get_regular_users_count
)


from utils import *
from shared_registry import registry_check, registry_register, registry_unregister

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)

logger = logging.getLogger(__name__)
for name in ["pyrogram", "pyrogram.client", "pyrogram.network", "pyrogram.session", "pyrogram.connection", "pyrogram.dispatcher"]:
    logging.getLogger(name).setLevel(logging.WARNING)

bot = Client(
    "bot_broadcast",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workdir="data"
)

broadcast_queue = asyncio.Queue()
_semaphore = asyncio.Semaphore(MAX_CONCURRENT)
_flood_gate = asyncio.Event()
_flood_gate.set()
_media_groups = {}
_user_buffers = {}
duplicate_notifications = defaultdict(lambda: {"count": 0, "timer": None})

# Runtime settings (loaded from DB at startup, toggled via /toggleforward)
PROTECT_CONTENT = True

# ============================================================================
# MENU COMMANDS
# ============================================================================
USER_COMMANDS = [
    BotCommand("start", "Iniciar bot y registrarse"),
    BotCommand("rules", "Ver las reglas del grupo"),
    BotCommand("me", "Ver tu información"),
    BotCommand("report", "Reportar usuario (responder al mensaje)"),
    BotCommand("renv", "Reenviar media/álbum a ti (VIP/Admin)"),
]

ADMIN_COMMANDS = [
    BotCommand("start", "Iniciar bot y registrarse"),
    BotCommand("rules", "Ver las reglas del grupo"),
    BotCommand("me", "Ver tu información"),
    BotCommand("stats", "[ADMIN] Estadísticas completas del bot"),
    BotCommand("addadmin", "[ADMIN] Promover usuario a admin"),
    BotCommand("removeadmin", "[ADMIN] Quitar privilegios de admin"),
    BotCommand("vip", "[ADMIN] Dar estado VIP"),
    BotCommand("unvip", "[ADMIN] Quitar estado VIP"),
    BotCommand("ban", "[ADMIN] Banear usuario permanentemente"),
    BotCommand("unban", "[ADMIN] Quitar ban de un usuario"),
    BotCommand("list_users", "[ADMIN] Listar usuarios aprobados"),
    BotCommand("showuser", "[ADMIN] Ver información detallada del usuario"),
    BotCommand("whois", "[ADMIN] Buscar usuarios por nombre o @usuario"),
    BotCommand("dupes_stats", "[ADMIN] Usuarios con más duplicados bloqueados"),
    BotCommand("listban", "[ADMIN] Listar usuarios baneados"),
    BotCommand("approve", "[ADMIN] Activar/desactivar modo aprobación manual"),
    BotCommand("toggleforward", "[ADMIN] Activar/desactivar reenvío"),
    BotCommand("setrules", "[ADMIN] Definir foto/texto de /rules"),
    BotCommand("setstart", "[ADMIN] Definir foto/texto de /start"),
    BotCommand("listap", "[ADMIN] Usuarios pendientes de aprobación"),
    BotCommand("pending", "[ADMIN] Usuarios pendientes de aprobación"),
    BotCommand("a", "[ADMIN] Aprobar usuario pendiente"),
    BotCommand("d", "[ADMIN] Rechazar usuario pendiente"),
    BotCommand("fix", "[ADMIN] Enviar y fijar mensaje para todos"),
    BotCommand("unfix", "[ADMIN] Desfijar mensajes de todos los chats"),
    BotCommand("erase", "[ADMIN] Eliminar mensaje del broadcast para todos"),
    BotCommand("scan", "[ADMIN] Escanear usuarios inactivos (3+ días)"),
    BotCommand("report", "[ADMIN] Reportar usuario (responder al mensaje)"),
    BotCommand("renv", "Reenviar media/álbum a ti (responder)"),
    BotCommand("setauthgroup", "[ADMIN] Restringir bot a un Grupo/Canal oficial"),
    BotCommand("delauthgroup", "[ADMIN] Quitar restricción de Grupo/Canal oficial"),
    BotCommand("setcapacity", "[ADMIN] Limitar número máximo de usuarios"),
    BotCommand("setforward", "[ADMIN] Definir canal para encaminhar broadcasts"),
    BotCommand("delforward", "[ADMIN] Parar de encaminhar broadcasts"),
]

# ============================================================================
# DYNAMIC MENU FUNCTIONS - BotCommandScopeChat
# ============================================================================
async def set_admin_menu(user_id: int):
    """Set ADMIN menu for a specific user in DM"""
    try:
        await bot.set_bot_commands(
            commands=ADMIN_COMMANDS,
            scope=BotCommandScopeChat(chat_id=user_id)
        )
        logger.info(f"✅ Admin menu set for user {user_id} (25 commands)")
        return True
    except Exception as e:
        logger.warning(f"⚠️ Could not set admin menu for {user_id}: {e}")
        return False

async def set_user_menu(user_id: int):
    """Set USER menu for a specific user (fallback)"""
    try:
        await bot.set_bot_commands(
            commands=USER_COMMANDS,
            scope=BotCommandScopeChat(chat_id=user_id)
        )
        logger.info(f"✅ User menu set for user {user_id} (4 commands)")
        return True
    except Exception as e:
        logger.warning(f"⚠️ Could not set user menu for {user_id}: {e}")
        return False

async def setup_bot_commands():
    """Set only default menu on startup"""
    try:
        await bot.set_bot_commands(
            commands=USER_COMMANDS,
            scope=BotCommandScopeDefault()
        )
        logger.info("✅ Default menu set: 6 commands for ALL USERS")
        logger.info("📋 Individual menus will be set when users send /start")
    except Exception as e:
        logger.error(f"❌ Error setting default menu: {e}")

# ============================================================================
# DUPLICATE NOTIFICATIONS
# ============================================================================
async def send_duplicate_notification(user_id: int):
    global duplicate_notifications
    if user_id not in duplicate_notifications:
        return
    
    count = duplicate_notifications[user_id]["count"]
    if count > 0:
        try:
            total = await get_user_duplicate_count(user_id)
            if count == 1:
                msg = (
                    "⚠️ **Contenido duplicado detectado**\n\n"
                    "Enviaste **1 archivo** que ya habías enviado antes.\n\n"
                    "📌 **Consejo:** Evita reenviar el mismo contenido para mantener la comunidad fresca.\n\n"
                    "🔄 Tu duplicado fue eliminado automáticamente."
                )
            else:
                msg = (
                    f"⚠️ **Contenido duplicado detectado**\n\n"
                    f"Enviaste **{count} archivos** que ya habías enviado antes.\n\n"
                    f"📌 **Consejo:** Evita reenviar el mismo contenido para mantener la comunidad fresca.\n\n"
                    f"🔄 Tus duplicados fueron eliminados automáticamente."
                )
            details = await get_user_details(user_id)
            protect = PROTECT_CONTENT and not (details and (details.get('is_admin') or details.get('is_vip')))
            await bot.send_message(user_id, msg, protect_content=protect)
            logger.info(f"📨 Sent duplicate notification to user {user_id}: {count} items")
        except Exception as e:
            logger.error(f"Error sending duplicate notification to {user_id}: {e}")
        finally:
            del duplicate_notifications[user_id]

def schedule_duplicate_notification(user_id: int):
    global duplicate_notifications
    loop = asyncio.get_running_loop()
    
    duplicate_notifications[user_id]["count"] += 1
    
    if duplicate_notifications[user_id]["timer"]:
        duplicate_notifications[user_id]["timer"].cancel()
    
    duplicate_notifications[user_id]["timer"] = loop.call_later(
        3.0,
        lambda: asyncio.create_task(send_duplicate_notification(user_id))
    )
    logger.info(f"📊 User {user_id} duplicate count: {duplicate_notifications[user_id]['count']} (buffered)")

# ============================================================================
# BROADCAST WORKER
# ============================================================================
async def _broadcast_task_worker():
    """Broadcast worker with clickable reply support"""
    logger.info("🚀 Broadcast Worker Started")
    
    while True:
        try:
            task_data = await broadcast_queue.get()
            msgs = task_data['msgs']
            original_msg = msgs[0]
            sender_id = original_msg.from_user.id
            original_msg_id = original_msg.id
            
            users = await get_active_users_for_broadcast()
            
            sync_channel = get_sync_channel()
            # Fallback to .env variable if dynamic sync channel is not set
            if not sync_channel and SYNC_CHANNEL_ID != 0:
                sync_channel = SYNC_CHANNEL_ID
                
            if sync_channel and sync_channel not in users:
                users.append(sync_channel)
                
            if not users:
                broadcast_queue.task_done()
                continue
            
            # Admins and VIPs can forward; regular users cannot
            all_approved = await get_all_approved_users()
            can_forward_ids = {u['user_id'] for u in all_approved if u.get('is_admin') or u.get('is_vip')}
            
            sender = original_msg.from_user
            sender_details = await get_user_details(sender.id)
            is_vip = sender_details['is_vip'] if sender_details else False
            is_admin = sender_details['is_admin'] if sender_details else False
            sender_info = await get_sender_info(sender, is_vip, is_admin)
            
            media_list = []
            text_content = None
            
            # DETECT REPLY
            reply_to_original_msg_id = None
            reply_to_sender_id = None
            
            if original_msg.reply_to_message and original_msg.reply_to_message.from_user:
                replied_to_msg_id = original_msg.reply_to_message.id
                reply_to_sender_id = original_msg.reply_to_message.from_user.id
                
                conn = sqlite3.connect(DB_FILE)
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT original_sender_id, original_message_id
                    FROM message_mapping
                    WHERE broadcast_message_id = ? AND target_user_id = ?
                """, (replied_to_msg_id, sender_id))
                result = cursor.fetchone()
                conn.close()
                
                if result:
                    reply_to_sender_id, reply_to_original_msg_id = result
                    logger.info(f"📌 REPLY: {sender_id} replying to msg {reply_to_original_msg_id} from {reply_to_sender_id}")
            
            # ALBUM
            full_caption = ""
            if len(msgs) > 1 or msgs[0].media_group_id:
                base_caption = f"{sender_info}\n{msgs[0].caption or ''}".strip()[:1024]
                for idx, m in enumerate(msgs):
                    try:
                        cap = base_caption if idx == 0 else ""
                        if m.photo:
                            media_list.append(InputMediaPhoto(m.photo.file_id, caption=cap))
                        elif m.video:
                            media_list.append(InputMediaVideo(m.video.file_id, caption=cap))
                        elif m.document:
                            media_list.append(InputMediaDocument(m.document.file_id, caption=cap))
                        elif m.audio:
                            media_list.append(InputMediaAudio(m.audio.file_id, caption=cap))
                    except Exception:
                        continue
            else:
                msg = msgs[0]
                full_caption = f"{sender_info}\n{msg.caption or ''}".strip()[:1024]
                if msg.text:
                    text_content = f"{sender_info}\n{msg.text}"
            
            # SEND WITH REPLY
            async def _send_to_one(uid):
                await _flood_gate.wait()
                async with _semaphore:
                    retry_count = 0
                    while retry_count < 3:
                        try:
                            reply_to_msg_id = None
                            if reply_to_sender_id and reply_to_original_msg_id:
                                reply_to_msg_id = await get_message_id_for_user(
                                    reply_to_original_msg_id,
                                    reply_to_sender_id,
                                    uid
                                )
                                if reply_to_msg_id:
                                    logger.info(f"✅ REPLY: msg_id {reply_to_msg_id} for user {uid}")
                            
                            if uid == sync_channel and text_content:
                                return
                            
                            protect = PROTECT_CONTENT and (uid not in can_forward_ids)
                            sent_msg = None
                            
                            current_media_list = media_list
                            current_full_caption = full_caption
                            
                            # Strip captions if sending to sync_channel
                            if uid == sync_channel:
                                current_full_caption = ""
                                if media_list:
                                    current_media_list = []
                                    for m in media_list:
                                        if isinstance(m, InputMediaPhoto):
                                            current_media_list.append(InputMediaPhoto(m.media, caption=""))
                                        elif isinstance(m, InputMediaVideo):
                                            current_media_list.append(InputMediaVideo(m.media, caption=""))
                                        elif isinstance(m, InputMediaDocument):
                                            current_media_list.append(InputMediaDocument(m.media, caption=""))
                                        elif isinstance(m, InputMediaAudio):
                                            current_media_list.append(InputMediaAudio(m.media, caption=""))
                            
                            if current_media_list:
                                ALBUM_MAX = 10
                                for chunk_start in range(0, len(current_media_list), ALBUM_MAX):
                                    chunk = current_media_list[chunk_start:chunk_start + ALBUM_MAX]
                                    sent_msgs = await bot.send_media_group(uid, media=chunk, protect_content=protect)
                                    if sent_msgs:
                                        for sent_msg in sent_msgs:
                                            await save_message_mapping(sent_msg.id, uid, sender_id, original_msg_id)
                                    if SEND_DELAY > 0 and chunk_start + ALBUM_MAX < len(current_media_list):
                                        await asyncio.sleep(SEND_DELAY)
                            elif text_content:
                                sent_msg = await bot.send_message(
                                    uid,
                                    text_content,
                                    disable_web_page_preview=True,
                                    reply_to_message_id=reply_to_msg_id,
                                    protect_content=protect
                                )
                                if sent_msg:
                                    await save_message_mapping(sent_msg.id, uid, sender_id, original_msg_id)
                            else:
                                try:
                                    sent_msg = await msgs[0].copy(
                                        uid,
                                        caption=current_full_caption if not msgs[0].sticker else None,
                                        reply_to_message_id=reply_to_msg_id,
                                        protect_content=protect
                                    )
                                    if sent_msg:
                                        await save_message_mapping(sent_msg.id, uid, sender_id, original_msg_id)
                                except Exception:
                                    sent_msg = await msgs[0].copy(uid, reply_to_message_id=reply_to_msg_id, protect_content=protect)
                                    if sent_msg:
                                        await save_message_mapping(sent_msg.id, uid, sender_id, original_msg_id)
                            
                            if SEND_DELAY > 0:
                                await asyncio.sleep(SEND_DELAY)
                                
                            break  # Success, exit retry loop
                        
                        except FloodWait as e:
                            logger.warning(f"⏳ FloodWait {e.value}s — pausing all broadcast sends")
                            _flood_gate.clear()
                            await asyncio.sleep(e.value + 1)
                            _flood_gate.set()
                            retry_count += 1
                        except (InputUserDeactivated, UserIsBlocked, PeerIdInvalid, ChannelInvalid):
                            if uid != sync_channel:
                                await remove_approved_user(uid)
                                registry_unregister(uid)
                            break
                        except Exception as e:
                            logger.error(f"Send error {uid}: {e}")
                            await asyncio.sleep(2)
                            retry_count += 1
            
            BATCH_SIZE = 25
            for batch_start in range(0, len(users), BATCH_SIZE):
                batch = users[batch_start:batch_start + BATCH_SIZE]
                await asyncio.gather(*[_send_to_one(u) for u in batch], return_exceptions=True)
                if batch_start + BATCH_SIZE < len(users):
                    await asyncio.sleep(1.0)
            
            has_scorable_media = any(getattr(m, 'photo', None) or getattr(m, 'video', None) for m in msgs)
            if not text_content and not msgs[0].sticker and has_scorable_media:
                asyncio.create_task(add_media_to_history(msgs))
            
            try:
                await original_msg.delete()
            except Exception:
                pass
        
        except Exception as e:
            logger.error(f"Broadcast error: {e}")
        finally:
            broadcast_queue.task_done()

async def _flush_group(key, is_user_buffer=False):
    if is_user_buffer:
        data = _user_buffers.pop(key, None)
    else:
        data = _media_groups.pop(key, None)
    
    if data and data['messages']:
        msgs = sorted(data['messages'], key=lambda m: m.id)
        await broadcast_queue.put({'msgs': msgs})

def _schedule_media(message, is_user_buffer=False):
    loop = asyncio.get_running_loop()
    
    if is_user_buffer:
        key = message.from_user.id
        store = _user_buffers
    else:
        key = (message.chat.id, message.media_group_id)
        store = _media_groups
    
    if key not in store:
        store[key] = {
            "messages": [],
            "timer": loop.call_later(
                MEDIA_GROUP_TIMEOUT,
                lambda: asyncio.create_task(_flush_group(key, is_user_buffer))
            )
        }
    
    store[key]["messages"].append(message)

# ============================================================================
# COMMAND HANDLERS
# ============================================================================
def _get_rules_content():
    """Returns (photo_file_id_or_path, text) for /rules. text max 1024 if photo else 4096."""
    photo = get_rules_photo_file_id()
    if not photo and WELCOME_PHOTO_FILE_ID:
        photo = WELCOME_PHOTO_FILE_ID
    if not photo and WELCOME_PHOTO_PATH and os.path.exists(WELCOME_PHOTO_PATH):
        photo = WELCOME_PHOTO_PATH
    text = get_rules_text() or WELCOME_RULES
    
    footer_len = len(BOT_FOOTER)
    if photo:
        text = (text or "")[:1024 - footer_len]
    else:
        text = (text or "")[:4096 - footer_len]
    text = f"{text}{BOT_FOOTER}"
    return photo, text

def _get_start_content():
    """Returns (photo_file_id_or_path, text) for /start."""
    photo = get_start_photo_file_id()
    if not photo and WELCOME_PHOTO_FILE_ID:
        photo = WELCOME_PHOTO_FILE_ID
    if not photo and WELCOME_PHOTO_PATH and os.path.exists(WELCOME_PHOTO_PATH):
        photo = WELCOME_PHOTO_PATH
    text = get_start_text() or WELCOME_RULES
    
    footer_len = len(BOT_FOOTER)
    if photo:
        text = (text or "")[:1024 - footer_len]
    else:
        text = (text or "")[:4096 - footer_len]
    text = f"{text}{BOT_FOOTER}"
    return photo, text

async def check_group_auth(client, message, user_id) -> bool:
    """Verifica si el usuario está en el grupo autorizado."""
    auth_group_id, auth_group_name = get_auth_group()
    if not auth_group_id:
        return True
    
    user_details = await get_user_details(user_id)
    if (user_id in ADMIN_IDS) or (user_details and user_details['is_admin']):
        return True

    error_msg = f"🚫 **¡Acceso Denegado!**\n\nNo estás en el grupo `{auth_group_name}`.\nPara participar en el bot, solicita a los admins la invitación al grupo `{auth_group_name}`."
    
    try:
        member = await client.get_chat_member(auth_group_id, user_id)
        if member.status in [enums.ChatMemberStatus.LEFT, enums.ChatMemberStatus.BANNED, enums.ChatMemberStatus.RESTRICTED]:
            await message.reply(error_msg)
            return False
        return True
    except Exception:
        await message.reply(error_msg)
        return False

@bot.on_message(filters.command(["start", "rules"]) & filters.private)
async def start_handler(client, message):
    """Handler for /start and /rules - Configures menu with BotCommandScopeChat"""
    user = message.from_user
    
    if not await check_group_auth(client, message, user.id):
        return
    
    if await is_user_banned(user.id):
        return await message.reply(
            "🚫 **Estás BANEADO**\n\n"
            "No puedes usar este bot.\n\n"
            "Contacta a un admin si crees que es un error."
        )
    
    cmd = (message.command or [""])[0]
    if cmd == "rules":
        photo, text = _get_rules_content()
    else:
        photo, text = _get_start_content()
    
    if photo:
        await message.reply_photo(photo, caption=text or None)
    else:
        await message.reply(text or "Bienvenido.")
    
    if message.command and message.command[0] == "start":
        is_already_approved = await is_authorized(user.id)
        
        if not is_already_approved:
            is_admin = (user.id in ADMIN_IDS)
            if not is_admin:
                other_bot = registry_check(user.id, BOT_INSTANCE_ID)
                if other_bot:
                    return await message.reply(
                        "🚫 **¡Acceso denegado!**\n\n"
                        "Ya estás registrado en otro bot de esta familia.\n"
                        "Solo puedes pertenecer a **un bot** a la vez.\n\n"
                        "Si deseas cambiar de bot, contacta a un admin para que te eliminen del bot actual."
                    )
                cap_limit = get_capacity_limit()
                if cap_limit > 0:
                    reg_count = await get_regular_users_count()
                    if reg_count >= cap_limit:
                        return await message.reply(
                            "🛑 **¡El bot está lleno!**\n\n"
                            f"Cupos ocupados: {reg_count}/{cap_limit}\n"
                            "Un cupo se libera automáticamente cuando alguien queda inactivo por 72h.\n\n"
                            "¡Intenta enviar /start nuevamente más tarde!"
                        )

        if MANUAL_APPROVAL_MODE and not is_already_approved:
            if await is_pending_approval(user.id):
                return await message.reply("⏳ Pendiente de aprobación")
            
            await add_pending_approval(user.id, user.username, user.first_name)
            for admin_id in ADMIN_IDS:
                try:
                    await bot.send_message(admin_id, f"🔔 **Nuevo usuario**\n{user.first_name}\n`{user.id}`\n\n/a {user.id} | /d {user.id}", protect_content=False)
                except Exception:
                    pass
            return await message.reply("⏳ **Aprobación requerida**")
        
        await add_approved_user(
            user.id,
            username=user.username,
            first_name=user.first_name
        )
        registry_register(user.id, BOT_INSTANCE_ID)
        if user.id in ADMIN_IDS:
            await set_user_admin_status(user.id, True)
        logger.info(f"✅ New user: {user.id} - {user.first_name}")
        
        await asyncio.sleep(1)
        
        user_details = await get_user_details(user.id)
        is_admin = (user.id in ADMIN_IDS) or (user_details and user_details['is_admin'])
        
        if is_admin:
            success = await set_admin_menu(user.id)
            if success:
                logger.info(f"🎬 Admin menu configured for {user.id} (25 commands)")
            else:
                logger.warning(f"⚠️ Admin menu failed for {user.id}, will use default")
        else:
            success = await set_user_menu(user.id)
            if success:
                logger.info(f"👤 User menu configured for {user.id} (6 commands)")
            else:
                logger.warning(f"⚠️ User menu failed for {user.id}, will use default")

SETRULES_HELP = (
    "📋 **Cómo usar /setrules:**\n\n"
    "• **Para definir la FOTO** de /rules: envía una foto y responde (reply) con /setrules.\n"
    "• **Para definir el TEXTO** de /rules: envía un mensaje de texto y responde con /setrules.\n\n"
    "Límites: 1024 caracteres con foto, 4096 sin foto.\n"
    "/rules mostrará esa foto y ese texto."
)

SETSTART_HELP = (
    "📋 **Cómo usar /setstart:**\n\n"
    "• **Para definir la FOTO** de /start: envía una foto y responde (reply) con /setstart.\n"
    "• **Para definir el TEXTO** de /start: envía un mensaje de texto y responde con /setstart.\n\n"
    "Límites: 1024 caracteres con foto, 4096 sin foto.\n"
    "/start mostrará esa foto y ese texto."
)

@bot.on_message(filters.command("setrules") & filters.private)
async def setrules_handler(client, message):
    """Admin: reply to photo or text to set /rules content."""
    user_details = await get_user_details(message.from_user.id)
    if not user_details or not user_details['is_admin']:
        return await message.reply("🚫 Solo admins")
    
    if not message.reply_to_message:
        return await message.reply(SETRULES_HELP)
    
    reply = message.reply_to_message
    if reply.photo:
        file_id = reply.photo.file_id
        set_rules_photo_file_id(file_id)
        text_content = reply.caption
        if not text_content and getattr(reply, "media_group_id", None):
            try:
                group = await client.get_media_group(reply.chat.id, reply.id)
                if group:
                    text_content = getattr(group[0], "caption", None) or ""
            except Exception:
                pass
        if text_content:
            text = strip_sender_info(text_content)[:1024]
            set_rules_text(text)
        msg = "✅ **Foto de /rules establecida.**" + (" Con texto." if text_content else "")
        await message.reply(msg)
    elif reply.text or reply.caption:
        text = strip_sender_info(reply.caption or reply.text or "")
        if len(text) > 4096:
            return await message.reply("❌ El texto debe tener máximo 4096 caracteres.")
        set_rules_text(text)
        await message.reply("✅ **Texto de /rules establecido.**")
    else:
        return await message.reply(SETRULES_HELP)

@bot.on_message(filters.command("setstart") & filters.private)
async def setstart_handler(client, message):
    """Admin: reply to photo or text to set /start content."""
    user_details = await get_user_details(message.from_user.id)
    if not user_details or not user_details['is_admin']:
        return await message.reply("🚫 Solo admins")
    
    if not message.reply_to_message:
        return await message.reply(SETSTART_HELP)
    
    reply = message.reply_to_message
    if reply.photo:
        file_id = reply.photo.file_id
        set_start_photo_file_id(file_id)
        text_content = reply.caption
        if not text_content and getattr(reply, "media_group_id", None):
            try:
                group = await client.get_media_group(reply.chat.id, reply.id)
                if group:
                    text_content = getattr(group[0], "caption", None) or ""
            except Exception:
                pass
        if text_content:
            text = strip_sender_info(text_content)[:1024]
            set_start_text(text)
        msg = "✅ **Foto de /start establecida.**" + (" Con texto." if text_content else "")
        await message.reply(msg)
    elif reply.text or reply.caption:
        text = strip_sender_info(reply.caption or reply.text or "")
        if len(text) > 4096:
            return await message.reply("❌ El texto debe tener máximo 4096 caracteres.")
        set_start_text(text)
        await message.reply("✅ **Texto de /start establecido.**")
    else:
        return await message.reply(SETSTART_HELP)

@bot.on_message(filters.command("setauthgroup") & (filters.private | filters.group | filters.channel))
async def setauthgroup_handler(client, message):
    if not message.from_user:
        if message.chat.type.value in ["group", "supergroup", "channel"]:
            try:
                await message.reply(f"⚠️ En canales o como admin anónimo, usa este comando en el chat privado del bot:\n`/setauthgroup {message.chat.id}`")
            except Exception:
                pass
        return
        
    user_details = await get_user_details(message.from_user.id)
    if not user_details or not user_details['is_admin']:
        if message.chat.type.value == "private":
            await message.reply("🚫 Solo admins")
        return
    
    if message.chat.type.value in ["group", "supergroup", "channel"]:
        group_id = message.chat.id
        group_name = message.chat.title or "Canal/Grupo Oficial"
        set_auth_group(group_id, group_name)
        await message.reply(f"✅ **¡Grupo de Autenticación Vinculado!**\n\nAhora solo los miembros del grupo `{group_name}` (ID: `{group_id}`) podrán usar el bot.")
    else:
        if len(message.command) < 2:
            return await message.reply("❌ **Uso:**\nAñade el bot al grupo/canal como Admin y escribe `/setauthgroup` allí dentro.\nO envía `/setauthgroup <ID_DEL_GRUPO_O_CANAL>` aquí en privado.")
        
        try:
            group_id = int(message.command[1])
            try:
                chat = await client.get_chat(group_id)
                group_name = chat.title or "Canal/Grupo Oficial"
            except Exception:
                group_name = "Canal/Grupo Oficial"
            
            set_auth_group(group_id, group_name)
            await message.reply(f"✅ **¡Grupo de Autenticación Vinculado!**\n\nID: `{group_id}`\nNombre: `{group_name}`\nSolo miembros podrán usar el bot.")
        except ValueError:
            await message.reply("❌ ID de grupo inválido.")

@bot.on_message(filters.command("delauthgroup") & filters.private)
async def delauthgroup_handler(client, message):
    user_details = await get_user_details(message.from_user.id)
    if not user_details or not user_details['is_admin']:
        return await message.reply("🚫 Solo admins")
    
    del_auth_group()
    await message.reply("✅ **¡Verificación de Grupo Desactivada!**\n\nEl bot ahora acepta a cualquier persona.")

@bot.on_message(filters.command("setforward") & (filters.private | filters.group | filters.channel))
async def setforward_handler(client, message):
    if not message.from_user:
        if message.chat.type.value in ["group", "supergroup", "channel"]:
            try:
                await message.reply(f"⚠️ En canales o como admin anónimo, usa este comando en el chat privado del bot:\n`/setforward {message.chat.id}`")
            except Exception:
                pass
        return
        
    user_details = await get_user_details(message.from_user.id)
    if not user_details or not user_details['is_admin']:
        if message.chat.type.value == "private":
            await message.reply("🚫 Solo admins")
        return
    
    if message.chat.type.value in ["group", "supergroup", "channel"]:
        channel_id = message.chat.id
        set_sync_channel(channel_id)
        await message.reply(f"✅ **¡Canal de Broadcast Vinculado!**\n\nTodas las fotos y videos de broadcast serán enviadas a este chat automáticamente (ID: `{channel_id}`).")
    else:
        if len(message.command) < 2:
            return await message.reply("❌ **Uso:**\nAñade el bot al canal/grupo como Admin y escribe `/setforward` allí dentro.\nO envía `/setforward <ID_DEL_CANAL>` aquí en privado.")
        
        try:
            channel_id = int(message.command[1])
            set_sync_channel(channel_id)
            await message.reply(f"✅ **¡Canal de Broadcast Vinculado!**\n\nID: `{channel_id}`\nLas fotos y videos serán enviadas allí.")
        except ValueError:
            await message.reply("❌ ID de canal inválido.")

@bot.on_message(filters.command("delforward") & filters.private)
async def delforward_handler(client, message):
    user_details = await get_user_details(message.from_user.id)
    if not user_details or not user_details['is_admin']:
        return await message.reply("🚫 Solo admins")
    
    del_sync_channel()
    await message.reply("✅ **¡Canal de Broadcast Removido!**\n\nEl bot ya no enviará copias a ningún canal extra.")

@bot.on_message(filters.command("setcapacity") & filters.private)
async def setcapacity_handler(client, message):
    user_details = await get_user_details(message.from_user.id)
    if not user_details or not user_details['is_admin']:
        return await message.reply("🚫 Solo admins")
    
    if len(message.command) < 2:
        return await message.reply("❌ **Uso:** `/setcapacity <número>`\nEj: `/setcapacity 400`. Usa 0 para desactivar el límite.")
    
    try:
        limit = int(message.command[1])
        if limit < 0:
            limit = 0
        set_capacity_limit(limit)
        if limit == 0:
            await message.reply("✅ **Límite de capacidad desactivado.** Los cupos ahora son infinitos.")
        else:
            await message.reply(f"✅ **Límite de capacidad definido en {limit} cupos.**\n(VIPs y Admins no consumen cupos).")
    except ValueError:
        await message.reply("❌ El límite debe ser un número entero.")

@bot.on_message(filters.command("stats") & filters.private)
async def stats_handler(client, message):
    """Bot statistics"""
    user_details = await get_user_details(message.from_user.id)
    if not user_details or not user_details['is_admin']:
        return await message.reply("🚫 Solo admins")
    
    users = await get_active_users_for_broadcast()
    all_users = await get_all_approved_users()
    inactive_count = len(all_users) - len(users)
    vip_count = await get_vip_users_count()
    media_stats = await get_media_stats()
    banned_count = await get_banned_users_count()
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT SUM(duplicates_blocked) FROM users")
    total_dupes = cursor.fetchone()[0] or 0
    conn.close()
    
    pending_count = len(await get_all_pending_approvals()) if MANUAL_APPROVAL_MODE else 0
    
    cap_limit = get_capacity_limit()
    if cap_limit > 0:
        reg_count = await get_regular_users_count()
        cap_text = f"🚧 Límite de usuarios: **{cap_limit}**\n📊 Cupos comunes ocupados: `{reg_count}/{cap_limit}`\n\n"
    else:
        cap_text = f"🚧 Límite de usuarios: **Ilimitado**\n\n"
    
    stats_text = (
        f"📊 **Estadísticas del Bot**\n\n"
        f"{cap_text}"
        f"🔒 Reenvío: **{'Desactivado' if PROTECT_CONTENT else 'Permitido'}**\n\n"
        f"👥 Activos: `{len(users)}`\n"
        f"⏳ Inactivos: `{inactive_count}`\n"
        f"📝 Total aprobados: `{len(all_users)}`\n"
        f"{cap_text}"
        f"⭐ VIPs: `{vip_count}`\n"
        f"🛡 Admins: `{sum(1 for u in all_users if u['is_admin'])}`\n"
        f"🚫 Baneados: `{banned_count}`\n"
        f"⏳ Pendientes: `{pending_count}`\n"
        f"🔇 Duplicados bloqueados: `{total_dupes}`\n\n"
        f"📸 Fotos: `{media_stats['photo']}`\n"
        f"🎥 Videos: `{media_stats['video']}`\n"
        f"🎬 GIFs: `{media_stats['animation']}`\n"
        f"📄 Documentos: `{media_stats['document']}`\n"
        f"🎵 Audios: `{media_stats['audio']}`\n"
        f"📦 Total media: `{sum(media_stats.values())}`"
    )
    await message.reply(stats_text)

def _listban_build_text(banned_users: list, page: int, users_per_page: int = 20) -> tuple:
    """Returns (text, total_pages) for the given page."""
    total = len(banned_users)
    total_pages = max(1, (total - 1) // users_per_page + 1)
    page = max(0, min(page, total_pages - 1))
    start = page * users_per_page
    end = min(start + users_per_page, total)
    chunk = banned_users[start:end]
    text = f"🚫 **Usuarios baneados**\n\nTotal: `{total}` | Página {page + 1}/{total_pages}\n\n"
    for user in chunk:
        name = user['first_name'] or "Desconocido"
        reason = user.get('ban_reason', 'Sin motivo')
        text += f"• `{user['user_id']}` - {name}\n   📝 Motivo: {reason}\n\n"
    text += "Usa /unban para desbanear"
    return text, total_pages, page

@bot.on_message(filters.command("listban") & filters.private)
async def listban_handler(client, message):
    """List banned users with pagination"""
    user_details = await get_user_details(message.from_user.id)
    if not user_details or not user_details['is_admin']:
        return await message.reply("🚫 Solo admins")
    
    banned_users = await get_all_banned_users()
    if not banned_users:
        return await message.reply("✅ No hay usuarios baneados")
    
    users_per_page = 20
    text, total_pages, page = _listban_build_text(banned_users, 0, users_per_page)
    
    buttons = []
    if total_pages > 1:
        row = []
        if page > 0:
            row.append(InlineKeyboardButton("⬅️ Atrás", callback_data=f"listban_{page - 1}"))
        if page < total_pages - 1:
            row.append(InlineKeyboardButton("Siguiente ➡️", callback_data=f"listban_{page + 1}"))
        if row:
            buttons.append(row)
    keyboard = InlineKeyboardMarkup(buttons) if buttons else None
    await message.reply(text, reply_markup=keyboard)

@bot.on_callback_query(filters.regex(r"^listban_\d+$"))
async def listban_pagination(client, callback_query):
    """Pagination handler for /listban"""
    user_details = await get_user_details(callback_query.from_user.id)
    if not user_details or not user_details['is_admin']:
        return await callback_query.answer("🚫 Solo admins", show_alert=True)
    
    await callback_query.answer()
    page = int(callback_query.data.split("_")[1])
    banned_users = await get_all_banned_users()
    if not banned_users:
        return await callback_query.edit_message_text("✅ No hay usuarios baneados")
    
    users_per_page = 20
    text, total_pages, current_page = _listban_build_text(banned_users, page, users_per_page)
    
    buttons = []
    if total_pages > 1:
        row = []
        if current_page > 0:
            row.append(InlineKeyboardButton("⬅️ Atrás", callback_data=f"listban_{current_page - 1}"))
        if current_page < total_pages - 1:
            row.append(InlineKeyboardButton("Siguiente ➡️", callback_data=f"listban_{current_page + 1}"))
        if row:
            buttons.append(row)
    keyboard = InlineKeyboardMarkup(buttons) if buttons else None
    
    try:
        await callback_query.edit_message_text(text, reply_markup=keyboard)
    except Exception as e:
        logger.error(f"Error updating listban pagination: {e}")

@bot.on_message(filters.command("addadmin") & filters.private)
async def addadmin_handler(client, message):
    """Add admin - user needs to send /start"""
    user_details = await get_user_details(message.from_user.id)
    if not user_details or not user_details['is_admin']:
        return await message.reply("🚫 Solo admins")
    
    target_id = None
    
    if message.reply_to_message and len(message.command) == 1:
        replied_msg_id = message.reply_to_message.id
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT original_sender_id 
            FROM message_mapping 
            WHERE broadcast_message_id = ? AND target_user_id = ?
        """, (replied_msg_id, message.from_user.id))
        result = cursor.fetchone()
        conn.close()
        
        if result:
            target_id = result[0]
        else:
            return await message.reply("❌ No se pudo identificar el remitente de este mensaje")
    else:
        if len(message.command) < 2:
            return await message.reply("❌ Uso: /addadmin <user_id> o responde a un mensaje.")
        try:
            target_id = int(message.command[1])
        except ValueError:
            return await message.reply("❌ ID inválido")
    
    try:
        await add_approved_user(target_id)
        await set_user_admin_status(target_id, True)
        await message.reply(f"✅ Admin añadido: `{target_id}`\n\n📋 El usuario debe enviar /start para actualizar su menú")
        
        try:
            await bot.send_message(target_id, "🎉 ¡Has sido promovido a **Admin**!\n\n✅ Envía /start para actualizar tu menú de comandos.", protect_content=False)
        except Exception:
            pass
    except ValueError:
        await message.reply("❌ ID inválido")
    except Exception as e:
        await message.reply(f"❌ Error: {e}")

@bot.on_message(filters.command("removeadmin") & filters.private)
async def removeadmin_handler(client, message):
    """Remove admin and delete custom menu"""
    user_details = await get_user_details(message.from_user.id)
    if not user_details or not user_details['is_admin']:
        return await message.reply("🚫 Solo admins")
    
    target_id = None
    
    if message.reply_to_message and len(message.command) == 1:
        replied_msg_id = message.reply_to_message.id
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT original_sender_id 
            FROM message_mapping 
            WHERE broadcast_message_id = ? AND target_user_id = ?
        """, (replied_msg_id, message.from_user.id))
        result = cursor.fetchone()
        conn.close()
        
        if result:
            target_id = result[0]
        else:
            return await message.reply("❌ No se pudo identificar el remitente de este mensaje")
    else:
        if len(message.command) < 2:
            return await message.reply("❌ Uso: /removeadmin <user_id> o responde a un mensaje.")
        try:
            target_id = int(message.command[1])
        except ValueError:
            return await message.reply("❌ ID inválido")
    
    try:
        
        if target_id in ADMIN_IDS:
            return await message.reply("❌ No se puede quitar al admin configurado en .env")
        
        await set_user_admin_status(target_id, False)
        
        try:
            await bot.delete_bot_commands(scope=BotCommandScopeChat(chat_id=target_id))
            logger.info(f"✅ Deleted custom menu for {target_id}")
        except Exception as e:
            logger.warning(f"⚠️ Could not delete menu for {target_id}: {e}")
        
        await message.reply(f"✅ Admin eliminado: `{target_id}`\n👤 El usuario verá el menú por defecto")
        
        try:
            await bot.send_message(target_id, "ℹ️ Tus privilegios de admin han sido removidos.\n\n👤 Tu menú de comandos ha sido restablecido.", protect_content=False)
        except Exception:
            pass
    except ValueError:
        await message.reply("❌ ID inválido")
    except Exception as e:
        await message.reply(f"❌ Error: {e}")

@bot.on_message(filters.command("vip") & filters.private)
async def vip_handler(client, message):
    """Add VIP"""
    user_details = await get_user_details(message.from_user.id)
    if not user_details or not user_details['is_admin']:
        return await message.reply("🚫 Solo admins")
    
    target_id = None
    
    if message.reply_to_message and len(message.command) == 1:
        replied_msg_id = message.reply_to_message.id
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT original_sender_id 
            FROM message_mapping 
            WHERE broadcast_message_id = ? AND target_user_id = ?
        """, (replied_msg_id, message.from_user.id))
        result = cursor.fetchone()
        conn.close()
        
        if result:
            target_id = result[0]
        else:
            return await message.reply("❌ No se pudo identificar el remitente de este mensaje")
    else:
        if len(message.command) < 2:
            return await message.reply("❌ Uso: /vip <user_id> o responde a un mensaje.")
        try:
            target_id = int(message.command[1])
        except ValueError:
            return await message.reply("❌ ID inválido")
    
    try:
        await set_user_vip_status(target_id, True)
        await add_approved_user(target_id)
        await message.reply(f"✅ VIP añadido: `{target_id}`")
        
        try:
            td = await get_user_details(target_id)
            protect = PROTECT_CONTENT and not (td and (td.get('is_admin') or td.get('is_vip')))
            await bot.send_message(target_id, "¡Ahora eres **[VIP]**! Sin límites de inactividad.", protect_content=protect)
        except Exception:
            pass
    except ValueError:
        await message.reply("❌ ID inválido")
    except Exception as e:
        await message.reply(f"❌ Error: {e}")

@bot.on_message(filters.command("unvip") & filters.private)
async def unvip_handler(client, message):
    """Remove VIP status"""
    user_details = await get_user_details(message.from_user.id)
    if not user_details or not user_details['is_admin']:
        return await message.reply("🚫 Solo admins")
    
    target_id = None
    
    if message.reply_to_message and len(message.command) == 1:
        replied_msg_id = message.reply_to_message.id
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT original_sender_id 
            FROM message_mapping 
            WHERE broadcast_message_id = ? AND target_user_id = ?
        """, (replied_msg_id, message.from_user.id))
        result = cursor.fetchone()
        conn.close()
        
        if result:
            target_id = result[0]
        else:
            return await message.reply("❌ No se pudo identificar el remitente de este mensaje")
    else:
        if len(message.command) < 2:
            return await message.reply("❌ Uso: /unvip <user_id> o responde a un mensaje.")
        try:
            target_id = int(message.command[1])
        except ValueError:
            return await message.reply("❌ ID inválido")
    
    try:
        target_details = await get_user_details(target_id)
        
        if target_details and target_details['is_admin']:
            return await message.reply("❌ Los admins siempre son VIP")
        
        await set_user_vip_status(target_id, False)
        await message.reply(f"✅ VIP eliminado: `{target_id}`")
    except ValueError:
        await message.reply("❌ ID inválido")
    except Exception as e:
        await message.reply(f"❌ Error: {e}")

@bot.on_message(filters.command("ban") & filters.private)
async def ban_handler(client, message):
    """Ban user"""
    user_details = await get_user_details(message.from_user.id)
    if not user_details or not user_details['is_admin']:
        return await message.reply("🚫 Solo admins")
    
    target_id = None
    reason = "Sin motivo"
    
    is_reply_command = False
    if message.reply_to_message:
        if len(message.command) == 1 or not message.command[1].isdigit():
            is_reply_command = True
            
    if is_reply_command:
        replied_msg_id = message.reply_to_message.id
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT original_sender_id 
            FROM message_mapping 
            WHERE broadcast_message_id = ? AND target_user_id = ?
        """, (replied_msg_id, message.from_user.id))
        result = cursor.fetchone()
        conn.close()
        
        if result:
            target_id = result[0]
            reason = " ".join(message.command[1:]) if len(message.command) > 1 else "Sin motivo"
        else:
            return await message.reply("❌ No se pudo identificar el remitente de este mensaje")
    else:
        if len(message.command) < 2:
            return await message.reply("❌ Uso: /ban <user_id> [motivo] o responde a un mensaje.")
        try:
            target_id = int(message.command[1])
            reason = " ".join(message.command[2:]) if len(message.command) > 2 else "Sin motivo"
        except ValueError:
            return await message.reply("❌ ID inválido")
    
    try:
        
        # Fetch banned user information
        target_details = await get_user_details(target_id)
        target_username = f"@{target_details['username']}" if target_details and target_details['username'] else "Sin usuario"
        target_name = target_details['first_name'] if target_details else "Desconocido"
        
        # Ban the user
        await ban_user_permanent(target_id, reason=reason)
        registry_unregister(target_id)
        await message.reply(f"✅ Usuario `{target_id}` baneado\nMotivo: {reason}")
        
        # Notify banned user
        try:
            protect = PROTECT_CONTENT and not (target_details and (target_details.get('is_admin') or target_details.get('is_vip')))
            await bot.send_message(target_id, f"🚫 Has sido baneado.\nMotivo: {reason}", protect_content=protect)
        except Exception:
            pass
        
        # 📢 NOTIFICACIÓN PARA TODOS LOS MIEMBROS (BROADCAST)
        broadcast_msg = (
            f"🚫 **Usuario baneado**\n\n"
            f"**Usuario:** {target_name} {target_username} (`{target_id}`)\n"
            f"**Motivo:** {reason}"
        )
        
        can_forward_ban = {u['user_id'] for u in await get_all_approved_users() if u.get('is_admin') or u.get('is_vip')}
        active_users = await get_active_users_for_broadcast()
        for uid in active_users:
            try:
                protect = PROTECT_CONTENT and (uid not in can_forward_ban)
                await bot.send_message(uid, broadcast_msg, protect_content=protect)
                if SEND_DELAY > 0:
                    await asyncio.sleep(SEND_DELAY)
            except Exception:
                pass
        
        # 📋 LOG DETALHADO PARA ADMINS
        admin_username = f"@{message.from_user.username}" if message.from_user.username else "@no_username"
        admin_log = (
            f"🚨 **REGISTRO DE BAN - Acción Admin**\n\n"
            f"👮 **Baneado por:** {message.from_user.first_name} {admin_username} [`{message.from_user.id}`]\n"
            f"🚫 **Usuario baneado:** {target_name} {target_username} [`{target_id}`]\n"
            f"📝 **Motivo:** {reason}\n"
            f"🕐 **Hora:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        
        # Send log to all admins
        all_users = await get_all_approved_users()
        for user in all_users:
            if user['is_admin'] and user['user_id'] != message.from_user.id:  # Do not send to ban executor
                try:
                    await bot.send_message(user['user_id'], admin_log, protect_content=False)
                except Exception:
                    pass
        
        logger.info(f"🚫 BAN: Admin {message.from_user.id} banned user {target_id} - Reason: {reason}")
        
    except ValueError:
        await message.reply("❌ ID inválido")
    except Exception as e:
        await message.reply(f"❌ Error: {e}")


@bot.on_message(filters.command("unban") & filters.private)
async def unban_handler(client, message):
    """Unban user"""
    user_details = await get_user_details(message.from_user.id)
    if not user_details or not user_details['is_admin']:
        return await message.reply("🚫 Solo admins")
    
    target_id = None
    
    if message.reply_to_message and len(message.command) == 1:
        replied_msg_id = message.reply_to_message.id
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT original_sender_id 
            FROM message_mapping 
            WHERE broadcast_message_id = ? AND target_user_id = ?
        """, (replied_msg_id, message.from_user.id))
        result = cursor.fetchone()
        conn.close()
        
        if result:
            target_id = result[0]
        else:
            return await message.reply("❌ No se pudo identificar el remitente de este mensaje")
    else:
        if len(message.command) < 2:
            return await message.reply("❌ Uso: /unban <user_id> o responde a un mensaje.")
        try:
            target_id = int(message.command[1])
        except ValueError:
            return await message.reply("❌ ID inválido")
    
    try:
        await unban_user_permanent(target_id)
        await message.reply(f"✅ Usuario `{target_id}` desbaneado")
    except ValueError:
        await message.reply("❌ ID inválido")
    except Exception as e:
        await message.reply(f"❌ Error: {e}")

@bot.on_message(filters.command("me") & filters.private)
async def me_handler(client, message):
    """Show user information"""
    user = message.from_user
    details = await get_user_details(user.id)
    
    if not details:
        return await message.reply("❌ No estás registrado. Usa /start")
    
    status = []
    if details['is_admin']:
        status.append("[ADMIN]")
    if details['is_vip']:
        status.append("[VIP]")
    
    status_str = " | ".join(status) if status else "👤 Usuario regular"
    
    media_stats = await get_user_media_stats(user.id)
    
    info_text = (
        f"👤 **Tu información**\n\n"
        f"🆔 ID: `{user.id}`\n"
        f"👤 Nombre: {user.first_name}\n"
        f"🏷 Estado: {status_str}\n"
        f"📸 Fotos enviadas: `{media_stats['photo']}` | 🎥 Videos enviados: `{media_stats['video']}`\n"
        f"⚠️ Advertencias: {details.get('inactivity_warnings', 0)}/3\n"
        f"🚫 Duplicados bloqueados: {details.get('duplicates_blocked', 0)}\n"
        f"🕐 Última actividad: {details['last_active']}"
        f"{BOT_FOOTER}"
    )
    await message.reply(info_text)

@bot.on_message(filters.command("list_users") & filters.private)
async def list_users_handler(client, message):
    """List all users with pagination and category separators"""
    user_details = await get_user_details(message.from_user.id)
    if not user_details or not user_details['is_admin']:
        return await message.reply("🚫 Solo admins")
    
    users = await get_all_approved_users()
    page = 0
    users_per_page = 50
    total_pages = (len(users) - 1) // users_per_page + 1
    start_idx = page * users_per_page
    end_idx = min(start_idx + users_per_page, len(users))
    
    text = f"📋 **Total usuarios**: {len(users)} | Página {page + 1}/{total_pages}\n\n"
    
    current_category = None
    
    for u in users[start_idx:end_idx]:
        if u['is_admin']:
            category = 'ADMINS'
        elif u['is_vip']:
            category = 'VIPS'
        else:
            category = 'USERS'
        
        if category != current_category:
            if current_category is not None:
                text += "═════════════════\n\n"
            text += f"**{category}**\n═════════════════\n"
            current_category = category
        
        tags = []
        if u['is_admin']:
            tags.append("[ADMIN]")
        if u['is_vip']:
            tags.append("[VIP]")
        tag_str = " ".join(tags)
        name = u['first_name'] or "Desconocido"
        text += f"• `{u['user_id']}` - {name} {tag_str}\n"
    
    if current_category is not None:
        text += "═════════════════"
    
    buttons = []
    if total_pages > 1:
        row = []
        if page > 0:
            row.append(InlineKeyboardButton("⬅️ Anterior", callback_data=f"listusers_{page-1}"))
        if page < total_pages - 1:
            row.append(InlineKeyboardButton("Siguiente ➡️", callback_data=f"listusers_{page+1}"))
        if row:
            buttons.append(row)
    
    keyboard = InlineKeyboardMarkup(buttons) if buttons else None
    await message.reply(text, reply_markup=keyboard)

@bot.on_callback_query(filters.regex(r"^listusers_\d+$"))
async def list_users_pagination(client, callback_query):
    """Pagination handler for /list_users"""
    user_details = await get_user_details(callback_query.from_user.id)
    if not user_details or not user_details['is_admin']:
        return await callback_query.answer("🚫 Solo admins", show_alert=True)
    
    await callback_query.answer()
    
    page = int(callback_query.data.split("_")[1])
    users = await get_all_approved_users()
    users_per_page = 50
    total_pages = (len(users) - 1) // users_per_page + 1
    start_idx = page * users_per_page
    end_idx = min(start_idx + users_per_page, len(users))
    
    text = f"📋 **Total usuarios**: {len(users)} | Página {page + 1}/{total_pages}\n\n"
    
    current_category = None
    
    for u in users[start_idx:end_idx]:
        if u['is_admin']:
            category = 'ADMINS'
        elif u['is_vip']:
            category = 'VIPS'
        else:
            category = 'USERS'
        
        if category != current_category:
            if current_category is not None:
                text += "═════════════════\n\n"
            text += f"**{category}**\n═════════════════\n"
            current_category = category
        
        tags = []
        if u['is_admin']:
            tags.append("[ADMIN]")
        if u['is_vip']:
            tags.append("[VIP]")
        tag_str = " ".join(tags)
        name = u['first_name'] or "Desconocido"
        text += f"• `{u['user_id']}` - {name} {tag_str}\n"
    
    if current_category is not None:
        text += "═════════════════"
    
    buttons = []
    if total_pages > 1:
        row = []
        if page > 0:
            row.append(InlineKeyboardButton("⬅️ Anterior", callback_data=f"listusers_{page-1}"))
        if page < total_pages - 1:
            row.append(InlineKeyboardButton("Siguiente ➡️", callback_data=f"listusers_{page+1}"))
        if row:
            buttons.append(row)
    
    keyboard = InlineKeyboardMarkup(buttons) if buttons else None
    
    try:
        await callback_query.edit_message_text(text, reply_markup=keyboard)
    except Exception as e:
        logger.error(f"Error updating list_users pagination: {e}")

@bot.on_message(filters.command("showuser") & filters.private)
async def showuser_handler(client, message):
    """Show complete user information - Supports reply"""
    user_details = await get_user_details(message.from_user.id)
    if not user_details or not user_details['is_admin']:
        return await message.reply("🚫 Solo admins")
    
    target_id = None
    
    # Check if used in reply
    if message.reply_to_message:
        # Find who sent the original message
        replied_msg_id = message.reply_to_message.id
        
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT original_sender_id 
            FROM message_mapping 
            WHERE broadcast_message_id = ? AND target_user_id = ?
        """, (replied_msg_id, message.from_user.id))
        result = cursor.fetchone()
        conn.close()
        
        if result:
            target_id = result[0]
            logger.info(f"🔍 /showuser via reply: Found sender {target_id}")
        else:
            return await message.reply("❌ No se pudo identificar el remitente de este mensaje")
    
    # Traditional usage: /showuser <user_id>
    elif len(message.command) >= 2:
        try:
            target_id = int(message.command[1])
        except ValueError:
            return await message.reply("❌ ID de usuario inválido")
    else:
        return await message.reply(
            "❌ **Uso:**\n"
            "• `/showuser <user_id>` - Ver info por ID\n"
            "• `/showuser` (respondiendo) - Ver info del remitente"
        )
    
    # Fetch and display information
    target_details = await get_user_details(target_id)
    if not target_details:
        return await message.reply(f"❌ Usuario `{target_id}` no encontrado en la base de datos")
    
    status = []
    if target_details['is_admin']:
        status.append("[ADMIN]")
    if target_details['is_vip']:
        status.append("[VIP]")
    status_str = " | ".join(status) if status else "👤 Usuario regular"
    
    info_text = (
        f"👤 **Información del usuario**\n\n"
        f"🆔 ID: `{target_details['user_id']}`\n"
        f"👤 Nombre: {target_details['first_name'] or 'Desconocido'}\n"
        f"🏷 Estado: {status_str}\n"
        f"⚠️ Advertencias: {target_details['inactivity_warnings']}/3\n"
        f"🚫 Duplicados bloqueados: {target_details['duplicates_blocked']}\n"
        f"🕐 Última actividad: {target_details['last_active']}\n"
        f"🚨 Baneado: {'Sí' if target_details['is_banned'] else 'No'}"
    )
    
    if target_details['is_banned'] and target_details['ban_reason']:
        info_text += f"\n📝 Motivo del ban: {target_details['ban_reason']}"
    
    await message.reply(info_text)

@bot.on_message(filters.command("report") & filters.private)
async def report_handler(client, message):
    """Report a user by replying to their message - Notifies all admins"""
    if not message.reply_to_message:
        return await message.reply(
            "❌ **Cómo reportar:**\n\n"
            "Responde al mensaje que quieras reportar y envía /report.\n\n"
            "Opcional: /report <motivo> - Añadir un motivo al reporte."
        )
    
    reporter = message.from_user
    replied_msg_id = message.reply_to_message.id
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT original_sender_id, original_message_id
        FROM message_mapping
        WHERE broadcast_message_id = ? AND target_user_id = ?
    """, (replied_msg_id, reporter.id))
    result = cursor.fetchone()
    conn.close()
    
    if not result:
        return await message.reply("❌ No se pudo identificar el remitente. Responde solo a mensajes del broadcast.")
    
    reported_id, original_message_id = result[0], result[1]
    if reported_id == reporter.id:
        return await message.reply("❌ No puedes reportar tu propio mensaje.")
    
    reported_details = await get_user_details(reported_id)
    reported_name = reported_details['first_name'] if reported_details else "Desconocido"
    reported_username = f"@{reported_details['username']}" if reported_details and reported_details.get('username') else "Sin usuario"
    reason = " ".join(message.command[1:]).strip() if len(message.command) > 1 else "Sin motivo"
    
    report_text = (
        f"🚨 **REPORTE**\n\n"
        f"**Usuario reportado:** {reported_name} {reported_username} (`{reported_id}`)\n"
        f"**Reportado por:** {reporter.first_name} (`{reporter.id}`)\n"
        f"**Motivo:** {reason}\n\n"
        "_Contenido reenviado arriba ↑_"
    )
    
    report_buttons = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🚫 BAN", callback_data=f"rep_ban_{reported_id}"),
            InlineKeyboardButton("🗑️ ERASE", callback_data=f"rep_erase_{reported_id}_{original_message_id}")
        ]
    ])
    
    async def _send_report_to_admin(admin_id):
        try:
            await message.reply_to_message.forward(admin_id)
            await bot.send_message(admin_id, report_text, reply_markup=report_buttons, protect_content=False)
        except Exception as e:
            logger.warning(f"Could not send report to admin {admin_id}: {e}")
    
    for admin_id in ADMIN_IDS:
        await _send_report_to_admin(admin_id)
    
    all_users = await get_all_approved_users()
    for u in all_users:
        if u.get('is_admin') and u['user_id'] not in ADMIN_IDS:
            try:
                await message.reply_to_message.forward(u['user_id'])
                await bot.send_message(u['user_id'], report_text, reply_markup=report_buttons, protect_content=False)
            except Exception:
                pass
    
    await message.reply("✅ **Reporte enviado.** Los admins han sido notificados.")
    logger.info(f"🚨 REPORT: {reporter.id} reported {reported_id} - {reason}")

@bot.on_callback_query(filters.regex(r"^rep_ban_(\d+)$"))
async def report_ban_callback(client, callback_query):
    """BAN user from report button"""
    user_details = await get_user_details(callback_query.from_user.id)
    if not user_details or not user_details['is_admin']:
        return await callback_query.answer("🚫 Solo admins", show_alert=True)
    
    reported_id = int(callback_query.data.split("_")[2])
    reason = "Reporte: contenido inapropiado"
    
    await ban_user_permanent(reported_id, reason=reason)
    registry_unregister(reported_id)
    target_details = await get_user_details(reported_id)
    try:
        protect = PROTECT_CONTENT and not (target_details and (target_details.get('is_admin') or target_details.get('is_vip')))
        await bot.send_message(reported_id, f"🚫 Has sido baneado.\nMotivo: {reason}", protect_content=protect)
    except Exception:
        pass
    
    try:
        await callback_query.edit_message_text(
            callback_query.message.text + f"\n\n✅ **BANEADO** por {callback_query.from_user.first_name}",
            reply_markup=None
        )
    except Exception:
        pass
    await callback_query.answer("✅ Usuario baneado", show_alert=False)
    logger.info(f"🚫 REPORT BAN: Admin {callback_query.from_user.id} banned {reported_id}")

@bot.on_callback_query(filters.regex(r"^rep_erase_(\d+)_(\d+)$"))
async def report_erase_callback(client, callback_query):
    """ERASE broadcast message from report button"""
    user_details = await get_user_details(callback_query.from_user.id)
    if not user_details or not user_details['is_admin']:
        return await callback_query.answer("🚫 Solo admins", show_alert=True)
    
    parts = callback_query.data.split("_")
    original_sender_id = int(parts[2])
    original_message_id = int(parts[3])
    
    recipients = await get_all_broadcast_recipients(original_sender_id, original_message_id)
    if not recipients:
        return await callback_query.answer("❌ No se encontraron destinatarios", show_alert=True)
    
    await callback_query.answer("🗑️ Eliminando...", show_alert=False)
    
    reason = "Contenido eliminado - Reporte"
    deleted = 0
    failed = 0
    
    by_user = defaultdict(list)
    for r in recipients:
        by_user[r['user_id']].append(r['message_id'])
    
    for uid, msg_ids in by_user.items():
        try:
            await bot.delete_messages(chat_id=uid, message_ids=msg_ids)
            deleted += 1
            try:
                notification = f"🗑️ **Contenido eliminado**\n\n**Motivo:** {reason}"
                recv_details = await get_user_details(uid)
                protect = PROTECT_CONTENT and not (recv_details and (recv_details.get('is_admin') or recv_details.get('is_vip')))
                await bot.send_message(uid, notification, protect_content=protect)
            except Exception:
                pass
            if SEND_DELAY > 0:
                await asyncio.sleep(SEND_DELAY)
        except Exception:
            failed += 1
    
    try:
        await callback_query.edit_message_text(
            callback_query.message.text + f"\n\n✅ **ELIMINADO** por {callback_query.from_user.first_name}\n📨 Borrado para {deleted} usuarios | Fallos: {failed}",
            reply_markup=None
        )
    except Exception:
        pass
    logger.info(f"🗑️ REPORT ERASE: Admin {callback_query.from_user.id} erased broadcast {original_message_id}")

@bot.on_message(filters.command("whois") & filters.private)
async def whois_handler(client, message):
    """Search users by name or username - Supports reply"""
    user_details = await get_user_details(message.from_user.id)
    if not user_details or not user_details['is_admin']:
        return await message.reply("🚫 Solo admins")
    
    target_id = None
    search_by_reply = False
    
    # Check if used in reply (works for photo, video, text, gif, audio, album, etc.)
    if message.reply_to_message and len(message.command) == 1:
        # Find who sent the original message (any media type)
        replied_msg_id = message.reply_to_message.id
        
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT original_sender_id 
            FROM message_mapping 
            WHERE broadcast_message_id = ? AND target_user_id = ?
        """, (replied_msg_id, message.from_user.id))
        result = cursor.fetchone()
        conn.close()
        
        if result:
            target_id = result[0]
            search_by_reply = True
            logger.info(f"🔍 /whois via reply: Found sender {target_id}")
        else:
            return await message.reply("❌ No se pudo identificar el remitente de este mensaje")
    
    # Search by name/username
    if not search_by_reply:
        if len(message.command) < 2:
            return await message.reply(
                "❌ **Uso:**\n"
                "• `/whois <nombre>` - Buscar usuarios por nombre o @usuario\n"
                "• `/whois` (respondiendo) - Ver info del remitente del mensaje"
            )
        
        search_term = " ".join(message.command[1:]).strip()
        if search_term.startswith("@"):
            search_term = search_term[1:]
        
        results = await search_users_by_name(search_term)
        
        if not results:
            return await message.reply(f"❌ No se encontraron usuarios que coincidan: **{search_term}**")
        
        text = f"🔍 **Resultados para:** `{search_term}`\n\n"
        text += f"Encontrados: {len(results)} usuario(s)\n\n"
        
        for user in results:
            media_stats = await get_user_media_stats(user['user_id'])
            
            tags = []
            if user['is_admin']:
                tags.append("[ADMIN]")
            if user['is_vip']:
                tags.append("[VIP]")
            tag_str = " ".join(tags)
            
            username_display = f"@{user['username']}" if user['username'] else "Sin usuario"
            banned_str = " 🚫 BANEADO" if user['is_banned'] else ""
            
            joined_str = user.get('joined_date') or "N/D"
            text += (
                f"👤 **{user['first_name']}** {tag_str}{banned_str}\n"
                f"  🆔 ID: `{user['user_id']}`\n"
                f"  📝 Usuario: {username_display}\n"
                f"  📅 Unido: {joined_str}\n"
                f"  🚫 Duplicados: {user['duplicates_blocked']}\n"
                f"  🕐 Último: {user['last_active']}\n"
                f"  📊 **Estadísticas de media:**\n"
                f"    📸 Fotos: {media_stats['photo']}\n"
                f"    🎥 Videos: {media_stats['video']}\n"
                f"    🎬 GIFs: {media_stats['animation']}\n"
                f"    📄 Documentos: {media_stats['document']}\n"
                f"    🎵 Audios: {media_stats['audio']}\n"
                f"    📦 Total media: {media_stats['total']}\n\n"
            )
        
        if len(results) == 20:
            text += "\n_Mostrando los primeros 20 resultados. Refina la búsqueda para más resultados._"
        
        await message.reply(text)
    
    # If used in reply, show detailed information
    else:
        target_details = await get_user_details(target_id)
        if not target_details:
            return await message.reply(f"❌ Usuario `{target_id}` no encontrado en la base de datos")
        
        media_stats = await get_user_media_stats(target_id)
        
        status = []
        if target_details['is_admin']:
            status.append("[ADMIN]")
        if target_details['is_vip']:
            status.append("[VIP]")
        status_str = " | ".join(status) if status else "👤 Usuario regular"
        
        username_display = f"@{target_details['username']}" if target_details['username'] else "Sin usuario"
        banned_str = " 🚫 BANEADO" if target_details['is_banned'] else ""
        joined_str = target_details.get('joined_date') or "N/D"
        
        info_text = (
            f"🔍 **Información del remitente**\n\n"
            f"👤 **{target_details['first_name']}** {banned_str}\n"
            f"🆔 ID: `{target_details['user_id']}`\n"
            f"📝 Usuario: {username_display}\n"
            f"📅 Unido: {joined_str}\n"
            f"🏷 Estado: {status_str}\n"
            f"⚠️ Advertencias: {target_details['inactivity_warnings']}/3\n"
            f"🚫 Duplicados bloqueados: {target_details['duplicates_blocked']}\n"
            f"🕐 Última actividad: {target_details['last_active']}\n\n"
            f"📊 **Estadísticas de media:**\n"
            f"📸 Fotos: {media_stats['photo']}\n"
            f"🎥 Videos: {media_stats['video']}\n"
            f"🎬 GIFs: {media_stats['animation']}\n"
            f"📄 Documentos: {media_stats['document']}\n"
            f"🎵 Audios: {media_stats['audio']}\n"
            f"📦 Total media: {media_stats['total']}"
        )
        
        if target_details['is_banned'] and target_details['ban_reason']:
            info_text += f"\n\n📝 Motivo del ban: {target_details['ban_reason']}"
        
        await message.reply(info_text)

@bot.on_message(filters.command("dupes_stats") & filters.private)
async def dupes_stats_handler(client, message):
    """Show top users with duplicates blocked"""
    user_details = await get_user_details(message.from_user.id)
    if not user_details or not user_details['is_admin']:
        return await message.reply("🚫 Solo admins")
    
    top_users = await get_top_duplicate_users(20)
    
    if not top_users:
        return await message.reply("✅ No se detectaron intentos de duplicados")
    
    text = "📊 **Usuarios con más duplicados bloqueados**\n\n"
    
    for idx, user in enumerate(top_users[:15], 1):
        tags = []
        if user['is_admin']:
            tags.append("[ADMIN]")
        if user['is_vip']:
            tags.append("[VIP]")
        tag_str = " ".join(tags)
        
        text += (
            f"{idx}. **{user['first_name']}** {tag_str}\n"
            f"   🆔 ID: `{user['user_id']}`\n"
            f"   🚫 Bloqueados: {user['duplicates_blocked']}x\n\n"
        )
    
    total_blocked = sum(u['duplicates_blocked'] for u in top_users)
    text += f"\n📦 Total duplicados bloqueados: {total_blocked}"
    
    await message.reply(text)

@bot.on_message(filters.command("approve") & filters.private)
async def approve_toggle(client, message):
    """Toggle manual approval mode"""
    user_details = await get_user_details(message.from_user.id)
    if not user_details or not user_details['is_admin']:
        return await message.reply("🚫 Solo admins")
    
    global MANUAL_APPROVAL_MODE
    MANUAL_APPROVAL_MODE = not MANUAL_APPROVAL_MODE
    set_manual_approval_mode(MANUAL_APPROVAL_MODE)
    status = "ON ✅" if MANUAL_APPROVAL_MODE else "OFF ❌"
    await message.reply(f"🔐 **Modo aprobación: {status}**")

@bot.on_message(filters.command("toggleforward") & filters.private)
async def toggleforward_handler(client, message):
    """Toggle forwarding disabled (protect content) ON/OFF"""
    user_details = await get_user_details(message.from_user.id)
    if not user_details or not user_details['is_admin']:
        return await message.reply("🚫 Solo admins")
    
    global PROTECT_CONTENT
    PROTECT_CONTENT = not PROTECT_CONTENT
    set_protect_content(PROTECT_CONTENT)
    status = "ON ✅ (reenvío desactivado)" if PROTECT_CONTENT else "OFF ❌ (reenvío permitido)"
    await message.reply(f"🔒 **Reenvío: {status}**")

@bot.on_message(filters.command(["listap", "pending"]) & filters.private)
async def listap_handler(client, message):
    """List pending approval users"""
    user_details = await get_user_details(message.from_user.id)
    if not user_details or not user_details['is_admin']:
        return await message.reply("🚫 Solo admins")
    
    pending = await get_all_pending_approvals()
    
    if not pending:
        return await message.reply("✅ No hay pendientes")
    
    text = f"⏳ **Pendientes ({len(pending)}):**\n\n"
    for u in pending:
        text += f"• {u['first_name']}\n   `{u['user_id']}`\n   /a {u['user_id']} | /d {u['user_id']}\n\n"
    
    await message.reply(text.strip())

@bot.on_message(filters.command("a") & filters.private)
async def approve_handler(client, message):
    """Approve pending user"""
    user_details = await get_user_details(message.from_user.id)
    if not user_details or not user_details['is_admin']:
        return await message.reply("🚫 Solo admins")
    
    if len(message.command) < 2:
        return await message.reply("Uso: /a <user_id>")
    
    try:
        user_id = int(message.command[1])
        
        if not await is_pending_approval(user_id):
            return await message.reply("❌ No está pendiente")

        other_bot = registry_check(user_id, BOT_INSTANCE_ID)
        if other_bot:
            await remove_pending_approval(user_id)
            try:
                await bot.send_message(
                    user_id,
                    "🚫 **¡Acceso denegado!**\n\n"
                    "Ya estás registrado en otro bot de esta familia.\n"
                    "Solo puedes pertenecer a **un bot** a la vez.\n\n"
                    "Si deseas cambiar de bot, contacta a un admin para que te eliminen del bot actual."
                )
            except Exception:
                pass
            return await message.reply(f"❌ Usuario `{user_id}` ya registrado en otro bot. Removido de pendientes.")

        try:
            tg_user = await bot.get_users(user_id)
            username = tg_user.username
            first_name = tg_user.first_name
        except Exception:
            username = None
            first_name = "Desconocido"

        await add_approved_user(user_id, username, first_name)
        registry_register(user_id, BOT_INSTANCE_ID)
        await remove_pending_approval(user_id)
        
        try:
            ud = await get_user_details(user_id)
            protect = PROTECT_CONTENT and not (ud and (ud.get('is_admin') or ud.get('is_vip')))
            start_text = get_start_text() or WELCOME_RULES
            await bot.send_message(user_id, f"✅ **APPROVED!**\n\n{start_text}", protect_content=protect)
        except Exception:
            pass
        
        await message.reply(f"✅ Aprobado: {user_id}")
    except Exception:
        await message.reply("❌ ID inválido")

@bot.on_message(filters.command("d") & filters.private)
async def decline_handler(client, message):
    """Decline pending user"""
    user_details = await get_user_details(message.from_user.id)
    if not user_details or not user_details['is_admin']:
        return await message.reply("🚫 Solo admins")
    
    if len(message.command) < 2:
        return await message.reply("Uso: /d <user_id>")
    
    try:
        user_id = int(message.command[1])
        
        if not await is_pending_approval(user_id):
            return await message.reply("❌ No está pendiente")
        
        await remove_pending_approval(user_id)
        
        try:
            ud = await get_user_details(user_id)
            protect = PROTECT_CONTENT and not (ud and (ud.get('is_admin') or ud.get('is_vip')))
            await bot.send_message(user_id, "❌ **Rechazado**", protect_content=protect)
        except Exception:
            pass
        
        await message.reply(f"✅ Rechazado: {user_id}")
    except Exception:
        await message.reply("❌ ID inválido")

@bot.on_message(filters.command("fix") & filters.private)
async def fix_handler(client, message):
    """Pin message in private chat of ALL users"""
    user_details = await get_user_details(message.from_user.id)
    if not user_details or not user_details['is_admin']:
        return await message.reply("🚫 Solo admins")
    
    if message.reply_to_message:
        texto = message.reply_to_message.text or message.reply_to_message.caption
        if not texto:
            return await message.reply("❌ El mensaje debe contener texto")
    elif len(message.command) > 1:
        texto = " ".join(message.command[1:])
    else:
        return await message.reply(
            "❌ **Uso:**\n"
            "• `/fix <texto>` - Enviar y fijar un mensaje\n"
            "• `/fix` (respondiendo) - Fijar el mensaje respondido"
        )
    
    users = await get_active_users_for_broadcast()
    can_forward_fix = {u['user_id'] for u in await get_all_approved_users() if u.get('is_admin') or u.get('is_vip')}
    pinned = 0
    failed = 0
    
    await message.reply(f"📌 Fijando mensaje para `{len(users)}` usuarios...")
    
    for uid in users:
        try:
            protect = PROTECT_CONTENT and (uid not in can_forward_fix)
            sent = await bot.send_message(uid, texto, protect_content=protect)
            await bot.pin_chat_message(
                chat_id=uid,
                message_id=sent.id,
                disable_notification=False,
                both_sides=True
            )
            pinned += 1
            
            if SEND_DELAY > 0:
                await asyncio.sleep(SEND_DELAY)
        except Exception as e:
            logger.error(f"Error pinning for {uid}: {e}")
            failed += 1
    
    await message.reply(
        f"✅ **¡Mensaje fijado!**\n\n"
        f"• Éxito: `{pinned}` usuarios\n"
        f"• Fallos: `{failed}` usuarios"
    )

@bot.on_message(filters.command("unfix") & filters.private)
async def unfix_handler(client, message):
    """Unpin all messages from all private chats"""
    user_details = await get_user_details(message.from_user.id)
    if not user_details or not user_details['is_admin']:
        return await message.reply("🚫 Solo admins")
    
    users = await get_active_users_for_broadcast()
    unfixed = 0
    
    await message.reply(f"🔓 Desfijando mensajes para `{len(users)}` usuarios...")
    
    for uid in users:
        try:
            await bot.unpin_all_chat_messages(uid)
            unfixed += 1
            
            if SEND_DELAY > 0:
                await asyncio.sleep(SEND_DELAY)
        except Exception as e:
            logger.error(f"Error unpinning for {uid}: {e}")
    
    await message.reply(f"✅ Desfijado para `{unfixed}` usuarios")

@bot.on_message(filters.command("scan") & filters.private)
async def scan_handler(client, message):
    """Scan users inactive for 3 days (no photo/video activity). Excludes users already handled by 24h rule."""
    user_details = await get_user_details(message.from_user.id)
    if not user_details or not user_details['is_admin']:
        return await message.reply("🚫 Solo admins")
    
    inactive_users = await get_inactive_users_3days()
    
    if not inactive_users:
        return await message.reply(
            "✅ **No se encontraron usuarios inactivos**\n\n"
            "Todos los usuarios (no VIP/Admin) enviaron fotos o videos en los últimos 3 días (72h)."
        )
    
    text = (
        f"🔍 **Escaneo de usuarios inactivos (3+ días)**\n\n"
        f"Encontrados: **{len(inactive_users)} usuarios** sin actividad de foto/video\n\n"
        f"⚠️ Estos usuarios NO han enviado fotos ni videos en los últimos 3 días.\n"
        f"_(Excluidos los ya notificados por inactividad)_\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
    )
    
    for idx, user in enumerate(inactive_users[:20], 1):
        user_id = user['user_id']
        username = f"@{user['username']}" if user['username'] else "Sin usuario"
        name = user['first_name']
        last_active = user['last_active']
        dupes = user['duplicates_blocked']
        
        try:
            from datetime import datetime
            last_active_dt = datetime.strptime(last_active, '%Y-%m-%d %H:%M:%S')
            days_inactive = (datetime.now() - last_active_dt).days
        except Exception:
            days_inactive = "?"
        
        text += (
            f"**{idx}.** {name}\n"
            f"   🆔 `{user_id}` {username}\n"
            f"   🕐 Último: {last_active} (hace {days_inactive}d)\n"
            f"   🚫 Dupes: {dupes}\n\n"
        )
    
    if len(inactive_users) > 20:
        text += f"\n_... y {len(inactive_users) - 20} usuarios inactivos más._\n\n"
    
    text += (
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 **Total: {len(inactive_users)} usuarios**\n\n"
        f"⚠️ **Nota:** Solo fotos y videos cuentan como actividad (inactividad 24h = baja del broadcast).\n"
        f"Textos, stickers y otros medios NO reinician la inactividad.\n\n"
        f"🔴 Usa los botones para actuar:"
    )
    
    buttons = [
        [
            InlineKeyboardButton("🚪 Remover todos inactivos", callback_data=f"scan_ban_all_{len(inactive_users)}"),
            InlineKeyboardButton("❌ Cancelar", callback_data="scan_cancel")
        ]
    ]
    
    keyboard = InlineKeyboardMarkup(buttons)
    await message.reply(text, reply_markup=keyboard)


@bot.on_callback_query(filters.regex(r"^scan_ban_all_\d+$"))
async def scan_ban_all_callback(client, callback_query):
    """Confirm and execute mass ban"""
    user_details = await get_user_details(callback_query.from_user.id)
    if not user_details or not user_details['is_admin']:
        return await callback_query.answer("🚫 Solo admins", show_alert=True)
    
    inactive_users = await get_inactive_users_3days()
    
    if not inactive_users:
        await callback_query.edit_message_text("✅ No hay usuarios inactivos para banear.")
        return await callback_query.answer("No se encontraron usuarios", show_alert=True)
    
    confirm_text = (
        f"⚠️ **CONFIRMACIÓN DE REMOCIÓN MASIVA**\n\n"
        f"Estás a punto de **REMOVER DE LA DIFUSIÓN** a {len(inactive_users)} usuarios.\n\n"
        f"**Motivo:** Inactivos 3+ días (sin foto/video)\n\n"
        f"¿Estás seguro?"
    )
    
    confirm_buttons = [
        [
            InlineKeyboardButton("✅ SÍ, REMOVER TODOS", callback_data="scan_confirm_ban"),
            InlineKeyboardButton("❌ NO, CANCELAR", callback_data="scan_cancel")
        ]
    ]
    
    confirm_keyboard = InlineKeyboardMarkup(confirm_buttons)
    await callback_query.edit_message_text(confirm_text, reply_markup=confirm_keyboard)
    await callback_query.answer()


@bot.on_callback_query(filters.regex(r"^scan_confirm_ban$"))
async def scan_confirm_ban_callback(client, callback_query):
    """Execute mass ban"""
    user_details = await get_user_details(callback_query.from_user.id)
    if not user_details or not user_details['is_admin']:
        return await callback_query.answer("🚫 Solo admins", show_alert=True)
    
    await callback_query.answer("🔄 Removiendo usuarios... Puede tardar un poco.", show_alert=True)
    
    inactive_users = await get_inactive_users_3days()
    
    if not inactive_users:
        return await callback_query.edit_message_text("✅ No se encontraron usuarios inactivos.")
    
    progress_text = (
        f"🔄 **Remoción masiva en progreso...**\n\n"
        f"Removiendo {len(inactive_users)} usuarios...\n\n"
        f"Espera, puede tardar varios minutos.\n"
        f"_No cierres este chat._"
    )
    
    await callback_query.edit_message_text(progress_text)
    
    banned_count = 0
    failed_count = 0
    
    for user in inactive_users:
        try:
            from datetime import datetime
            last_active_dt = datetime.strptime(user['last_active'], '%Y-%m-%d %H:%M:%S')
            days_inactive = (datetime.now() - last_active_dt).days
            
            reason = f"Inactivo 3+ días ({days_inactive}d) - Sin foto/video"
            await remove_approved_user(user['user_id'])
            registry_unregister(user['user_id'])
            
            try:
                protect = PROTECT_CONTENT
                await bot.send_message(
                    user['user_id'],
                    f"🚪 **Removido por inactividad**\n\n"
                    f"Fuiste removido de la lista de difusión por no enviar fotos o videos en más de 3 días.\n\n"
                    f"Puedes intentar volver usando /start (si hay cupos disponibles).\n\n"
                    f"⚠️ Solo fotos y videos cuentan como actividad.",
                    protect_content=protect
                )
            except Exception:
                pass
            
            banned_count += 1
            
            if SEND_DELAY > 0:
                await asyncio.sleep(SEND_DELAY)
            
        except Exception as e:
            logger.error(f"Error banning user {user['user_id']}: {e}")
            failed_count += 1
    
    admin_log = (
        f"🚨 **REMOCIÓN MASIVA EJECUTADA**\n\n"
        f"👮 **Admin:** {callback_query.from_user.first_name} [`{callback_query.from_user.id}`]\n"
        f"📊 **Removidos:** {banned_count} usuarios\n"
        f"❌ **Fallidos:** {failed_count} usuarios\n"
        f"📝 **Motivo:** Inactivos 3+ días (sin foto/video)\n"
        f"🕐 **Hora:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    
    all_users = await get_all_approved_users()
    for user in all_users:
        if user['is_admin'] and user['user_id'] != callback_query.from_user.id:
            try:
                await bot.send_message(user['user_id'], admin_log, protect_content=False)
            except Exception:
                pass
    
    final_text = (
        f"✅ **Remoción masiva completada**\n\n"
        f"📊 **Resultados:**\n"
        f"✅ Removidos: **{banned_count}** usuarios\n"
        f"❌ Fallidos: **{failed_count}** usuarios\n\n"
        f"📝 **Motivo:** Inactivos 3+ días (sin foto/video)\n\n"
        f"Todos los admins han sido notificados."
    )
    
    await callback_query.edit_message_text(final_text)
    logger.info(f"🚨 MASS BAN: Admin {callback_query.from_user.id} removed {banned_count} inactive users")


@bot.on_callback_query(filters.regex(r"^scan_cancel$"))
async def scan_cancel_callback(client, callback_query):
    """Cancel the operation"""
    await callback_query.answer("❌ Operación cancelada", show_alert=True)
    
    cancel_text = (
        "❌ **Operación cancelada**\n\n"
        "No se baneó a ningún usuario.\n\n"
        "Usa `/scan` de nuevo para revisar usuarios inactivos."
    )
    
    await callback_query.edit_message_text(cancel_text)


@bot.on_message(filters.command("erase") & filters.private)
async def erase_handler(client, message):
    """Delete broadcast message for all users (reply required)"""
    user_details = await get_user_details(message.from_user.id)
    if not user_details or not user_details['is_admin']:
        return await message.reply("🚫 Solo admins")
    
    if not message.reply_to_message:
        return await message.reply(
            "❌ **Uso:**\n"
            "• Responde a un mensaje del broadcast y usa:\n"
            "• `/erase` - Eliminar en silencio\n"
            "• `/erase <motivo>` - Eliminar y notificar a usuarios"
        )
    
    # Extract reason (if provided)
    reason = " ".join(message.command[1:]) if len(message.command) > 1 else None
    
    replied_msg = message.reply_to_message
    replied_msg_id = replied_msg.id
    
    # Look up original message info in database
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT original_sender_id, original_message_id
        FROM message_mapping
        WHERE broadcast_message_id = ? AND target_user_id = ?
    """, (replied_msg_id, message.from_user.id))
    result = cursor.fetchone()
    conn.close()
    
    if not result:
        return await message.reply("❌ Este mensaje no es del broadcast o no está en la base de datos")
    
    original_sender_id, original_message_id = result
    
    # Find all users who received this message
    recipients = await get_all_broadcast_recipients(original_sender_id, original_message_id)
    
    if not recipients:
        return await message.reply("❌ No se encontraron destinatarios para este mensaje")
    
    deleted = 0
    failed = 0
    
    if reason:
        status_msg = await message.reply(f"🗑️ Eliminando y notificando a {len(recipients)} usuarios...")
    else:
        status_msg = await message.reply(f"🗑️ Eliminando mensaje para {len(recipients)} usuarios...")
    
    for recipient in recipients:
        try:
            # Delete the message
            await bot.delete_messages(
                chat_id=recipient['user_id'],
                message_ids=recipient['message_id']
            )
            deleted += 1
            
            # If reason provided, send notification
            if reason:
                try:
                    notification = (
                        f"🗑️ **Contenido eliminado**\n\n"
                        f"Se eliminó un mensaje del broadcast.\n\n"
                        f"**Motivo:** {reason}"
                    )
                    recv_details = await get_user_details(recipient['user_id'])
                    protect = PROTECT_CONTENT and not (recv_details and (recv_details.get('is_admin') or recv_details.get('is_vip')))
                    await bot.send_message(recipient['user_id'], notification, protect_content=protect)
                except Exception:
                    pass
            
            if SEND_DELAY > 0:
                await asyncio.sleep(SEND_DELAY)
        except Exception as e:
            failed += 1
            logger.debug(f"Could not delete for {recipient['user_id']}: {e}")
    
    # Delete original message from admin as well
    try:
        await replied_msg.delete()
    except Exception:
        pass
    
    if reason:
        await status_msg.edit_text(
            f"✅ **Mensaje eliminado y usuarios notificados**\n\n"
            f"📨 Eliminado para: {deleted} usuarios\n"
            f"❌ Fallos: {failed} usuarios\n"
            f"📝 Motivo enviado: {reason}"
        )
        logger.info(f"🗑️ ERASE: Admin {message.from_user.id} deleted broadcast {original_message_id} - Reason: {reason}")
    else:
        await status_msg.edit_text(
            f"✅ **Mensaje eliminado (silencioso)**\n\n"
            f"📨 Eliminado para: {deleted} usuarios\n"
            f"❌ Fallos: {failed} usuarios"
        )
        logger.info(f"🗑️ ERASE: Admin {message.from_user.id} deleted broadcast {original_message_id} (silent)")

# ============================================================================
# /renv - Resend media/album to the user who runs it (VIP, Admin, tag-unlocked)
# ============================================================================
@bot.on_message(filters.command("renv") & filters.private)
async def renv_handler(client, message):
    """Resends broadcast media/album to the user who used the command (reply required)."""
    user_id = message.from_user.id
    if not message.reply_to_message:
        return await message.reply(
            "❌ **Cómo usar /renv**\n\n"
            "Responde a un media o álbum del broadcast y envía /renv.\n\n"
            "El bot te reenviará ese contenido solo a ti (para que puedas guardarlo).\n\n"
            "⚠️ Solo VIPs y Admins pueden usar esto."
        )

    reply = message.reply_to_message
    bot_me = await client.get_me()
    if reply.from_user and reply.from_user.id != bot_me.id:
        return await message.reply("❌ Responde a un mensaje enviado por el bot (media del broadcast).")

    details = await get_user_details(user_id)
    if not details:
        return await message.reply("❌ No estás registrado. Usa /start")

    is_admin = (user_id in ADMIN_IDS) or details.get("is_admin")
    is_vip = details.get("is_vip")
    if not (is_admin or is_vip):
        return await message.reply(
            "❌ Solo VIPs y Admins pueden usar esto.\n\nUsa /me para ver tu estado."
        )

    has_media = reply.photo or reply.video or reply.document or reply.animation or reply.audio
    if not has_media and not reply.media_group_id:
        return await message.reply("❌ Responde a una foto, video, documento, audio o álbum.")

    try:
        if reply.media_group_id:
            msgs = await reply.get_media_group()
            media_list = []
            base_caption = (reply.caption or "").strip()[:1024]
            for idx, m in enumerate(msgs):
                cap = base_caption if idx == 0 else ""
                if m.photo:
                    media_list.append(InputMediaPhoto(m.photo.file_id, caption=cap))
                elif m.video:
                    media_list.append(InputMediaVideo(m.video.file_id, caption=cap))
                elif m.document:
                    media_list.append(InputMediaDocument(m.document.file_id, caption=cap))
                elif m.audio:
                    media_list.append(InputMediaAudio(m.audio.file_id, caption=cap))
            if media_list:
                ALBUM_MAX = 10
                for chunk_start in range(0, len(media_list), ALBUM_MAX):
                    chunk = media_list[chunk_start:chunk_start + ALBUM_MAX]
                    await client.send_media_group(user_id, media=chunk, protect_content=False)
                    if chunk_start + ALBUM_MAX < len(media_list) and SEND_DELAY > 0:
                        await asyncio.sleep(SEND_DELAY)
        else:
            await reply.copy(user_id, protect_content=False)

        await message.reply("✅ **¡Reenviado!** El contenido se te ha enviado.")
    except Exception as e:
        logger.error(f"renv error for {user_id}: {e}")
        await message.reply("❌ Error al reenviar. Intenta de nuevo.")

# ============================================================================
# AUTO BROADCAST
# ============================================================================
@bot.on_message(
    filters.private &
    ~filters.command([
        "start", "rules", "stats", "addadmin", "removeadmin",
        "vip", "unvip", "ban", "unban", "me", "list_users",
        "listban", "whois", "showuser", "dupes_stats",
        "approve", "toggleforward", "setrules", "setstart", "listap", "pending", "a", "d",
        "fix", "unfix", "erase", "scan", "report", "renv"
    ])
)
async def auto_broadcast(client, message):
    """Auto broadcast with per-user duplicate detection"""
    uid = message.from_user.id
    logger.info(f"🔵 Message received from user {uid}")
    
    if not await check_group_auth(client, message, uid):
        return
    
    if message.text and message.text.startswith('/'):
        logger.info(f"🚫 Unknown command blocked from user {uid}: {message.text[:30]}")
        return
    
    if await is_user_banned(uid):
        logger.info(f"❌ User {uid} is banned")
        return
    
    if not await is_authorized(uid):
        if uid in ADMIN_IDS:
            await add_approved_user(uid, username=message.from_user.username, first_name=message.from_user.first_name)
            logger.info(f"✅ Admin {uid} automatically authorized")
        else:
            logger.info(f"❌ User {uid} not authorized")
            return await message.reply("🚫 Usa /start primero")
    
    # Update activity only for photo/video
    if message.photo or message.video:
        asyncio.create_task(
            update_user_activity(
                uid,
                username=message.from_user.username,
                first_name=message.from_user.first_name
            )
        )
    
    user_details = await get_user_details(uid)
    is_admin = user_details and user_details['is_admin']
    logger.info(f"👤 User {uid} - Admin: {is_admin}")
    
    if not is_admin:
        if not check_rate_limit(uid):
            logger.info(f"⏰ User {uid} rate limited")
            return await message.reply(
                f"⏰ ¡Estás enviando mensajes muy rápido!\n"
                f"Límite: {RATE_LIMIT} mensajes por {RATE_WINDOW}s"
            )
    
    if message.text and has_forbidden_content(message.text):
        logger.info(f"🚫 User {uid} sent forbidden content (link)")
        await message.delete()
        return await message.reply("🚫 Los enlaces no están permitidos")
    
    if message.photo or message.video or message.document or message.animation or message.audio:
        file_unique_id = None
        media_type = None
        
        if message.photo:
            file_unique_id = message.photo.file_unique_id
            media_type = "photo"
        elif message.video:
            file_unique_id = message.video.file_unique_id
            media_type = "video"
        elif message.document:
            file_unique_id = message.document.file_unique_id
            media_type = "document"
        elif message.animation:
            file_unique_id = message.animation.file_unique_id
            media_type = "animation"
        elif message.audio:
            file_unique_id = message.audio.file_unique_id
            media_type = "audio"
        
        logger.info(f"📎 Media received: {media_type} - unique_id: {file_unique_id} from user {uid}")
        
        if file_unique_id and BLOCK_DUPLICATES:
            should_check = True
            if is_admin and DUPLICATE_EXEMPT_ADMINS:
                should_check = False
                logger.info(f"👑 User {uid} is admin and exempt from duplicate check")
            
            if should_check:
                logger.info(f"🔎 Checking if user {uid} already sent unique_id {file_unique_id}...")
                is_dupe = await is_duplicate_media(uid, file_unique_id, DUPLICATE_WINDOW_HOURS)
                
                if is_dupe:
                    logger.info(f"🚫 DUPLICATE CONFIRMED! User {uid} already sent this media")
                    count = await increment_user_duplicate_count(uid)
                    logger.info(f"📊 User {uid} now has {count} duplicates blocked")
                    await message.delete()
                    schedule_duplicate_notification(uid)
                    return
                else:
                    logger.info(f"✅ Not a duplicate for user {uid}, proceeding with broadcast")
    
    logger.info(f"📤 Scheduling message for broadcast from user {uid}")
    
    if message.media_group_id:
        logger.info(f"📸 Media group detected: {message.media_group_id}")
        _schedule_media(message, is_user_buffer=False)
    elif message.photo or message.video or message.document:
        logger.info(f"📸 Single media detected, buffering")
        _schedule_media(message, is_user_buffer=True)
    elif message.text or message.sticker or message.animation or message.audio or message.voice:
        logger.info(f"📝 Text/other media, adding to queue")
        await broadcast_queue.put({'msgs': [message]})

# ============================================================================
# MAINTENANCE TASKS
# ============================================================================
async def maintenance_task():
    """Maintenance task"""
    start_time = asyncio.get_running_loop().time()
    
    while True:
        await asyncio.sleep(RAM_CLEANUP_INTERVAL)
        collected = gc.collect()
        logger.info(f"🧹 RAM: {collected}")
        
        uptime = asyncio.get_running_loop().time() - start_time
        if uptime > REBOOT_INTERVAL:
            logger.warning("⏰ Restarting")
            os._exit(0)

async def inactivity_checker_task():
    """Check inactivity"""
    while True:
        await asyncio.sleep(INACTIVITY_CHECK_INTERVAL)
        
        try:
            for uid in await get_users_to_warn_71h():
                try:
                    await increment_inactivity_warning(uid)
                    uid_details = await get_user_details(uid)
                    protect = PROTECT_CONTENT and not (uid_details and (uid_details.get('is_admin') or uid_details.get('is_vip')))
                    await bot.send_message(uid, f"⚠️ **Advertencia** - Te queda 1 hora para enviar una foto o video y mantenerte activo en la lista.\n\nPara ser **VIP**, contacta a un admin.", protect_content=protect)
                    
                    await asyncio.sleep(0.1)
                except Exception:
                    pass
            
            for uid in await get_users_to_notify_72h():
                try:
                    uid_details = await get_user_details(uid)
                    protect = PROTECT_CONTENT and not (uid_details and (uid_details.get('is_admin') or uid_details.get('is_vip')))
                    msg_24h = (
                        "⚠️ **Aviso de inactividad / Inactivity warning**\n\n"
                        "🇪🇸 Llevas 24 horas sin enviar fotos o videos. Serás dado de baja del broadcast.\n"
                        "📸 Envía una foto o video para mantenerte activo.\n\n"
                        "🇬🇧 You have been inactive for 24 hours (no photos/videos). You will be removed from the broadcast.\n"
                        "📸 Send a photo or video to stay active.\n\n"
                        "💎 **VIP** no sufre inactividad. Contacta a un admin para ser VIP.\n"
                        "💎 **VIP** members are exempt from inactivity. Contact an admin to become VIP.\n"
                    )
                    await bot.send_message(uid, msg_24h, protect_content=protect)
                    await mark_user_72h_notified(uid)
                    await remove_approved_user(uid)
                    registry_unregister(uid)
                    await asyncio.sleep(0.1)
                except (InputUserDeactivated, UserIsBlocked, PeerIdInvalid):
                    await remove_approved_user(uid)
                    registry_unregister(uid)
                except Exception:
                    pass
        except Exception:
            pass

# ============================================================================
# MAIN
# ============================================================================
if __name__ == "__main__":
    os.makedirs(os.path.dirname(DB_FILE) if os.path.dirname(DB_FILE) else ".", exist_ok=True)
    os.makedirs(BACKUP_DIR, exist_ok=True)
    
    setup_database()
    
    # Load settings from database (persists after docker down/up)
    MANUAL_APPROVAL_MODE = get_manual_approval_mode()
    PROTECT_CONTENT = get_protect_content()
    
    logger.info("=" * 60)
    logger.info("🚀 BOT V3.0 - BotCommandScopeChat FIXED!")
    logger.info("=" * 60)
    logger.info(f"📊 Admins: {len(ADMIN_IDS)}")
    logger.info(f"🔒 Forwarding: {'Disabled' if PROTECT_CONTENT else 'Allowed'}")
    logger.info(f"⚡ Concurrent: {MAX_CONCURRENT}")
    logger.info(f"🚫 Duplicates: {BLOCK_DUPLICATES}")
    logger.info("=" * 60)
    
    from pyrogram import idle
    
    async def main():
        loop = asyncio.get_running_loop()
        loop.create_task(_broadcast_task_worker())
        loop.create_task(maintenance_task())
        loop.create_task(inactivity_checker_task())
        await bot.start()
        me = await bot.get_me()
        logger.info(f"🤖 Bot: @{me.username} (ID: {me.id})")
        await setup_bot_commands()
        await idle()
        await bot.stop()
    
    bot.run(main())
