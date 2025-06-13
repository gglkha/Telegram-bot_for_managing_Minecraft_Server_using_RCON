# -*- coding: utf-8 -*-
# -------------------------------------------------------------------------
# Шаблон многофункционального Telegram-бота для управления сервером Minecraft
# -------------------------------------------------------------------------

import logging
import re
from functools import wraps
from mcrcon import MCRcon
from mcstatus import JavaServer
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)
from telegram.constants import ParseMode
from telegram.error import BadRequest

# =========================================================================
# --- СЕКЦИЯ КОНФИГУРАЦИИ ---
# Отредактируйте эти значения под ваш проект
# =========================================================================

# Токен вашего Telegram-бота, полученный от @BotFather
TELEGRAM_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"

# Список ID пользователей Telegram, которым разрешен доступ к боту
# Чтобы узнать свой ID, напишите боту @userinfobot
ALLOWED_USER_IDS = [123456789, 987654321]

# -- Настройки подключения к Minecraft-серверу --
# IP-адрес или домен вашего сервера
RCON_HOST = "YOUR_SERVER_IP_OR_DOMAIN"
# RCON порт (обычно отличается от игрового)
RCON_PORT = 25575
# RCON пароль из server.properties
RCON_PASSWORD = "YOUR_RCON_PASSWORD"
# Игровой порт сервера (для команды статуса)
GAME_PORT = 25565

# --- КОНФИГУРАЦИЯ ЛОГИРОВАНИЯ ---
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# =========================================================================
# --- СЛУЖЕБНЫЕ УТИЛИТЫ И ДЕКОРАТОРЫ ---
# Эту часть обычно не нужно трогать
# =========================================================================

def escape_markdown(text: str) -> str:
    """Экранирует специальные символы для Telegram MarkdownV2."""
    if not isinstance(text, str): text = str(text)
    escape_chars = r'_*[]()~`>#+=-|{}.!'
    return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', text)

def restricted(func):
    """Декоратор для проверки прав доступа и логирования действий."""
    @wraps(func)
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id
        if user_id not in ALLOWED_USER_IDS:
            logger.warning(f"Неавторизованный доступ от пользователя {user_id}")
            return
        action_name = func.__name__
        if update.callback_query: action_name = update.callback_query.data
        elif update.message: action_name = update.message.text
        logger.info(f"Админ {update.effective_user.first_name} ({user_id}) -> Действие: {action_name}")
        return await func(update, context, *args, **kwargs)
    return wrapped

# =========================================================================
# --- ОСНОВНЫЕ ФУНКЦИИ ВЗАИМОДЕЙСТВИЯ С MINECRAFT ---
# =========================================================================

async def execute_rcon(command: str) -> str:
    """Безопасно выполняет RCON команду и возвращает ответ."""
    try:
        with MCRcon(RCON_HOST, RCON_PASSWORD, port=RCON_PORT, timeout=5) as mcr:
            resp = mcr.command(command)
            # Удаляем цветовые коды Minecraft из ответа для чистоты
            return re.sub(r'§[0-9a-fk-or]', '', resp) if resp else "✅ Команда выполнена."
    except Exception as e:
        logger.error(f"Ошибка RCON: {e}")
        return f"❌ Ошибка RCON: {e}"

async def get_online_players() -> list:
    """Возвращает список ников игроков онлайн."""
    resp = await execute_rcon('list')
    if "There are 0 of a max" in resp or not ":" in resp: return []
    try:
        players_str = resp.split(":", 1)[1]
        return [p.strip() for p in players_str.split(",")]
    except IndexError: return []

