import json
import os
import logging
import sys
import telegram
import pymysql
import numbers
import hashlib
import string
import random
from datetime import datetime
import datetime
from texts import texts

# Logging is cool!
logger = logging.getLogger()
if logger.handlers:
    for log_handler in logger.handlers:
        logger.removeHandler(log_handler)
logging.basicConfig(level=logging.INFO)

OK_RESPONSE = {
    'statusCode': 200,
    'headers': {'Content-Type': 'application/json'},
    'body': json.dumps('ok')
}
ERROR_RESPONSE = {
    'statusCode': 400,
    'body': json.dumps('Oops, something went wrong!')
}
DB_HOST = os.environ.get('DB_HOST')
DB_USER = os.environ.get('DB_USER')
DB_PASSWORD = os.environ.get('DB_PASSWORD')
DB_DATABASE = os.environ.get('DB_DATABASE')
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
BROADCAST_CODE = os.environ.get('BROADCAST_CODE')
REPLY_CODE = os.environ.get('REPLY_CODE')
CHAT_ID_SALT = os.environ.get('CHAT_ID_SALT')


DATABASE = pymysql.connect(host=DB_HOST, user=DB_USER, password=DB_PASSWORD, database=DB_DATABASE,
                           cursorclass=pymysql.cursors.DictCursor)


def configure_telegram():
    """
    Configures the bot with a Telegram Token.
    Returns a bot instance.
    """
    if not TELEGRAM_TOKEN:
        logger.error('The TELEGRAM_TOKEN must be set')
        raise NotImplementedError

    return telegram.Bot(TELEGRAM_TOKEN)


def db_strip(unsecure_variable):
    special_chars = "&%*;'\"\\\'"
    if isinstance(unsecure_variable, numbers.Number):
        return unsecure_variable
    return ''.join(e for e in unsecure_variable if e not in special_chars)


def db_safer_strip(unsecure_variable):
    return ''.join(e for e in unsecure_variable if e.isalnum() or e.isspace())


def get_chat_hash(chat_id):
    chat_hash = hashlib.sha1((str(chat_id) + CHAT_ID_SALT).encode("ascii")).hexdigest()
    return chat_hash


def get_chat_state(chat_id):
    state = -1
    with DATABASE.cursor() as cur:
        chat_hash = get_chat_hash(chat_id)
        cur.execute(f'SELECT * FROM chats where id="{chat_hash}"')
        if cur.rowcount != 0:
            result = cur.fetchone()
            now = datetime.datetime.now()
            last_update = result["lastUpdate"]
            time_delta = now - last_update
            seconds_delta = time_delta.total_seconds()
            if seconds_delta > 60 * 60 * 2:
                state = 4
            else:
                state = result["state"]
    if state == -1:
        with DATABASE.cursor() as cur:
            cur.execute(f'INSERT INTO chats VALUES("{chat_hash}", 0, now(), "", NULL, 0)')
            DATABASE.commit()
            state = 0
    return state


def set_chat_state(chat_id, new_state):
    if not isinstance(new_state, numbers.Number):
        logger.error(f"Tried to set {new_state} as chat state")
        return
    logger.info(f'Setting state in DB to {new_state}')
    with DATABASE.cursor() as cur:
        chat_hash = get_chat_hash(chat_id)
        cur.execute(f'UPDATE chats SET state={new_state}, lastUpdate=now() WHERE id="{chat_hash}"')
        DATABASE.commit()


def set_chat_user(chat_id, user_id):
    if not isinstance(user_id, numbers.Number):
        logger.error(f"Tried to set {user_id} as user id")
        return
    logger.info(f'Setting user in DB to {user_id}')
    with DATABASE.cursor() as cur:
        chat_hash = get_chat_hash(chat_id)
        cur.execute(f'UPDATE chats SET affiliatedUser={user_id}, lastUpdate=now() WHERE id="{chat_hash}"')
        DATABASE.commit()


# insecure. Usages should be checked
def set_chat_context(chat_id, new_context):
    encoded_context = new_context.replace("\'", "\\\'")
    with DATABASE.cursor() as cur:
        chat_hash = get_chat_hash(chat_id)
        cur.execute(f'UPDATE chats SET context=\'{encoded_context}\', lastUpdate=now() WHERE id="{chat_hash}"')
        DATABASE.commit()


def get_chat_context(chat_id):
    context = {}
    with DATABASE.cursor() as cur:
        chat_hash = get_chat_hash(chat_id)
        cur.execute(f'SELECT * FROM chats where id="{chat_hash}"')
        if cur.rowcount != 0:
            result = cur.fetchone()
            context = json.loads(result['context'])
    return context


def increment_child_count(user_id):
    if not isinstance(user_id, numbers.Number):
        logger.error(f"Tried to provide {user_id} as user id")
        return
    with DATABASE.cursor() as cur:
        cur.execute(f'SELECT * FROM users where id={user_id}')
        if cur.rowcount == 1:
            user = cur.fetchone()
            kid_count = user['kidCount']
            if not isinstance(kid_count, numbers.Number):
                kid_count = 0
            kid_count = kid_count + 1
            cur.execute(f'UPDATE users SET kidCount={kid_count} WHERE id={user_id}')
            DATABASE.commit()
            parent = user['parentUserId']
            if isinstance(parent, numbers.Number):
                increment_child_count(parent)


def decrement_child_count(user_id):
    if not isinstance(user_id, numbers.Number):
        logger.error(f"Tried to provide {user_id} as user id")
        return
    with DATABASE.cursor() as cur:
        cur.execute(f'SELECT * FROM users where id={user_id}')
        if cur.rowcount == 1:
            user = cur.fetchone()
            kid_count = user['kidCount']
            if not isinstance(kid_count, numbers.Number):
                kid_count = 0
            kid_count = kid_count - 1
            cur.execute(f'UPDATE users SET kidCount={kid_count} WHERE id={user_id}')
            DATABASE.commit()
            parent = user['parentUserId']
            if isinstance(parent, numbers.Number):
                increment_child_count(parent)


# insecure. Usages should be checked
def update_password(chat_id, new_password_hash):
    with DATABASE.cursor() as cur:
        chat_hash = get_chat_hash(chat_id)
        cur.execute(f'UPDATE users SET password="{new_password_hash}" WHERE '
                    f'id = (SELECT affiliatedUser FROM chats WHERE id="{chat_hash}");')
    DATABASE.commit()


def update_user_last_login(user_id):
    if not isinstance(user_id, numbers.Number):
        logger.error(f"Tried to provide {user_id} as user id")
        return
    with DATABASE.cursor() as cur:
        cur.execute(f'UPDATE users SET last_login=now() WHERE id = {user_id};')
    DATABASE.commit()


