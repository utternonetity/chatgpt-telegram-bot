import logging
import telebot
import os
import openai
import json
import boto3
import time
import multiprocessing
import base64
from telebot import types
from telebot.types import InputFile

user_state = {}

with open('faq.txt', 'r') as faq_file:
    lines = faq_file.readlines()
    faq = lines

faq_file.close()

questions = []
answers = []

for i, string in enumerate(faq):
    if i % 2 == 0:
        questions.append(string)
    else:
        answers.append(string)


with open('bot_messages.txt', 'r') as bot_messages_file:
    lines = bot_messages_file.readlines()
    bot_messages = lines

bot_messages_file.close()

TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN")
PROXY_API_KEY = os.environ.get("PROXY_API_KEY")
YANDEX_KEY_ID = os.environ.get("YANDEX_KEY_ID")
YANDEX_KEY_SECRET = os.environ.get("YANDEX_KEY_SECRET")
YANDEX_BUCKET = os.environ.get("YANDEX_BUCKET")


logger = telebot.logger
telebot.logger.setLevel(logging.INFO)

bot = telebot.TeleBot(TG_BOT_TOKEN, threaded=False)

client = openai.Client(
    api_key=PROXY_API_KEY,
    base_url="https://api.proxyapi.ru/openai/v1",
)


def get_s3_client():
    session = boto3.session.Session(
        aws_access_key_id=YANDEX_KEY_ID, aws_secret_access_key=YANDEX_KEY_SECRET
    )
    return session.client(
        service_name="s3", endpoint_url="https://storage.yandexcloud.net"
    )


def typing(chat_id):
    while True:
        bot.send_chat_action(chat_id, "typing")
        time.sleep(5)


keyboard = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
button1 = types.KeyboardButton(text=questions[0])
button2 = types.KeyboardButton(text=questions[1])
button3 = types.KeyboardButton(text=questions[2])
button4 = types.KeyboardButton(text=questions[3])
button5 = types.KeyboardButton(text="Я хочу связаться с оператором")
keyboard.add(button1, button2, button3, button4, button5)


@bot.message_handler(commands=["start"])
def send_welcome(message):
    bot.send_message(message.chat.id, bot_messages[0], reply_markup=keyboard)
    bot.send_sticker(message.chat.id, 'CAACAgIAAxkBAAEMHTpmQ539rrv313Is4ISSTu1brBtZxgACdgADJxRJC3YdMDdmkaDpNQQ', reply_markup=keyboard)
    

@bot.message_handler(commands=["help"])
def send_help(message):
    bot.send_message(message.chat.id, bot_messages[1], reply_markup=keyboard)

@bot.message_handler(func=lambda message: message.text in [questions[0][:-1], questions[1][:-1],questions[2][:-1],questions[3][:-1], "Я хочу связаться с оператором"] )
def handle_buttons(message):
    if message.text == questions[0][:-1]:
        bot.send_message(message.chat.id, answers[0] , reply_markup=keyboard)
    elif message.text == questions[1][:-1]:
        bot.send_message(message.chat.id, answers[1], reply_markup=keyboard)
    elif message.text == questions[2][:-1]:
        bot.send_message(message.chat.id, answers[2], reply_markup=keyboard)
    elif message.text == questions[3][:-1]:
        bot.send_message(message.chat.id, answers[3], reply_markup=keyboard)
    elif message.text=="Я хочу связаться с оператором":
        bot.send_message(message.chat.id, bot_messages[2], reply_markup=keyboard)
        user_state[message.chat.id] = "ожидание сообщения"


@bot.message_handler(func=lambda message: True, content_types=["text"])
def echo_message(message):
    if message.chat.id in user_state and user_state[message.chat.id] == "ожидание сообщения":
        bot.forward_message(1350686815, message.chat.id, message.message_id)
        user_state[message.chat.id] = None
    else:
        typing_process = multiprocessing.Process(target=typing, args=(message.chat.id,))
        typing_process.start()

        try:
            text = message.text
            ai_response = process_text_message(text, message.chat.id)
        except Exception as e:
            bot.reply_to(message, f"Произошла ошибка, попробуйте позже! {e}")
            return

        typing_process.terminate()
        bot.reply_to(message, ai_response)


def process_text_message(text, chat_id) -> str:
    model = "gpt-3.5-turbo"

    # read current chat history
    s3client = get_s3_client()
    history = []
    try:
        history_object_response = s3client.get_object(
            Bucket=YANDEX_BUCKET, Key=f"{chat_id}.json"
        )
        history = json.loads(history_object_response["Body"].read())
    except:
        pass

    history.append({"role": "user", "content": text})

    try:
        chat_completion = client.chat.completions.create(
            model=model, messages=history
        )
    except Exception as e:
        if type(e).__name__ == "BadRequestError":
            clear_history_for_chat(chat_id)
            return process_text_message(text, chat_id)
        else:
            raise e

    ai_response = chat_completion.choices[0].message.content
    history.append({"role": "assistant", "content": ai_response})

    # save current chat history
    s3client.put_object(
        Bucket=YANDEX_BUCKET,
        Key=f"{chat_id}.json",
        Body=json.dumps(history),
    )

    return ai_response

def clear_history_for_chat(chat_id):
    try:
        s3client = get_s3_client()
        s3client.put_object(
            Bucket=YANDEX_BUCKET,
            Key=f"{chat_id}.json",
            Body=json.dumps([]),
        )
    except:
        pass


def handler(event, context):
    message = json.loads(event["body"])
    update = telebot.types.Update.de_json(message)

    if (
        update.message is not None
    ):
        bot.process_new_updates([update])

    return {
        "statusCode": 200,
        "body": "ok",
    }