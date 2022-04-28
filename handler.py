import json
import os
import logging
import telegram
import pymysql
import numbers
import hashlib
import string
import random
from datetime import datetime
import datetime

# Logging is cool!
logger = logging.getLogger()
if logger.handlers:
    for handler in logger.handlers:
        logger.removeHandler(handler)
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


def get_chat_state(chat_id):
    state = -1
    with DATABASE.cursor() as cur:
        cur.execute(f'SELECT * FROM chats where id={chat_id}')
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
            cur.execute(f'INSERT INTO chats VALUES({chat_id}, 0, now(), "", NULL)')
            DATABASE.commit()
            state = 0
    return state


def set_chat_state(chat_id, new_state):
    logger.info(f'Setting state in DB to {new_state}')
    with DATABASE.cursor() as cur:
        cur.execute(f'UPDATE chats SET state={new_state}, lastUpdate=now() WHERE id={chat_id}')
        DATABASE.commit()


def set_chat_user(chat_id, user_id):
    logger.info(f'Setting user in DB to {user_id}')
    with DATABASE.cursor() as cur:
        cur.execute(f'UPDATE chats SET affiliatedUser={user_id}, lastUpdate=now() WHERE id={chat_id}')
        DATABASE.commit()


def set_chat_context(chat_id, new_context):
    encoded_context = new_context.replace("\'", "\\\'")
    with DATABASE.cursor() as cur:
        cur.execute(f'UPDATE chats SET context=\'{encoded_context}\', lastUpdate=now() WHERE id={chat_id}')
        DATABASE.commit()


def get_chat_context(chat_id):
    context = {}
    with DATABASE.cursor() as cur:
        cur.execute(f'SELECT * FROM chats where id={chat_id}')
        if cur.rowcount != 0:
            result = cur.fetchone()
            context = json.loads(result['context'])
    return context


def increment_child_count(user_id):
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


def update_password(chat_id, new_password):
    with DATABASE.cursor() as cur:
        cur.execute(f'UPDATE users SET password="{new_password}" WHERE '
                    f'id = (SELECT affiliatedUser FROM chats WHERE id={chat_id});')
    DATABASE.commit()


def get_current_user(chat_id):
    with DATABASE.cursor() as cur:
        cur.execute(f'SELECT users.* FROM users INNER JOIN chats ON users.id = chats.affiliatedUser'
                    f' WHERE chats.id={chat_id};')
        user = cur.fetchone()
    return user


def get_town_name(town_key):
    with DATABASE.cursor() as cur:
        cur.execute(f'SELECT t2.town from towns t1 inner join towns t2 on t1.key_idx = t2.id WHERE t1.id = {town_key};')
        town = cur.fetchone()
    return town['town']


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
        return 3
    elif text == "Вход":
        return 1
    elif text == "Регистрация":
        return 2
    else:
        return 0


def chat_reaction1(bot, update):
    username = update.message.text.strip().replace('\"', '\\\"').replace('\'', '\\\'')
    chat_id = update.message.chat.id
    try_to_delete_message(bot, chat_id, update)
    with DATABASE.cursor() as cur:
        cur.execute(f'SELECT * FROM users where login="{username}"')
        if cur.rowcount == 0:
            return 13
        user = cur.fetchone()
        chat_id = update.message.chat.id

    with DATABASE.cursor() as cur:
        cur.execute(f'SELECT * FROM chats WHERE id={chat_id}')
        chat = cur.fetchone()
        if chat['affiliatedUser'] == user['id']:
            reply = 'Я вас помню. Вхоите пожалуйста без пароля.\n' \
                    'Важно - если вы волнуетесь о безопасности - я вас помним по техническому номеру чата. Я не знаю' \
                    ' и не сохраняю никаких личных данных по которым вас можно было бы идентифицировать.'
            bot.sendMessage(chat_id=chat_id, text=reply)
            return 11
    context = {'user': user['id'], 'hash': user['password']}
    set_chat_context(chat_id, json.dumps(context))
    return 14


def chat_reaction2(bot, update):
    invitation_key = update.message.text.lower().strip()
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
            return 7
        else:
            return 5


def chat_reaction4(bot, update):
    reply = 'Из соображений безопастности ваш сеанс был завершён. Пожалуйста войдите еще раз.'
    chat_id = update.message.chat.id
    bot.sendMessage(chat_id=chat_id, text=reply)
    set_chat_context(chat_id, "")
    return 0