def increase_chat_user_creation(chat_id):
    with DATABASE.cursor() as cur:
        chat_hash = get_chat_hash(chat_id)
        cur.execute(f'UPDATE chats SET createdUsercount = createdUsercount + 1 WHERE id = "{chat_hash}";')
    DATABASE.commit()


def get_current_user(chat_id):
    with DATABASE.cursor() as cur:
        chat_hash = get_chat_hash(chat_id)
        cur.execute(f'SELECT users.* FROM users INNER JOIN chats ON users.id = chats.affiliatedUser'
                    f' WHERE chats.id="{chat_hash}";')
        user = cur.fetchone()
    return user


def get_town_name(town_key):
    if not isinstance(town_key, numbers.Number):
        logger.error(f"Tried to provide {town_key} as town id")
        return
    with DATABASE.cursor() as cur:
        cur.execute(f'SELECT t2.town from towns t1 inner join towns t2 on t1.key_idx = t2.id WHERE t1.id = {town_key};')
        town = cur.fetchone()
    return town['town']


def get_unused_invite_count(user_id):
    if not isinstance(user_id, numbers.Number):
        logger.error(f"Tried to provide {user_id} as user_id")
        return
    with DATABASE.cursor() as cur:
        cur.execute(f'select count(*) num from invites i where i.usedBy is null and i.createdBy = {user_id};')
        town = cur.fetchone()
    return town['num']


def try_to_delete_message(bot, chat_id, update):
    try:
        bot.delete_message(chat_id, update.message.message_id)
    except:
        logger.info("Could not delete the message")
    finally:
        logger.info("Tried to delete the message")


def chat_reaction0(bot, update):
    text = update.message.text
    if text == "Подробности":
        context = {'return': 0}
        chat_id = update.message.chat.id
        set_chat_context(chat_id, json.dumps(context))
        return 3
    elif text == "Вход":
        return 1
    elif text == "Регистрация":
        chat_id = update.message.chat.id
        with DATABASE.cursor() as cur:
            chat_hash = get_chat_hash(chat_id)
            cur.execute(f'SELECT * FROM chats where id="{chat_hash}"')
            chat = cur.fetchone()
            if chat['createdUserCount'] > 1:
                return 28
        return 35
    else:
        return 0


def chat_reaction1(bot, update):
    username = db_strip(update.message.text.strip())
    chat_id = update.message.chat.id
    try_to_delete_message(bot, chat_id, update)
    with DATABASE.cursor() as cur:
        cur.execute(f'SELECT * FROM users where login="{username}"')
        if cur.rowcount == 0:
            return 13
        user = cur.fetchone()
        chat_id = update.message.chat.id
    allow_free_login_till = user['passwordlessEntryAllowedTill']
    if allow_free_login_till is not None:
        if datetime.datetime.now() < allow_free_login_till:
            set_chat_user(chat_id, user['id'])
            update_user_last_login(user['id'])
            return 40
    context = {'user': user['id'], 'hash': user['password']}
    set_chat_context(chat_id, json.dumps(context))
    return 14


def chat_reaction2(bot, update):
    invitation_key = db_strip(update.message.text.lower().strip())
    with DATABASE.cursor() as cur:
        cur.execute(f'SELECT * FROM invites where invite="{invitation_key}"')
        if cur.rowcount > 0:
            result = cur.fetchone()
            used_by = result['usedBy']
            if isinstance(used_by, numbers.Number):
                return 6
            context = {'invite': result['id']}
            chat_id = update.message.chat.id
            set_chat_context(chat_id, json.dumps(context))
            return 44
        else:
            return 5


def chat_reaction3(bot, update):
    text = update.message.text
    if text == texts['btn_about_1']:
        return 3
    if text == texts['btn_about_2']:
        return 41
    if text == texts['btn_about_3']:
        return 42
    if text == texts['btn_about_4']:
        return 43
    if text == texts['btn_about_5']:
        return 46
    if text == texts['btn_about_6']:
        return 47
    if text == texts['btn_about_7']:
        return 48
    if text == texts['btn_about_8']:
        return 49
    if text == texts['btn_about_9']:
        return 50
    if text == texts['btn_about_10']:
        return 51
    chat_id = update.message.chat.id
    context = get_chat_context(chat_id)
    if context['return'] is None:
        return 0
    else:
        state = context['return']
    if state == 0:
        return 0
    else:
        return 11


def chat_reaction4(bot, update):
    reply = texts['safety_logout']
    chat_id = update.message.chat.id
    bot.sendMessage(chat_id=chat_id, text=reply)
    set_chat_context(chat_id, "")
    return 0


def chat_reaction7(bot, update):
    username = db_strip(update.message.text.strip())
    with DATABASE.cursor() as cur:
        cur.execute(f'SELECT * FROM users where login="{username}"')
        if cur.rowcount > 0:
            return 9
        chat_id = update.message.chat.id
        context = get_chat_context(chat_id)
        context['login'] = username
        set_chat_context(chat_id, json.dumps(context))
        return 8


def chat_reaction8(bot, update):
    password = update.message.text.strip()
    password_hash = hashlib.sha1(password.encode("utf-8")).hexdigest()
    chat_id = update.message.chat.id
    try_to_delete_message(bot, chat_id, update)
    context = get_chat_context(chat_id)
    context['passhash'] = password_hash
    set_chat_context(chat_id, json.dumps(context))
    return 10


def chat_reaction10(bot, update):
    password = update.message.text.strip()
    password_hash = hashlib.sha1(password.encode("utf-8")).hexdigest()
    chat_id = update.message.chat.id
    try_to_delete_message(bot, chat_id, update)
    context = get_chat_context(chat_id)
    prevhash = context['passhash']
    if password_hash != prevhash:
        return 12
    with DATABASE.cursor() as cur:
        invite = db_safer_strip(context['invite'])
        cur.execute(f'SELECT * FROM invites WHERE id={invite}')
        invite_object = cur.fetchone()
    inviting_user_id = invite_object['createdBy']
    with DATABASE.cursor() as cur:
        login = context['login']
        town = context['townId']
        parent = "NULL"
        if isinstance(inviting_user_id, numbers.Number):
            parent = inviting_user_id
        cur.execute(
            f'INSERT INTO users (login, password, last_login, parentUserId, kidCount, town, createdOn) VALUES("{login}", "{password_hash}", now(), {parent}, 0, {town}, CURDATE())')
        DATABASE.commit()
        new_user_id = cur.lastrowid
    with DATABASE.cursor() as cur:
        cur.execute(f'UPDATE invites SET usedBy={new_user_id}, usedOn=now() WHERE id={invite}')
        DATABASE.commit()
    increment_child_count(parent)
    for x in range(2):
        with DATABASE.cursor() as cur:
            invite_code = ''.join(random.choice(string.ascii_lowercase + string.digits) for _ in range(10))
            cur.execute(
                f'INSERT INTO invites (invite, createdBy, usedBy, createdOn, usedOn) VALUES ("{invite_code}", {new_user_id}, NULL, now(), NULL)')
            DATABASE.commit()
    set_chat_context(chat_id, "")
    set_chat_user(chat_id, new_user_id)
    increase_chat_user_creation(chat_id)
    send_password_writedown_reminder(bot, chat_id)
    return 11