# =========================================================================
# --- УПРАВЛЕНИЕ ИНТЕРФЕЙСОМ БОТА (UI) ---
# =========================================================================

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, message_text: str = None):
    """Отображает главное меню, редактируя существующее сообщение или отправляя новое."""
    query = update.callback_query
    keyboard = [
        [InlineKeyboardButton("📊 Статус сервера", callback_data="menu_status")],
        [InlineKeyboardButton("⚙️ Управление сервером", callback_data="menu_server")],
        [InlineKeyboardButton("👥 Управление игроками", callback_data="menu_players")],
        [InlineKeyboardButton("🌍 Управление миром", callback_data="menu_world")],
        [InlineKeyboardButton("ℹ️ О боте", callback_data="menu_about")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    if message_text is None:
        message_text = f"👋 Привет, {escape_markdown(update.effective_user.first_name)}\\! Выберите действие:"
    
    # Редактируем сообщение, если пришел запрос с кнопки, или отправляем новое
    if query:
        try:
            await query.edit_message_text(text=message_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN_V2)
        except BadRequest as e:
            if "Message is not modified" not in str(e): logger.error(f"Ошибка редактирования сообщения: {e}")
    else:
        await update.message.reply_text(text=message_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN_V2)

@restricted
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start. Сбрасывает состояние и показывает главное меню."""
    context.user_data.clear()
    # Устанавливаем постоянные кнопки внизу, если это первый запуск для пользователя
    if 'reply_keyboard_sent' not in context.user_data:
        await update.message.reply_text("Панель управления активирована.", reply_markup=ReplyKeyboardMarkup([["/start"]], resize_keyboard=True))
        context.user_data['reply_keyboard_sent'] = True
    await show_main_menu(update, context)

# =========================================================================
# --- ЛОГИКА РАБОТЫ МЕНЮ ---
# =========================================================================

@restricted
async def button_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Главный маршрутизатор, который обрабатывает все нажатия на inline-кнопки."""
    query = update.callback_query
    await query.answer()
    action, *params = query.data.split(':')

    # Словарь с обработчиками для каждого меню
    menu_handlers = {
        "menu_main": show_main_menu,
        "menu_status": status_handler,
        "menu_server": server_menu_handler,
        "menu_players": players_menu_handler,
        "menu_world": world_menu_handler,
        "menu_about": about_menu_handler,
    }

    if action in menu_handlers:
        await menu_handlers[action](update, context)
    elif action == "action": # Для простых действий в одно нажатие
        await action_handler(update, context, params)
    elif action == "wizard": # Для сложных, пошаговых действий
        await wizard_handler(update, context, params)

# --- Функции, отображающие каждое конкретное подменю ---

async def status_handler(update, context):
    """Показывает подробный статус сервера."""
    try:
        server = JavaServer.lookup(f"{RCON_HOST}:{GAME_PORT}", timeout=3)
        status = await server.async_status()
        players_list = await get_online_players()
        player_text = "\n\n*Игроки онлайн:*\n" + "\n".join([f"\\- ``{p}``" for p in players_list]) if players_list else ""
        motd_escaped = escape_markdown(status.description)
        text = (f"✅ *Сервер ОНЛАЙН*\n\n_{motd_escaped}_\n\n"
                f"⚙️ *Версия:* {escape_markdown(status.version.name)}\n"
                f"👥 *Игроки:* {status.players.online} / {status.players.max}{player_text}")
    except Exception as e:
        logger.error(f"Ошибка статуса: {e}")
        text = f"❌ *Сервер ОФФЛАЙН*\n\nНе удалось получить ответ от `{escape_markdown(RCON_HOST)}:{GAME_PORT}`"
    await show_main_menu(update, context, text)

async def server_menu_handler(update, context):
    """Показывает меню управления сервером."""
    keyboard = [
        [InlineKeyboardButton("⚙️ Рестарт (через /stop)", callback_data="action:confirm:stop")],
        [InlineKeyboardButton("🔌 Список плагинов", callback_data="action:show:plugins")],
        [InlineKeyboardButton("🕹️ Консольный режим", callback_data="wizard:console:start")],
        [InlineKeyboardButton("« Назад", callback_data="menu_main")],
    ]
    await update.callback_query.edit_message_text("⚙️ *Управление сервером*", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN_V2)

async def players_menu_handler(update, context):
    """Показывает меню управления игроками."""
    keyboard = [
        [InlineKeyboardButton("📋 Список игроков онлайн", callback_data="action:show:players_list")],
        [InlineKeyboardButton("⚖️ Наказания (Бан/Кик)", callback_data="wizard:punishment_menu")],
        [InlineKeyboardButton("📜 Белый список (Whitelist)", callback_data="wizard:whitelist_menu")],
        [InlineKeyboardButton("🕹️ Сменить режим игры", callback_data="wizard:gamemode_select_player")],
        [InlineKeyboardButton("👑 Управление правами (OP)", callback_data="wizard:op_menu")],
        [InlineKeyboardButton("✉️ Личное сообщение", callback_data="wizard:msg_select_player")],
        [InlineKeyboardButton("« Назад", callback_data="menu_main")]
    ]
    await update.callback_query.edit_message_text("👥 *Управление игроками*", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN_V2)

async def world_menu_handler(update, context):
    """Показывает меню управления миром."""
    keyboard = [
        [InlineKeyboardButton("⏳ Управление временем", callback_data="wizard:time_menu")],
        [InlineKeyboardButton("🌦️ Управление погодой", callback_data="wizard:weather_menu")],
        [InlineKeyboardButton("« Назад", callback_data="menu_main")],
    ]
    await update.callback_query.edit_message_text("🌍 *Управление миром*", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN_V2)

async def about_menu_handler(update, context):
    """Показывает информацию о боте и его ограничениях."""
    text = (
        "ℹ️ *О боте и возможностях*\n\n"
        "Этот бот использует протокол RCON для отправки команд на сервер\\.\n\n"
        "✅ *Что МОЖНО делать:*\n"
        "\\- Выполнять любые игровые команды\n"
        "\\- Управлять игроками и миром\n"
        "\\- Перезапускать сервер командой `/stop`\n\n"
        "❌ *Что НЕЛЬЗЯ делать через бота:*\n"
        "\\- *Управлять файлами*: Загружать/удалять плагины, моды, карты\\.\n"
        "\\- *Просматривать ресурсы*: Узнать использование RAM/CPU сервера\\.\n\n"
        "_Всё это делается только через FTP/SFTP или панель вашего хостинга\\._"
    )
    keyboard = [[InlineKeyboardButton("« Назад в панель управления", callback_data="menu_main")]]
    await update.callback_query.edit_message_text(text=text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN_V2)

async def action_handler(update, context, params):
    """Обрабатывает простые действия, такие как выполнение команды или запрос подтверждения."""
    action_type, command, *args = params
    query = update.callback_query
    text = ""
    if action_type == "confirm":
        confirm_texts = {'stop': "🚨 *РЕСТАРТ СЕРВЕРА*\n\nБудет выполнена команда `/stop`\\. Большинство хостингов *автоматически перезапустят* сервер после этого\\. Для *полного выключения* используйте панель хостинга\\. Вы уверены?"}
        keyboard = [[InlineKeyboardButton("Да, рестарт", callback_data=f"action:exec:{command}"), InlineKeyboardButton("Отмена", callback_data="menu_server")]]
        await query.edit_message_text(confirm_texts[command], reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN_V2)
        return
    elif action_type == "exec":
        command_str = command + (" " + " ".join(args) if args else "")
        response = await execute_rcon(command_str)
        text = f"Выполнена команда `{escape_markdown(command_str)}`\n\n*Ответ сервера:*\n`{escape_markdown(response)}`"
    elif action_type == "show":
        if command == "plugins":
            response = await execute_rcon("plugins")
            text = f"🔌 *Список плагинов:*\n`{escape_markdown(response)}`\n\n_Управление файлами плагинов доступно только через панель хостинга\\._"
        elif command == "players_list":
            players = await get_online_players()
            text = "*Игроки онлайн:*\n" + "\n".join([f"\\- ``{p}``" for p in players]) if players else "На сервере нет игроков онлайн\\."
    await show_main_menu(update, context, text)

async def wizard_handler(update, context, params):
    """Обрабатывает сложные, многошаговые действия (мастера)."""
    step, *args = params
    query = update.callback_query
    
    # --- Мастер: Консольный режим ---
    if step == "console":
        if args[0] == "start":
            context.user_data['console_mode'] = True
            keyboard = [[InlineKeyboardButton("Выйти из режима консоли", callback_data="wizard:console:stop")]]
            message = await query.edit_message_text("🕹️ *Режим консоли*\n\nОжидание команды\\.\\.\\.", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN_V2)
            context.user_data['console_message_id'] = message.message_id
        elif args[0] == "stop":
            context.user_data.pop('console_mode', None)
            context.user_data.pop('console_message_id', None)
            await show_main_menu(update, context, "✅ Вы вышли из режима консоли")
        return

    # --- Общий мастер для выбора игроков ---
    player_wizards = {
        "op_select_player": ("Выдать OP", "op_exec", "op_prompt", "wizard:op_menu"),
        "deop_select_player": ("Забрать OP", "deop_exec", "deop_prompt", "wizard:op_menu"),
        "msg_select_player": ("Отправить сообщение", "msg_prompt_message", None, "menu_players"),
        "gamemode_select_player": ("Сменить режим игры", "gamemode_select_mode", None, "menu_players"),
        "kick_select_player": ("Кикнуть игрока", "kick_exec", None, "wizard:punishment_menu"),
        "ban_select_player": ("Забанить игрока", "ban_prompt_reason", "ban_prompt", "wizard:punishment_menu"),
        "whitelist_add_select_player": ("Добавить в WL", "whitelist_add_exec", "whitelist_add_prompt", "wizard:whitelist_menu"),
        "whitelist_remove_select_player": ("Удалить из WL", "whitelist_remove_exec", "whitelist_remove_prompt", "wizard:whitelist_menu")
    }
    if step in player_wizards:
        title, exec_action, manual_action, back_menu = player_wizards[step]
        players = await get_online_players()
        keyboard = [[InlineKeyboardButton(p, callback_data=f"wizard:{exec_action}:{p}")] for p in players]
        if not players:
            prompt_text = f"Нет игроков онлайн для действия '{escape_markdown(title)}'\\. Вы можете ввести ник вручную\\."
            keyboard = [[InlineKeyboardButton("Ввести ник вручную", callback_data=f"wizard:{manual_action}") if manual_action else None], [InlineKeyboardButton("« Назад", callback_data=back_menu)]]
            keyboard = [row for row in keyboard if row[0] is not None] # Убираем пустые кнопки
            await query.edit_message_text(prompt_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN_V2)
            return

        if manual_action: keyboard.append([InlineKeyboardButton("Ввести ник вручную", callback_data=f"wizard:{manual_action}")])
        keyboard.append([InlineKeyboardButton("« Назад", callback_data=back_menu)])
        await query.edit_message_text(f"Выберите игрока для действия '{escape_markdown(title)}':", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    # --- Прямые действия с выбранными игроками ---
    if step in ["op_exec", "deop_exec", "kick_exec", "whitelist_add_exec", "whitelist_remove_exec"]:
        player = args[0]
        commands = {"op_exec": "op", "deop_exec": "deop", "kick_exec": "kick", 
                    "whitelist_add_exec": "whitelist add", "whitelist_remove_exec": "whitelist remove"}
        cmd = commands[step]
        response = await execute_rcon(f"{cmd} {player}")
        await show_main_menu(update, context, f"Выполнена команда `{cmd} {escape_markdown(player)}`\n\n*Ответ:*\n`{escape_markdown(response)}`")
    
    # --- Шаги мастеров ---
    elif step == "ban_prompt_reason":
        context.user_data.update({'selected_player': args[0], 'next_action': 'ban_reason'})
        await query.edit_message_text(f"Введите причину бана для игрока ``{escape_markdown(args[0])}`` (или просто отправьте `-` для бана без причины):")
    elif step == "gamemode_select_mode":
        context.user_data['selected_player'] = args[0]
        gamemode_map = {'c': 'creative', 's': 'survival', 'a': 'adventure', 'sp': 'spectator'}
        keyboard = [[InlineKeyboardButton(f"{v.capitalize()} ({k})", callback_data=f"wizard:gamemode_exec:{v}")] for k, v in gamemode_map.items()]
        keyboard.append([InlineKeyboardButton("« Назад", callback_data="wizard:gamemode_select_player")])
        await query.edit_message_text(f"Выберите режим для ``{escape_markdown(args[0])}``:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN_V2)
    elif step == "gamemode_exec":
        mode, player = args[0], context.user_data.pop('selected_player', 'неизвестно')
        response = await execute_rcon(f"gamemode {mode} {player}")
        await show_main_menu(update, context, f"Игроку ``{escape_markdown(player)}`` установлен режим *{escape_markdown(mode)}*\\.\n\n*Ответ:*\n`{escape_markdown(response)}`")
    elif step == "msg_prompt_message":
        context.user_data.update({'selected_player': args[0], 'next_action': 'msg'})
        await query.edit_message_text(f"Введите сообщение для игрока ``{escape_markdown(args[0])}``:")

    # --- Отображение подменю ---
    elif step in ["op_menu", "punishment_menu", "whitelist_menu", "time_menu", "weather_menu"]:
        menu_map = {
            "op_menu": ("👑 *Управление правами OP*", [[InlineKeyboardButton("👑 Выдать OP", callback_data="wizard:op_select_player")], [InlineKeyboardButton("🚫 Забрать OP", callback_data="wizard:deop_select_player")], [InlineKeyboardButton("« Назад", callback_data="menu_players")]]),
            "punishment_menu": ("⚖️ *Управление наказаниями*", [[InlineKeyboardButton("🚷 Кикнуть игрока", callback_data="wizard:kick_select_player")], [InlineKeyboardButton("🚫 Забанить игрока", callback_data="wizard:ban_select_player")], [InlineKeyboardButton("🔓 Разбанить игрока", callback_data="wizard:unban_prompt")], [InlineKeyboardButton("« Назад", callback_data="menu_players")]]),
            "whitelist_menu": ("📜 *Управление Белым списком*", [[InlineKeyboardButton("➕ Добавить в WL", callback_data="wizard:whitelist_add_select_player")], [InlineKeyboardButton("➖ Удалить из WL", callback_data="wizard:whitelist_remove_select_player")], [InlineKeyboardButton("📋 Показать WL", callback_data="action:exec:whitelist list")], [InlineKeyboardButton("▶️ Включить WL", callback_data="action:exec:whitelist on"), InlineKeyboardButton("⏹️ Выключить WL", callback_data="action:exec:whitelist off")], [InlineKeyboardButton("« Назад", callback_data="menu_players")]]),
            "time_menu": ("⏳ *Управление временем*", [[InlineKeyboardButton("Рассвет (0)", callback_data="action:exec:time set 0"), InlineKeyboardButton("Полдень (6000)", callback_data="action:exec:time set 6000")], [InlineKeyboardButton("Закат (12000)", callback_data="action:exec:time set 12000"), InlineKeyboardButton("Ночь (18000)", callback_data="action:exec:time set 18000")], [InlineKeyboardButton("Задать время в тиках", callback_data="wizard:time_prompt_ticks")], [InlineKeyboardButton("« Назад", callback_data="menu_world")]]),
            "weather_menu": ("🌦️ *Управление погодой*", [[InlineKeyboardButton("☀️ Ясно", callback_data="action:exec:weather clear")], [InlineKeyboardButton("💧 Дождь", callback_data="action:exec:weather rain")], [InlineKeyboardButton("⚡️ Гроза", callback_data="action:exec:weather thunder")], [InlineKeyboardButton("« Назад", callback_data="menu_world")]])}
        title, keyboard_layout = menu_map[step]
        await query.edit_message_text(title, reply_markup=InlineKeyboardMarkup(keyboard_layout), parse_mode=ParseMode.MARKDOWN_V2)
    
    # --- Запросы на ввод текста ---
    prompts = {'op_prompt': ('op', "👑 Введите ник для выдачи OP:"), 'deop_prompt': ('deop', "🚫 Введите ник для снятия OP:"),
               'time_prompt_ticks': ('time_ticks', "⏳ Введите время в тиках:"), 'ban_prompt': ('ban', "🚫 Введите ник для бана:"),
               'unban_prompt': ('unban', "🔓 Введите ник для разбана:"), 'whitelist_add_prompt': ('whitelist_add', "➕ Введите ник для добавления в WL:"),
               'whitelist_remove_prompt': ('whitelist_remove', "➖ Введите ник для удаления из WL:")}
    if step in prompts:
        context.user_data['next_action'] = prompts[step][0]
        await query.edit_message_text(escape_markdown(prompts[step][1]))

# =========================================================================
# --- ОБРАБОТЧИК ТЕКСТОВЫХ СООБЩЕНИЙ ---
# =========================================================================
@restricted
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает прямой текстовый ввод для консоли и ответов на запросы."""
    user_text = update.message.text
    # Обработка консольного режима
    if context.user_data.get('console_mode'):
        chat_id = update.effective_chat.id
        message_id = context.user_data.get('console_message_id')
        await update.message.delete()
        if not message_id: return
        response = await execute_rcon(user_text)
        console_text = f"🕹️ *Режим консоли*\n\n_Последняя команда:_\n> ``{escape_markdown(user_text)}``\n\n_Ответ сервера:_\n```\n{escape_markdown(response)}\n```"
        keyboard = [[InlineKeyboardButton("Выйти из режима консоли", callback_data="wizard:console:stop")]]
        try:
            await context.bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=console_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN_V2)
        except BadRequest as e:
            if "Message is not modified" not in str(e): logger.error(f"Ошибка обновления консоли: {e}")
        return

    # Обработка ответов на запросы (wizard)
    if 'next_action' in context.user_data:
        action = context.user_data.pop('next_action')
        command = ""
        if action == 'msg':
            player = context.user_data.pop('selected_player', None)
            if player: command = f"msg {player} {user_text}"
        elif action == 'ban_reason':
            player = context.user_data.pop('selected_player', None)
            reason = user_text if user_text != '-' else ''
            if player: command = f"ban {player} {reason}"
        else:
            actions_map = {'op': f"op {user_text}", 'deop': f"deop {user_text}", 'time_ticks': f"time set {user_text}", 'ban': f"ban {user_text}",
                           'unban': f"pardon {user_text}", 'whitelist_add': f"whitelist add {user_text}", 'whitelist_remove': f"whitelist remove {user_text}"}
            command = actions_map.get(action)
        if command:
            response = await execute_rcon(command)
            try: await update.message.delete()
            except Exception: pass
            await show_main_menu(update, context, f"Выполнено\\.\n\n*Ответ:*\n`{escape_markdown(response)}`")

# =========================================================================
# --- ЗАПУСК БОТА ---
# =========================================================================
def main():
    """Главная функция, которая собирает и запускает бота."""
    application = Application.builder().token(TELEGRAM_TOKEN).build()

    # Регистрация обработчиков
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_router))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    
    logger.info("Бот 'Elite Panel Template' запущен...")
    application.run_polling()

if __name__ == "__main__":
    main()