def chat_reaction7(bot, update):
    username = update.message.text.strip().replace('\"', '\\\"').replace('\'', '\\\'')
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
        invite = context['invite']
        cur.execute(f'SELECT * FROM invites WHERE id={invite}')
        invite_object = cur.fetchone()
    inviting_user_id = invite_object['createdBy']
    with DATABASE.cursor() as cur:
        login = context['login']
        parent = "NULL"
        if isinstance(inviting_user_id, numbers.Number):
            parent = inviting_user_id
        cur.execute(f'INSERT INTO users (login, password, last_login, parentUserId, kidCount) VALUES("{login}", "{password_hash}", now(), {parent}, 0)')
        DATABASE.commit()
        new_user_id = cur.lastrowid
    with DATABASE.cursor() as cur:
        cur.execute(f'UPDATE invites SET usedBy={new_user_id}, usedOn=now() WHERE id={invite}')
        DATABASE.commit()
    increment_child_count(parent)
    for x in range(2):
        with DATABASE.cursor() as cur:
            invite_code = ''.join(random.choice(string.ascii_lowercase + string.digits) for _ in range(10))
            cur.execute(f'INSERT INTO invites (invite, createdBy, usedBy, createdOn, usedOn) VALUES ("{invite_code}", {new_user_id}, NULL, now(), NULL)')
            DATABASE.commit()
    set_chat_context(chat_id, "")
    set_chat_user(chat_id, new_user_id)
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
        return 11
    return 15


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
    town_name = update.message.text.strip().capitalize()
    town_id = None
    user = get_current_user(update.message.chat.id)
    with DATABASE.cursor() as cur:
        cur.execute(f'SELECT * FROM towns WHERE town="{town_name}"')
        if cur.rowcount > 0:
            town = cur.fetchone()
            town_id = town['id']
    if town_id is None:
        with DATABASE.cursor() as cur:
            cur.execute(f'INSERT INTO towns (town, key_idx) VALUES ("{town_name}", 1)')
            DATABASE.commit()
            town_id = cur.lastrowid
        with DATABASE.cursor() as cur:
            cur.execute(f'UPDATE towns SET key_idx={town_id} WHERE id={town_id}')
            DATABASE.commit()

    with DATABASE.cursor() as cur:
        cur.execute(f'UPDATE users SET town={town_id} WHERE id={user["id"]}')
        DATABASE.commit()
    return 24


def chat_output0(bot, chat_id, update):
    reply = 'Добро пожаловать.\n' \
            'Нас будет миллион!'
    send_message_with_intro_keyboard(bot, chat_id, reply)
    logger.info('Message sent')


def chat_output1(bot, chat_id, update):
    reply = 'Ведите имя пользователя'
    bot.sendMessage(chat_id=chat_id, text=reply)
    logger.info('Message sent')


def chat_output2(bot, chat_id, update):
    reply = 'Ведите код приглашения'
    bot.sendMessage(chat_id=chat_id, text=reply)
    logger.info('Message sent')


def chat_output3(bot, chat_id, update):
    reply = 'Тут будет простыня текста про то что мы вообще такое делаем и как оно работает. Даня, Серж, напишите её ' \
            'пожалуйста '
    send_message_with_intro_keyboard(bot, chat_id, reply)
    set_chat_state(chat_id, 0)
    logger.info('Message sent')


def chat_output5(bot, chat_id, update):
    reply = 'Приглашение с таким кодом не найдено.'
    send_message_with_intro_keyboard(bot, chat_id, reply)
    set_chat_state(chat_id, 0)
    logger.info('Message sent')


def chat_output6(bot, chat_id, update):
    reply = 'Это прииглашение уже использовано. Если это были вы, попробуйте войти. Если вы потеряли доступ к логину' \
            ' или паролю - я никак не могу вам помочь из соображений безопасности. Ваш логин виден тому, кто дал вам ' \
            'приглашение.'
    send_message_with_intro_keyboard(bot, chat_id, reply)
    set_chat_state(chat_id, 0)


def chat_output7(bot, chat_id, update):
    reply = 'Приумайте имя пользователя (логин).\n' \
            'Обратите внимание, ваш логин будет сообщён тому, кто дал вам приглашение. Не регистрируйтесь, если вы' \
            ' ему не доверяете!'
    bot.sendMessage(chat_id=chat_id, text=reply)
    logger.info('Message sent')


def chat_output8(bot, chat_id, update):
    bot.delete_message(chat_id, update.message.message_id)
    reply = 'Отлично! Теперь придумайте пароль.'
    bot.sendMessage(chat_id=chat_id, text=reply)
    logger.info('Message sent')


def chat_output9(bot, chat_id, update):
    reply = 'Это имя пользователя уже занято. Попробуйте еще раз.\n' \
            'Обратите внимание, ваш логин будет сообщён тому, кто дал вам приглашение. Не регистрируйтесь, если вы' \
            ' ему не доверяете!'
    bot.sendMessage(chat_id=chat_id, text=reply)
    set_chat_state(chat_id, 7)
    logger.info('Message sent')