def chat_reaction11(bot, update):
    text = update.message.text
    if text == "Мои приглашения":
        return 16
    elif text == "Общая картина":
        return 17
    elif text == "Мой город":
        return 18
    elif text == "Сменить пароль":
        return 19
    elif text == "Выход":
        return 0
    elif text == "Подробности":
        context = {'return': 11}
        chat_id = update.message.chat.id
        set_chat_context(chat_id, json.dumps(context))
        return 3
    elif text == "Обратная связь":
        return 32
    elif text == "Удалить аккаунт":
        return 29
    else:
        return 11


def chat_reaction14(bot, update):
    password = update.message.text.strip()
    chat_id = update.message.chat.id
    try_to_delete_message(bot, chat_id, update)
    password_hash = hashlib.sha1(password.encode("utf-8")).hexdigest()
    context = get_chat_context(chat_id)
    if context['hash'] == password_hash:
        set_chat_user(chat_id, context['user'])
        update_user_last_login(context['user'])
        return 11
    return 15


def chat_reaction16(bot, update):
    text = update.message.text
    if text != "Разрешить приглашенным входить без пароля в течение 5 минут":
        return 11
    user = get_current_user(update.message.chat.id)
    with DATABASE.cursor() as cur:
        allow_till = datetime.datetime.now() + datetime.timedelta(minutes=6)
        cur.execute(f'UPDATE users SET passwordlessEntryAllowedTill=\'{allow_till.strftime("%Y-%m-%d %H:%M:%S")}\' '
                    f'WHERE parentUserId={user["id"]}')
        DATABASE.commit()
    return 39


def chat_reaction18(bot, update):
    text = update.message.text
    if text == "Сменить":
        return 23
    return 11


def chat_reaction19(bot, update):
    text = update.message.text
    if text == "Да":
        return 20
    return 11


def chat_reaction20(bot, update):
    password = update.message.text.strip()
    password_hash = hashlib.sha1(password.encode("utf-8")).hexdigest()
    chat_id = update.message.chat.id
    try_to_delete_message(bot, chat_id, update)
    context = {'passhash': password_hash}
    set_chat_context(chat_id, json.dumps(context))
    return 21


def chat_reaction21(bot, update):
    password = update.message.text.strip()
    password_hash = hashlib.sha1(password.encode("utf-8")).hexdigest()
    chat_id = update.message.chat.id
    try_to_delete_message(bot, chat_id, update)
    context = get_chat_context(chat_id)
    if context['passhash'] == password_hash:
        set_chat_context(chat_id, "")
        update_password(chat_id, password_hash)
        return 25
    else:
        return 22


def chat_reaction23(bot, update):
    town_name = db_safer_strip(update.message.text.strip().capitalize())
    town_id = None
    user = get_current_user(update.message.chat.id)
    with DATABASE.cursor() as cur:
        cur.execute(f'SELECT * FROM towns WHERE town="{town_name}"')
        if cur.rowcount > 0:
            town = cur.fetchone()
            town_id = town['id']
    if town_id is None:
        return 34

    with DATABASE.cursor() as cur:
        cur.execute(f'UPDATE users SET town={town_id} WHERE id={user["id"]}')
        DATABASE.commit()
    return 24


def chat_reaction26(bot, update):
    answer = update.message.text.strip()
    answer_int = None
    if answer.isdigit():
        answer_int = int(answer)
    chat_id = update.message.chat.id
    context = get_chat_context(chat_id)
    if context['answer'] == answer_int:
        return 2
    else:
        return 27


def chat_reaction29(bot, update):
    text = update.message.text.lower()
    if text != "удалить":
        return 11
    chat_id = update.message.chat.id
    user = get_current_user(chat_id)
    if user['kidCount'] < 2:
        with DATABASE.cursor() as cur:
            cur.execute(f'UPDATE invites SET usedBy = NULL, usedOn = NULL WHERE usedBy = {user["id"]}')
            DATABASE.commit()
        decrement_child_count(user['parentUserId'])
    with DATABASE.cursor() as cur:
        cur.execute(f'UPDATE chats SET affiliatedUser = NULL, createdUserCount = 0 WHERE affiliatedUser = {user["id"]}')
        DATABASE.commit()
    with DATABASE.cursor() as cur:
        cur.execute(f'DELETE FROM users WHERE id = {user["id"]}')
        DATABASE.commit()
    return 30


def chat_reaction31(bot, update):
    text = update.message.text
    if text == "Отмена":
        return 0
    # with DATABASE.cursor() as cur:
    #     cur.execute(f'SELECT * FROM chats')
    #     chats = cur.fetchall()
    # success = 0
    # fail = 0
    # for chat in chats:
    #     try:
    #         bot.sendMessage(chat_id=chat['id'], text=text)
    #         success += 1
    #     except:
    #         fail += 1
    chat_id = update.message.chat.id
    # reply = f"Сообщение разослано {fail + success} раз. {100 * success / (success + fail):.2f}% успешно"
    # bot.sendMessage(chat_id=chat_id, text=reply)
    reply = f"Массовая рассылка отключена по соображениям безопасности"
    bot.sendMessage(chat_id=chat_id, text=reply)
    return 0


def chat_reaction32(bot, update):
    text = update.message.text
    if len(text) > 1024:
        text = text[-1024:]
    if text == "Назад":
        return 11
    text = db_strip(text)
    user = get_current_user(update.message.chat.id)
    with DATABASE.cursor() as cur:
        cur.execute(f"INSERT INTO million.tickets (user_id, creation_date, question, answer, is_answered)"
                    f" VALUES({user['id']}, now(), '{text}', NULL, 0);")
        DATABASE.commit()
    return 11


def chat_reaction33(bot, update):
    text = update.message.text
    if len(text) > 1024:
        text = text[-1024:]
    if text == "Назад":
        return 0
    if text == "Ответ не нужен":
        text = ''
    context = get_chat_context(update.message.chat.id)
    with DATABASE.cursor() as cur:
        cur.execute(f"SELECT * FROM tickets WHERE id={context['ticket']}")
        ticket = cur.fetchone()
    text = db_strip(text)
    with DATABASE.cursor() as cur:
        cur.execute(f'UPDATE tickets SET answer="{text}", is_answered=1 WHERE id={context["ticket"]}')
        DATABASE.commit()

    # with DATABASE.cursor() as cur:
    #     cur.execute(f'SELECT * FROM chats WHERE affiliatedUser={ticket["user_id"]}')
    #    if cur.rowcount != 0:
    #        author_chat = cur.fetchone()
    #        bot.sendMessage(chat_id=author_chat['id'], text="Получен ответ на Ваш вопрос")
    return 33