def chat_output10(bot, chat_id, update):
    reply = 'Спасибо! Повторите пожалуйста пароль.'
    bot.sendMessage(chat_id=chat_id, text=reply)
    logger.info('Message sent')


def chat_output11(bot, chat_id, update):
    reply = 'Добро пожаловать, вы вошли в систему!'
    send_message_with_logged_in_keyboard(bot, chat_id, reply)


def chat_output12(bot, chat_id, update):
    reply = 'Пароли не совпали! Придумайте пожалуйста пароль.'
    bot.sendMessage(chat_id=chat_id, text=reply)
    set_chat_state(chat_id, 8)
    logger.info('Message sent')


def chat_output13(bot, chat_id, update):
    reply = 'Такое имя пользователя в базе не зарегистрировано. Если вы забыли имя пользователя, то его знает тот,' \
            ' кто дал вам приглашение.'
    send_message_with_intro_keyboard(bot, chat_id, reply)
    set_chat_state(chat_id, 0)
    logger.info('Message sent')


def chat_output14(bot, chat_id, update):
    reply = 'Введите пароль.'
    bot.sendMessage(chat_id=chat_id, text=reply)


def chat_output15(bot, chat_id, update):
    reply = 'Пароль не совпадает. Попробуйте еще раз.'
    send_message_with_intro_keyboard(bot, chat_id, reply)
    set_chat_state(chat_id, 0)


def chat_output16(bot, chat_id, update):
    reply = 'Данные о моих приглашениях:'
    with DATABASE.cursor() as cur:
        cur.execute(f'select invites.invite, invites.createdOn, invites.usedOn, users.login, users.kidCount from '
                    f'invites inner join chats on invites.createdBy  = chats.affiliatedUser left join users on '
                    f'invites.usedBy = users.id where chats.id={chat_id}')
        invite_objects = cur.fetchall()
    total_unused = 0
    for invite in invite_objects:
        user = invite['login']
        used = False
        use_hint = ''
        if user is None:
            user = "Не использовано"
            use_by_date = invite['createdOn']
            use_by_date = use_by_date + datetime.timedelta(days=3)
            use_hint = f'Рекоммендуем использовать до {use_by_date.strftime("%Y-%m-%d")}'
        else:
            user = 'Пользователь ' + user
            used = True
            total_unused += 1
        message = f'---------\n' \
                  f'Код приглашения: {invite["invite"]}\n' \
                  f'Создано: {invite["createdOn"].strftime("%Y-%m-%d")}\n' \
                  f'{user}'
        if not used:
            message += f'\n{use_hint}'

        bot.sendMessage(chat_id=chat_id, text=message)
    if total_unused == 0:
        reply = "Спасибо за то, что вы пригласили друзей!"
    else:
        reply = "Пожалуйста, не забудьте приласить ваших друзей и знакомых! Не дайте цепочке разорваться на вас!"
    send_message_with_logged_in_keyboard(bot, chat_id, reply)
    set_chat_state(chat_id, 11)


def chat_output17(bot, chat_id, update):
    with DATABASE.cursor() as cur:
        cur.execute("SELECT count(*) AS numUsers FROM users")
        count = cur.fetchone()
    total = count['numUsers']
    user = get_current_user(chat_id)
    in_town = None
    if user['town'] is not None:
        with DATABASE.cursor() as cur:
            town = user['town']
            cur.execute(f'SELECT count(*) as inTown from users where town = {town};')
            in_town = cur.fetchone()['inTown']
    percentage = total / 10000.0
    reply = f'Сейчас в системе зарегистрировано {total}. Это {percentage:.2f}% от нашей цели. '
    reply += f'Из них {user["kidCount"]} привели вы и те, кого вы пригласили.'
    if in_town is not None:
        reply += f'\n Из них {in_town} в вашем городе.'
    if total < 1000000:
        next_friday = datetime.date.today()
        next_friday += datetime.timedelta(1)
        while next_friday.weekday() != 4:
            next_friday += datetime.timedelta(1)
        reply += f'\nДля нас этого количества пока что не достаточно! Если вы еще не использовали свои приглашения,' \
                 f' пожалуйста пригласите друзей. И приходите проверить в следующую ' \
                 f'пятницу {next_friday.strftime("%Y-%m-%d")}'
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
    reply = f"Вы хотите сменить пароль?"
    kb = [[telegram.KeyboardButton("Да")],
          [telegram.KeyboardButton("Нет")]]
    kb_markup = telegram.ReplyKeyboardMarkup(kb, one_time_keyboard=True)
    bot.sendMessage(chat_id=chat_id, text=reply, reply_markup=kb_markup)


def chat_output20(bot, chat_id, update):
    reply = f"Введите новый пароль"
    bot.sendMessage(chat_id=chat_id, text=reply)


def chat_output21(bot, chat_id, update):
    reply = f"Пожалуйста повторите пароль"
    bot.sendMessage(chat_id=chat_id, text=reply)


def chat_output22(bot, chat_id, update):
    reply = f"Введённые пароли не совпали. Пожалуйста введите новый пароль"
    bot.sendMessage(chat_id=chat_id, text=reply)
    set_chat_state(chat_id, 20)


def chat_output23(bot, chat_id, update):
    reply = f'Введите название города или населённого пункта, в котором вы готовы выйти на митинг, когда придёт время'
    bot.sendMessage(chat_id=chat_id, text=reply)


def chat_output24(bot, chat_id, update):
    reply = f'Город изменён. Спасибо.'
    send_message_with_logged_in_keyboard(bot, chat_id, reply)
    set_chat_state(chat_id, 11)


def chat_output25(bot, chat_id, update):
    reply = f'Пароль изменён. Обязательно запишите его! Серьёзно. Восстановить пароль невозможно!'
    send_message_with_logged_in_keyboard(bot, chat_id, reply)
    set_chat_state(chat_id, 11)


def send_message_with_logged_in_keyboard(bot, chat_id, reply):
    kb = [[telegram.KeyboardButton("Мои приглашения")],
          [telegram.KeyboardButton("Общая картина")],
          [telegram.KeyboardButton("Мой город")],
          [telegram.KeyboardButton("Сменить пароль")],
          [telegram.KeyboardButton("Выход")]]
    kb_markup = telegram.ReplyKeyboardMarkup(kb, one_time_keyboard=True)
    bot.sendMessage(chat_id=chat_id, text=reply, reply_markup=kb_markup)


def send_message_with_intro_keyboard(bot, chat_id, reply):
    kb = [[telegram.KeyboardButton("Вход")],
          [telegram.KeyboardButton("Регистрация")],
          [telegram.KeyboardButton("Подробности")]]
    kb_markup = telegram.ReplyKeyboardMarkup(kb, one_time_keyboard=True)
    bot.sendMessage(chat_id=chat_id, text=reply, reply_markup=kb_markup)


def shortbot(event, context):
    """
    Runs the Telegram webhook.
    """

    bot = configure_telegram()
    global DATABASE
    DATABASE = pymysql.connect(host=DB_HOST, user=DB_USER, password=DB_PASSWORD, database=DB_DATABASE,
                               cursorclass=pymysql.cursors.DictCursor, connect_timeout=30, read_timeout=30, write_timeout=30)
    if event.get('httpMethod') == 'POST' and event.get('body'):
        logger.info('Message received')
        update = telegram.Update.de_json(json.loads(event.get('body')), bot)
        chat_id = update.message.chat.id
        state = get_chat_state(chat_id)
        logger.info(f'Pre state is {state}')
        processors = {
            0: chat_reaction0,
            1: chat_reaction1,
            2: chat_reaction2,
            4: chat_reaction4,
            7: chat_reaction7,
            8: chat_reaction8,
            10: chat_reaction10,
            11: chat_reaction11,
            14: chat_reaction14,
            18: chat_reaction18,
            19: chat_reaction19,
            20: chat_reaction20,
            21: chat_reaction21,
            23: chat_reaction23
        }
        outputters = {
            0: chat_output0,
            1: chat_output1,
            2: chat_output2,
            3: chat_output3,
            5: chat_output5,
            6: chat_output6,
            7: chat_output7,
            8: chat_output8,
            9: chat_output9,
            10: chat_output10,
            11: chat_output11,
            12: chat_output12,
            13: chat_output13,
            14: chat_output14,
            15: chat_output15,
            16: chat_output16,
            17: chat_output17,
            18: chat_output18,
            19: chat_output19,
            20: chat_output20,
            21: chat_output21,
            22: chat_output22,
            23: chat_output23,
            24: chat_output24,
            25: chat_output25
        }
        if state in processors:
            newState = processors[state](bot, update)
            logger.info(f'New state is {newState}')
            if newState != state:
                set_chat_state(chat_id, newState)
                state = newState
        else:
            text = f'Чат в неожиданном состоянии {state}. MrBearclaw еще работает'
            bot.sendMessage(chat_id=chat_id, text=text)
            logger.info('Message sent')

        if state in outputters:
            outputters[state](bot, chat_id, update)
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