def chat_reaction35(bot, update):
    text = update.message.text
    if text == "Наши требования":
        return 38
    if text != "Согласен / Согласна":
        return 0
    return 36


def chat_reaction36(bot, update):
    text = update.message.text
    if text != "Согласен / Согласна":
        return 0
    return 37


def chat_reaction37(bot, update):
    text = update.message.text
    if text != "Согласен / Согласна":
        return 0
    return 26


def chat_reaction44(bot, update):
    town_name = db_safer_strip(update.message.text.strip().capitalize())
    town_id = None
    with DATABASE.cursor() as cur:
        cur.execute(f'SELECT * FROM towns WHERE town="{town_name}"')
        if cur.rowcount > 0:
            town = cur.fetchone()
            town_id = town['id']
    if town_id is None:
        return 45
    chat_id = update.message.chat.id
    context = get_chat_context(chat_id)
    context['townId'] = town_id
    set_chat_context(chat_id, json.dumps(context))
    return 7


def chat_output0(bot, chat_id, update):
    reply = texts[0]
    send_message_with_intro_keyboard(bot, chat_id, reply)


def chat_output1(bot, chat_id, update):
    reply = texts[1]
    bot.sendMessage(chat_id=chat_id, text=reply)


def chat_output2(bot, chat_id, update):
    reply = texts[2]
    bot.sendMessage(chat_id=chat_id, text=reply)


def chat_output3(bot, chat_id, update):
    reply = texts[3]
    send_message_with_about_keyboard(bot, chat_id, reply, 'Markdown')


def chat_output5(bot, chat_id, update):
    reply = texts[5]
    send_message_with_intro_keyboard(bot, chat_id, reply)
    set_chat_state(chat_id, 0)


def chat_output6(bot, chat_id, update):
    reply = texts[6]
    send_message_with_intro_keyboard(bot, chat_id, reply)
    set_chat_state(chat_id, 0)


def chat_output7(bot, chat_id, update):
    reply = texts[7]
    bot.sendMessage(chat_id=chat_id, text=reply)


def chat_output8(bot, chat_id, update):
    bot.delete_message(chat_id, update.message.message_id)
    reply = texts[8]
    bot.sendMessage(chat_id=chat_id, text=reply)


def chat_output9(bot, chat_id, update):
    reply = texts[9]
    bot.sendMessage(chat_id=chat_id, text=reply)
    set_chat_state(chat_id, 7)


def chat_output10(bot, chat_id, update):
    reply = texts[10]
    bot.sendMessage(chat_id=chat_id, text=reply)


def chat_output11(bot, chat_id, update):
    reply = texts[11]
    send_message_with_logged_in_keyboard(bot, chat_id, reply)


def chat_output12(bot, chat_id, update):
    reply = texts[12]
    bot.sendMessage(chat_id=chat_id, text=reply)
    set_chat_state(chat_id, 8)


def chat_output13(bot, chat_id, update):
    reply = texts[13]
    send_message_with_intro_keyboard(bot, chat_id, reply)
    set_chat_state(chat_id, 0)
    logger.info('Message sent')


def chat_output14(bot, chat_id, update):
    reply = texts[14]
    bot.sendMessage(chat_id=chat_id, text=reply)


def chat_output15(bot, chat_id, update):
    reply = texts[15]
    send_message_with_intro_keyboard(bot, chat_id, reply)
    set_chat_state(chat_id, 0)


def chat_output16(bot, chat_id, update):
    not_fulfilling_sons = []
    with DATABASE.cursor() as cur:
        chat_hash = get_chat_hash(chat_id)
        cur.execute(f'select invites.invite, invites.createdOn, invites.usedOn, users.login, users.kidCount, '
                    f'count(i2.id) as usedInvites from invites inner join chats '
                    f'on invites.createdBy = chats.affiliatedUser left join users on '
                    f'invites.usedBy = users.id left join invites i2'
                    f' on i2.createdBy = users.id and i2.usedBy is not null '
                    f'where chats.id="{chat_hash}" '
                    f'group by invites.invite, invites.createdOn, invites.usedOn, users.login, users.kidCount')
        invite_objects = cur.fetchall()
    total_unused = 0
    total_used = 0
    unused_invite_codes = []
    for invite in invite_objects:
        user = invite['login']
        use_hint = ''
        if user is None:
            use_by_date = invite['createdOn']
            use_by_date = use_by_date + datetime.timedelta(days=3)
            use_hint = f'Рекоммендуем использовать до {use_by_date.strftime("%Y-%m-%d")}'
            total_unused += 1
            unused_invite_codes.append(f'{invite["invite"]}\n')
        else:
            total_used += 1
            if invite['usedInvites'] < 2:
                not_fulfilling_sons.append(invite['login'])
    if total_unused == 0:
        reply = texts['thanks_for_inviting']
    else:
        reply = 'Мои неиспользованные приглашения:\n'
        bot.sendMessage(chat_id=chat_id, text=reply)
        for invite in unused_invite_codes:
            bot.sendMessage(chat_id=chat_id, text=invite)
        reply = use_hint
        reply += '\nНе приглашайте людей, которым вы не доверяете полностью!'
        bot.sendMessage(chat_id=chat_id, text=reply)
        reply = texts['dont_forget_to_invite']
    if total_used == 0:
        send_message_with_logged_in_keyboard(bot, chat_id, reply)
        set_chat_state(chat_id, 11)
    else:
        if len(not_fulfilling_sons) > 0:
            reply2 = texts['sons_not_inviting'].format(", ".join(not_fulfilling_sons))
            send_message_with_logged_in_keyboard(bot, chat_id, reply2)
        kb = [[telegram.KeyboardButton("Назад")],
              [telegram.KeyboardButton("Разрешить приглашенным входить без пароля в течение 5 минут")]]
        kb_markup = telegram.ReplyKeyboardMarkup(kb, one_time_keyboard=True)
        bot.sendMessage(chat_id=chat_id, text=reply, reply_markup=kb_markup)


def chat_output17(bot, chat_id, update):
    # send_current_state_image(bot, chat_id)
    with DATABASE.cursor() as cur:
        cur.execute("SELECT count(*) AS numUsers FROM users")
        count = cur.fetchone()
    total = count['numUsers']
    target = 140000000 * 0.04
    user = get_current_user(chat_id)
    in_town = None
    if user['town'] is not None:
        with DATABASE.cursor() as cur:
            town = user['town']
            cur.execute(f'SELECT count(*) as inTown from users where town = {town};')
            in_town = cur.fetchone()['inTown']
        with DATABASE.cursor() as cur:
            town = user['town']
            cur.execute(f'SELECT * from towns WHERE id = {town};')
            town = cur.fetchone()
    percentage = total / (0.01 * target)
    reply = f'Сейчас в системе зарегистрировано {total} пользователей. Это {percentage:.2f}% от {target:.0f}.\n'
    reply += f'Из этих людей {user["kidCount"]} привели вы и те, кого вы пригласили.\n'
    if in_town is not None:
        reply += f'В вашем городе зарегистрировано {in_town}'
        if town is not None and town['population'] is not None:
            town_target = town['population'] * 0.04
            town_percentage = in_town / (0.01 * town_target)
            reply += f' Это {town_percentage:.2f}% от {town_target:.0f}.'
    if total < target:
        next_friday = datetime.date.today()
        next_friday += datetime.timedelta(1)
        while next_friday.weekday() != 4:
            next_friday += datetime.timedelta(1)
        reply += f'\n\nЗаходите снова в следующую пятницу {next_friday.strftime("%d.%m.%Y")}, а пока не забудьте удалить этот чат!'
        unused_invites = get_unused_invite_count(user['id'])
        if unused_invites > 0:
            reply += f'\n\nВы еще не использовали свои приглашения, пожалуйста пригласите друзей!'
        else:
            reply += f'\n\nВы уже использовали оба ваших приглашения. Ура!'
    else:
        reply += f'\n\n Цель достигнута! Нас больше миллиона! Инструкции появятся вместо этого сообщения как только' \
                 f' наша команда придёт в себя после празднования этого события!'
    set_chat_state(chat_id, 11)
    send_message_with_logged_in_keyboard(bot, chat_id, reply)


def chat_output18(bot, chat_id, update):
    user = get_current_user(chat_id)
    if user['town'] is None:
        town = "неизвестен"
    else:
        town = get_town_name(user['town'])
    reply = f'Ваш город {town}.'
    kb = [[telegram.KeyboardButton("Вернуться")],
          [telegram.KeyboardButton("Сменить")]]
    kb_markup = telegram.ReplyKeyboardMarkup(kb, one_time_keyboard=True)
    bot.sendMessage(chat_id=chat_id, text=reply, reply_markup=kb_markup)


def chat_output19(bot, chat_id, update):
    reply = texts[19]
    kb = [[telegram.KeyboardButton("Да")],
          [telegram.KeyboardButton("Нет")]]
    kb_markup = telegram.ReplyKeyboardMarkup(kb, one_time_keyboard=True)
    bot.sendMessage(chat_id=chat_id, text=reply, reply_markup=kb_markup)


def chat_output20(bot, chat_id, update):
    reply = texts[20]
    bot.sendMessage(chat_id=chat_id, text=reply)


def chat_output21(bot, chat_id, update):
    reply = texts[21]
    bot.sendMessage(chat_id=chat_id, text=reply)


def chat_output22(bot, chat_id, update):
    reply = texts[22]
    bot.sendMessage(chat_id=chat_id, text=reply)
    set_chat_state(chat_id, 20)


def chat_output23(bot, chat_id, update):
    reply = texts[23]
    bot.sendMessage(chat_id=chat_id, text=reply)


def chat_output24(bot, chat_id, update):
    reply = texts[24]
    send_message_with_logged_in_keyboard(bot, chat_id, reply)
    set_chat_state(chat_id, 11)


def chat_output25(bot, chat_id, update):
    reply = texts[25]
    send_message_with_logged_in_keyboard(bot, chat_id, reply)
    set_chat_state(chat_id, 11)


def chat_output26(bot, chat_id, update):
    reply = texts[26]
    bot.sendMessage(chat_id=chat_id, text=reply)
    answer = random.randint(1, 10)
    context = {'answer': answer}
    set_chat_context(chat_id, json.dumps(context))
    first_line = random.randint(1, answer)
    second_line = answer - first_line
    smiles = [{'smile': '😄😁😄😅', 'names': ['улыбок', 'смайлов', 'весёлых рожиц']},
              {'smile': '😸😹😽', 'names': ['кошек', 'котов', 'котиков']},
              {'smile': '✋', 'names': ['рук', 'ладоней', 'поднятых рук']},
              {'smile': '❄', 'names': ['снежинок']},
              {'smile': '❓❔', 'names': ['вопросов', 'вопросительных знаков', 'знаков вопроса']},
              {'smile': '🚩', 'names': ['флажков', 'флагов']},
              {'smile': '↖↘↗', 'names': ['стрелок', 'стрелочек']}]
    selected_smiley = random.choice(smiles)
    while True:
        incorrect_smiley = random.choice(smiles)
        if incorrect_smiley != selected_smiley:
            break
    while True:
        incorrect_smiley2 = random.choice(smiles)
        if incorrect_smiley2 != selected_smiley and incorrect_smiley2 != incorrect_smiley:
            break
    line1 = []
    for i in range(first_line):
        line1.append(random.choice(selected_smiley['smile']))
    for i in range(10 - first_line):
        if random.random() > 0.5:
            line1.append(random.choice(incorrect_smiley['smile']))
        else:
            line1.append(random.choice(incorrect_smiley2['smile']))
    line2 = []
    for i in range(second_line):
        line2.append(random.choice(selected_smiley['smile']))
    for i in range(10 - second_line):
        if random.random() > 0.5:
            line2.append(random.choice(incorrect_smiley['smile']))
        else:
            line2.append(random.choice(incorrect_smiley2['smile']))
    random.shuffle(line1)
    random.shuffle(line2)
    reply = ' '.join(line1)
    bot.sendMessage(chat_id=chat_id, text=reply)
    reply = ' '.join(line2)
    bot.sendMessage(chat_id=chat_id, text=reply)
    reply = f'Сколько я прислал {random.choice(selected_smiley["names"])}. Напишите пожалуйста ответ цифрой.'
    bot.sendMessage(chat_id=chat_id, text=reply)


def chat_output27(bot, chat_id, update):
    reply = texts[27]
    send_message_with_intro_keyboard(bot, chat_id, reply)
    set_chat_state(chat_id, 0)


def chat_output28(bot, chat_id, update):
    reply = texts[28]
    send_message_with_intro_keyboard(bot, chat_id, reply)
    set_chat_state(chat_id, 0)


def chat_output29(bot, chat_id, update):
    reply = texts[29]
    kb = [[telegram.KeyboardButton("Вернуться")]]
    kb_markup = telegram.ReplyKeyboardMarkup(kb, one_time_keyboard=True)
    bot.sendMessage(chat_id=chat_id, text=reply, reply_markup=kb_markup)


def chat_output30(bot, chat_id, update):
    reply = texts[30]
    send_message_with_intro_keyboard(bot, chat_id, reply)
    set_chat_state(chat_id, 0)


def chat_output31(bot, chat_id, update):
    reply = texts[31]
    kb = [[telegram.KeyboardButton("Отмена")]]
    kb_markup = telegram.ReplyKeyboardMarkup(kb, one_time_keyboard=True)
    bot.sendMessage(chat_id=chat_id, text=reply, reply_markup=kb_markup)


def chat_output32(bot, chat_id, update):
    reply = f'*_Обратная связь_*\n\n'
    can_send = True
    messages = ''
    user = get_current_user(chat_id)
    with DATABASE.cursor() as cur:
        cur.execute(f"SELECT * FROM tickets WHERE user_id={user['id']} ORDER BY creation_date DESC")
        tickets = cur.fetchall()
        for ticket in tickets:
            if ticket['is_answered'] == 0:
                can_send = False
            else:
                answer = escape_tg(ticket['answer'])
                messages = f"*Ответ:*\n{answer}\n\n" + messages
            question = escape_tg(ticket['question'])
            messages = f"*Вопрос:*\n{question}\n" + messages
            if len(messages) > 2048:
                continue
    reply += messages
    if can_send:
        reply += '\n\nВы можете послать нам одно сообщение\\. Вы не сможете послать других, пока мы не ответим\\. ' \
                 'Извините, это ограничение нужно, чтобы мы могли справиться с потоком вопросов\\.\n' \
                 'Отредактировать сообщение будет, к сожалению, нельзя\\. Максимальный размер сообщения -- 1000 символов\\.'
    else:
        reply += '\n\n К сожалению, вы сейчас не можете послать нам новое сообщение\\. Пожалуйста, подождите, пока мы ответим на ваше предыдущее\\.'

    if can_send:
        kb = [[telegram.KeyboardButton("Назад")]]
        kb_markup = telegram.ReplyKeyboardMarkup(kb, one_time_keyboard=True)
        bot.sendMessage(chat_id=chat_id, text=reply, reply_markup=kb_markup, parse_mode='MarkdownV2')
    else:
        send_message_with_logged_in_keyboard(bot, chat_id, reply, 'MarkdownV2')
        set_chat_state(chat_id, 11)


def chat_output33(bot, chat_id, update):
    reply = f'*_Ответы на обратную связь_*\n\n'
    with DATABASE.cursor() as cur:
        cur.execute(f"SELECT * FROM tickets WHERE is_answered=0 ORDER BY creation_date ASC LIMIT 1")
        if cur.rowcount == 0:
            reply += "Ни у кого никаких вопросов\\."
            set_chat_state(chat_id, 0)
            send_message_with_intro_keyboard(bot, chat_id, reply, 'MarkdownV2')
            return
        ticket = cur.fetchone()
    context = {'ticket': ticket['id']}
    set_chat_context(chat_id, json.dumps(context))
    with DATABASE.cursor() as cur:
        cur.execute(f'SELECT * FROM users WHERE id={ticket["user_id"]}')
        if cur.rowcount == 0:
            username = "Некто"
        else:
            user = cur.fetchone()
            username = user['login']
    reply += f"_{username}_ спрашивает \n"
    reply += escape_tg(ticket['question'])
    kb = [[telegram.KeyboardButton("Ответ не нужен")],
          [telegram.KeyboardButton("Назад")]]
    kb_markup = telegram.ReplyKeyboardMarkup(kb, one_time_keyboard=True)
    bot.sendMessage(chat_id=chat_id, text=reply, reply_markup=kb_markup, parse_mode='MarkdownV2')


def chat_output34(bot, chat_id, update):
    reply = texts[34]
    send_message_with_logged_in_keyboard(bot, chat_id, reply)
    set_chat_state(chat_id, 11)


def chat_output35(bot, chat_id, update):
    reply = texts[35]
    kb = [[telegram.KeyboardButton("Согласен / Согласна")],
          [telegram.KeyboardButton("Не согласен / Не согласна")],
          [telegram.KeyboardButton("Наши требования")]]
    kb_markup = telegram.ReplyKeyboardMarkup(kb, one_time_keyboard=True)
    bot.sendMessage(chat_id=chat_id, text=reply, reply_markup=kb_markup)


def chat_output36(bot, chat_id, update):
    reply = texts[36]
    kb = [[telegram.KeyboardButton("Согласен / Согласна")],
          [telegram.KeyboardButton("Не согласен / Не согласна")]]
    kb_markup = telegram.ReplyKeyboardMarkup(kb, one_time_keyboard=True)
    bot.sendMessage(chat_id=chat_id, text=reply, reply_markup=kb_markup)


def chat_output37(bot, chat_id, update):
    reply = texts[37]
    kb = [[telegram.KeyboardButton("Согласен / Согласна")],
          [telegram.KeyboardButton("Не согласен / Не согласна")]]
    kb_markup = telegram.ReplyKeyboardMarkup(kb, one_time_keyboard=True)
    bot.sendMessage(chat_id=chat_id, text=reply, reply_markup=kb_markup)


def chat_output38(bot, chat_id, update):
    reply = texts[38]
    kb = [[telegram.KeyboardButton("Согласен / Согласна")],
          [telegram.KeyboardButton("Не согласен / Не согласна")]]
    kb_markup = telegram.ReplyKeyboardMarkup(kb, one_time_keyboard=True)
    bot.sendMessage(chat_id=chat_id, text=reply, reply_markup=kb_markup)
    set_chat_state(chat_id, 35)


def chat_output39(bot, chat_id, update):
    reply = texts[39]
    send_message_with_logged_in_keyboard(bot, chat_id, reply)
    set_chat_state(chat_id, 11)


def chat_output40(bot, chat_id, update):
    reply = texts[40]
    bot.sendMessage(chat_id=chat_id, text=reply)
    set_chat_state(chat_id, 20)


def chat_output41(bot, chat_id, update):
    reply = texts[41]
    send_message_with_about_keyboard(bot, chat_id, reply, 'Markdown')
    set_chat_state(chat_id, 3)


def chat_output42(bot, chat_id, update):
    reply = texts[38]
    send_message_with_about_keyboard(bot, chat_id, reply, 'Markdown')
    set_chat_state(chat_id, 3)


def chat_output43(bot, chat_id, update):
    reply = texts[43]
    send_message_with_about_keyboard(bot, chat_id, reply, 'Markdown')
    set_chat_state(chat_id, 3)


def chat_output44(bot, chat_id, update):
    reply = texts[23]
    bot.sendMessage(chat_id=chat_id, text=reply)


def chat_output45(bot, chat_id, update):
    reply = texts[45]
    bot.sendMessage(chat_id, reply)
    set_chat_state(chat_id, 44)


def chat_output46(bot, chat_id, update):
    reply = texts[46]
    send_message_with_about_keyboard(bot, chat_id, reply, 'Markdown')
    set_chat_state(chat_id, 3)


def chat_output47(bot, chat_id, update):
    reply = texts[47]
    send_message_with_about_keyboard(bot, chat_id, reply, 'Markdown')
    set_chat_state(chat_id, 3)


def chat_output48(bot, chat_id, update):
    reply = texts[48]
    send_message_with_about_keyboard(bot, chat_id, reply, 'Markdown')
    set_chat_state(chat_id, 3)


def chat_output49(bot, chat_id, update):
    reply = texts[42]  # not a bug! 42 is the text about safety principles
    send_message_with_about_keyboard(bot, chat_id, reply, 'Markdown')
    set_chat_state(chat_id, 3)


def chat_output50(bot, chat_id, update):
    reply = texts[50]
    send_message_with_about_keyboard(bot, chat_id, reply, 'Markdown')
    set_chat_state(chat_id, 3)


def chat_output51(bot, chat_id, update):
    reply = texts[51]
    send_message_with_about_keyboard(bot, chat_id, reply, 'Markdown')
    set_chat_state(chat_id, 3)


def send_password_writedown_reminder(bot, chat_id):
    bot.sendMessage(chat_id=chat_id, text=texts['write_down_reminder'])


def send_message_with_logged_in_keyboard(bot, chat_id, reply, parse_mode=None):
    kb = [[telegram.KeyboardButton("Мои приглашения")],
          [telegram.KeyboardButton("Общая картина")],
          [telegram.KeyboardButton("Мой город")],
          [telegram.KeyboardButton("Сменить пароль")],
          [telegram.KeyboardButton("Подробности")],
          [telegram.KeyboardButton("Выход")],
          [telegram.KeyboardButton("Обратная связь")],
          [telegram.KeyboardButton("Удалить аккаунт")]]
    kb_markup = telegram.ReplyKeyboardMarkup(kb, one_time_keyboard=True)
    if parse_mode is not None:
        bot.sendMessage(chat_id=chat_id, text=reply, reply_markup=kb_markup, parse_mode=parse_mode)
    else:
        bot.sendMessage(chat_id=chat_id, text=reply, reply_markup=kb_markup)


def send_message_with_intro_keyboard(bot, chat_id, reply, parse_mode=None):
    kb = [[telegram.KeyboardButton("Вход")],
          [telegram.KeyboardButton("Регистрация")],
          [telegram.KeyboardButton("Подробности")]]
    kb_markup = telegram.ReplyKeyboardMarkup(kb, one_time_keyboard=True)
    if parse_mode is not None:
        bot.sendMessage(chat_id=chat_id, text=reply, reply_markup=kb_markup, parse_mode=parse_mode)
    else:
        bot.sendMessage(chat_id=chat_id, text=reply, reply_markup=kb_markup)


def send_message_with_about_keyboard(bot, chat_id, reply, parse_mode=None):
    kb = [[telegram.KeyboardButton(texts['btn_about_1'])],
          [telegram.KeyboardButton(texts['btn_about_2'])],
          [telegram.KeyboardButton(texts['btn_about_3'])],
          [telegram.KeyboardButton(texts['btn_about_4'])],
          [telegram.KeyboardButton(texts['btn_about_5'])],
          [telegram.KeyboardButton(texts['btn_about_6'])],
          [telegram.KeyboardButton(texts['btn_about_7'])],
          [telegram.KeyboardButton(texts['btn_about_8'])],
          [telegram.KeyboardButton(texts['btn_about_9'])],
          [telegram.KeyboardButton(texts['btn_about_10'])],
          [telegram.KeyboardButton(texts['btn_back'])]]
    kb_markup = telegram.ReplyKeyboardMarkup(kb, one_time_keyboard=True)
    if parse_mode is not None:
        bot.sendMessage(chat_id=chat_id, text=reply, reply_markup=kb_markup, parse_mode=parse_mode)
    else:
        bot.sendMessage(chat_id=chat_id, text=reply, reply_markup=kb_markup)


def escape_tg(in_string):
    return in_string.replace('\\', '\\\\').replace('.', '\\.').replace('_', '\\_').replace('*', '\\*').replace(
        '[', '\\[').replace(']', '\\]').replace('(', '\\(').replace(')', '\\)').replace('~', '\\~').replace(
        '`', '\\´').replace('>', '\\>').replace('#', '\\#').replace('+', '\\+').replace('-', '\\-').replace(
        '=', '\\=').replace('|', '\\|').replace('{', '\\{').replace('}', '\\}').replace('!', '\\!')


def escape_tg_punctuation(in_string):
    return in_string.replace('.', '\\.').replace('(', '\\(').replace(')', '\\)').replace('=', '\\=').replace('!',
                                                                                                             '\\!').replace(
        '-', '\\-')


# def send_current_state_image(bot, chat_id):
#    with DATABASE.cursor() as cur:
#        cur.execute(f'SELECT num FROM(    select count(*) as num from users u where u.createdOn <= CURDATE() - 0    '
#                    f'UNION ALL select count(*) as c from users u where u.createdOn <= CURDATE() - 1    UNION ALL '
#                    f'select count(*) as c from users u where u.createdOn <= CURDATE() - 2    UNION ALL select count('
#                    f'*) as c from users u where u.createdOn <= CURDATE() - 3    UNION All select count(*) as c from '
#                    f'users u where u.createdOn <= CURDATE() - 4   UNION All select count(*) as c from users u where '
#                    f'u.createdOn <= CURDATE() - 5    UNION All select count(*) as c from users u where u.createdOn '
#                    f'<= CURDATE() - 6 UNION ALL select count(*) as c from users u where u.createdOn = CURDATE() '
#                    f'UNION ALL select count(*) as c from users u where u.createdOn = CURDATE() - 1    UNION ALL '
#                    f'select count(*) as c from users u where u.createdOn = CURDATE() - 2    UNION ALL select count('
#                    f'*) as c from users u where u.createdOn = CURDATE() - 3    UNION All select count(*) as c from '
#                    f'users u where u.createdOn = CURDATE() - 4    UNION All select count(*) as c from users u where '
#                    f'u.createdOn = CURDATE() - 5    UNION All select count(*) as c from users u where u.createdOn = '
#                    f'CURDATE() - 6) as sums')  # if you are trying to read it, well... oops:)
#        sums = cur.fetchall()
#    max_val = sums[0]['num']
#    min_val = sums[6]['num']
#    min_reg_val = max_reg_val = sums[7]['num']
#    for i in range(8, 14):
#        if min_reg_val > sums[i]['num']:
#            min_reg_val = sums[i]['num']
#        if max_reg_val < sums[i]['num']:
#            max_reg_val = sums[i]['num']
#    if max_reg_val == 0 or max_val == 0:
#        return
#    order_of_magnitude = floor(log10(max_val))
#    order_of_reg_magnitude = floor(log10(max_reg_val))
#    max_graph_val = ((max_val // (10 ** order_of_magnitude)) + 1) * 10 ** order_of_magnitude
#    max_graph_reg_val = ((max_reg_val // (10 ** order_of_reg_magnitude)) + 1) * 10 ** order_of_reg_magnitude
#    min_graph_val = max_graph_val
#    while min_graph_val > min_val:
#        min_graph_val -= 10 ** order_of_magnitude
#    graph_range_y = max_graph_val - min_graph_val
#    min_graph_reg_val = max_graph_reg_val
#    while min_graph_reg_val > min_reg_val:
#        min_graph_reg_val -= 10 ** order_of_reg_magnitude
#    graph_range_reg_y = max_graph_reg_val - min_graph_reg_val

#    width = 300
#    height = 300
#    arrow_length = 3
#    arrow_width = 2
#    padding = 20
#    offset_x = 10
#    offset_y = 10
#    value_zone_y = height - 2 * padding - 2 * offset_y
#    value_zone_x = width - 2 * padding - 2 * offset_x
#    dash_length = 2
#    bar_width = 14
#    image = Image.new('RGB', (width, height), (255, 255, 255))
#    canvas = ImageDraw.Draw(image)
#    black = (0, 0, 0)
#    line_color = (255, 127, 80)
#    bar_color = (30, 161, 161)
#    bar_outline_color = (0, 131, 131)

#    top_left = (padding, padding)
#    origin = (padding, height - padding)
#    bottom_right = (width - padding, height - padding)
#    top_right = (width - padding, padding)
#    default_font = ImageFont.load_default()
#    canvas.line([top_left, origin, bottom_right, top_right], black, 1)
#    canvas.line([top_left, (padding + arrow_width, padding + arrow_length)], black, 1)
#    canvas.line([top_left, (padding - arrow_width, padding + arrow_length)], black, 1)
#    canvas.line([top_right, (width - padding + arrow_width, padding + arrow_length)], black, 1)
#    canvas.line([top_right, (width - padding - arrow_width, padding + arrow_length)], black, 1)
#    canvas.text((6, 1), text="Total users", font=default_font, fill=line_color, direction='ttb', anchor='mm')
#    canvas.text((width - 60, 1), text="Users/day", font=default_font, fill=bar_color, direction='ttb', anchor='mm')
#    canvas.text((width / 2 - 20, 10), text="Million", font=default_font, fill=black, direction='ttb', anchor='mm')

#    dateval = datetime.datetime.now() - datetime.timedelta(days=6)
#    for x in range(padding + offset_x, width - padding - offset_x + 1, round((width - 2 * padding - 2 * offset_x) / 6)):
#        canvas.line([(x, height - padding), (x, height - padding + dash_length)], black, 1)
#        canvas.text(
#            (x - 10, height - padding + dash_length),
#            text=dateval.strftime("%d/%m"),
#            font=default_font, fill=black,
#            direction='ttb',
#            anchor='mm'
#        )
#        dateval = dateval + datetime.timedelta(days=1)

#    val = max_graph_val
#    valstep = (max_graph_val -# min_graph_val) / 4
#    val_reg = max_graph_reg_va#l
#    valstep_reg = (max_graph_reg_val - min_graph_reg_val) / 4#
#    for y in range(padding + offset_y, height - padding - offset_y + 1,
#                   round((height - 2 * padding - 2 * offset_y) / 4)):
#        canvas.text((1, y), text=str(floor(val)), font=default_font, fill=line_color, direction='ttb', anchor='mm')
#        canvas.text((width - padding + 2, y), text=str(floor(val_reg)), font=default_font, fill=bar_color, direction='ttb',
#                    anchor='mm')
#        canvas.line([(padding, y), (padding - dash_length, y)], line_color, 1)
#        canvas.line([(width - padding, y), (width - padding + dash_length, y)], bar_color, 1)
#        val -= valstep
#        val_reg -= valstep_reg

#    for i in range(0, 7):
#        cur_val = sums[13 - i]['num']
#        cur_graph_val = \
#            round(height - padding - offset_y - (cur_val - min_graph_reg_val) / graph_range_reg_y * value_zone_y)
#        cur_x = round(padding + offset_x + value_zone_x / 6 * i)
#        canvas.rectangle(
#            [(cur_x - bar_width / 2, height - padding - 1), (cur_x + bar_width / 2, cur_graph_val)],
#            fill=bar_color,
#            outline=bar_outline_color
#        )

#    dots = []
#    for i in range(0, 7):
#        cur_val = sums[6 - i]['num']
#        cur_graph_val = round(height - padding - offset_y - (cur_val - min_graph_val) / graph_range_y * value_zone_y)
#        cur_x = round(padding + offset_x + value_zone_x / 6 * i)
#        dots.append((cur_x, cur_graph_val))

#    canvas.line(dots, fill=line_color, width=1, joint='curve')
#    bio = BytesIO()
#    bio.name = 'image.png'
#    image.save(bio, 'PNG')
#    bio.seek(0)
#    bot.send_photo(chat_id=chat_id, photo=bio)


def shortbot(event, context):
    """
    Runs the Telegram webhook.
    """

    bot = configure_telegram()
    global DATABASE
    DATABASE = pymysql.connect(host=DB_HOST, user=DB_USER, password=DB_PASSWORD, database=DB_DATABASE,
                               cursorclass=pymysql.cursors.DictCursor, connect_timeout=30, read_timeout=30,
                               write_timeout=30)
    if event.get('httpMethod') == 'POST' and event.get('body'):
        logger.info('Message received')
        update = telegram.Update.de_json(json.loads(event.get('body')), bot)
        chat_id = update.message.chat.id
        state = get_chat_state(chat_id)
        logger.info(f'Pre state is {state}')
        processor = getattr(sys.modules[__name__], "chat_reaction" + str(state))
        if update.message.text == BROADCAST_CODE:
            set_chat_state(chat_id, 31)
            state = 31
        elif update.message.text == REPLY_CODE:
            set_chat_state(chat_id, 33)
            state = 33
        else:
            if processor is not None:
                newState = processor(bot, update)
                logger.info(f'New state is {newState}')
                if newState != state:
                    set_chat_state(chat_id, newState)
                    state = newState
            else:
                text = f'Чат в неожиданном состоянии {state}. MrBearclaw еще работает'
                bot.sendMessage(chat_id=chat_id, text=text)
                set_chat_state(chat_id, 0)
                logger.info('Message sent')

        outputter = getattr(sys.modules[__name__], "chat_output" + str(state))
        if outputter is not None:
            outputter(bot, chat_id, update)
        else:
            text = f'Вывод для состояния {state} не определён. В релизе этого быть не должно. Пока что возвращаемся в' \
                   f' начало. '
            set_chat_state(chat_id, 0)
            bot.sendMessage(chat_id=chat_id, text=text)
        DATABASE.close()
        return OK_RESPONSE
    else:
        logger.info("Unexpected!  " + event.get('body'))
        DATABASE.close()
        return OK_RESPONSE
