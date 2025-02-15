# Standard library imports
import asyncio
import sys
import os
import io
import random
import re
import logging
from datetime import datetime, timedelta

# Third-party imports
import requests
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, html
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command
from aiogram.types import InputFile, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from openai import OpenAI

load_dotenv()

# Bot token can be obtained via https://t.me/BotFather
TOKEN = os.getenv("TELEGRAM_API_TOKEN")
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

client = OpenAI(
  api_key=OPENAI_API_KEY
)

dp = Dispatcher()
bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))

reminders={}

# Mapping of time units
time_units = {"h": 3600, "m": 60, "s": 1}

# Function to parse flexible time formats
def parse_time(message_text):
    # Matching hours, minutes, seconds (handling cases like "10h15m", "2h2m4s", "3.5h")
    time_pattern = re.compile(r"(\d+(\.\d+)?)(h|m|s)")
    time_in_seconds = 0
    matches = time_pattern.findall(message_text)
    
    if not matches:
        return

    for match in matches:
        amount, _, unit = match
        amount = float(amount) if '.' in amount else int(amount)
        time_in_seconds += amount * time_units[unit]

    return time_in_seconds

async def schedule_reminder(chat_id: int, text: str, scheduled_time, task_id, image_info=None, joke=None):
    """Waits for the delay and sends a reminder message."""
    delay = (scheduled_time - datetime.now()).total_seconds()
    await asyncio.sleep(delay)
    image_url, photographer, photographer_url = image_info
    if image_url:  # Checking if image URL is available
        await bot.send_photo( # Sending the image
            chat_id,
            photo=image_url,
            caption=f"by {photographer or ''} {photographer_url or ''}"
        )
        await bot.send_message(
            chat_id,
            f"⏰ Reminder: {text}"
        )
        if joke:
            await bot.send_message(
                chat_id,
                f"{joke}"
            )
    else:
        await bot.send_message(
            chat_id,
            f"⏰ Reminder: {text}"  # Sending only the reminder text if image_url is None
        )
        if joke:
            await bot.send_message(
                chat_id,
                f"{joke}"
            )
    del reminders[task_id] 

def fetch_image_from_pexels(query):
    headers = {
        "Authorization": PEXELS_API_KEY
    }
    params = {
        "query": query,
        "per_page": 1
    }
    response = requests.get("https://api.pexels.com/v1/search", headers=headers, params=params)
    
    if response.status_code == 200:
        data = response.json()
        if "photos" in data and len(data["photos"]) > 0:
            return (
                data["photos"][0]["src"].get("original", None),
                data["photos"][0].get("photographer", None),
                data["photos"][0].get("photographer_url", None)
            )
    return None

def get_image_from_text(text):
    # Checking the length of the text; skipping image generation, if too long
    if len(text.split()) > 8:  # For example, if the text contains more than 5 words, skip
        return None
    else:
        #Using the text directly to fetch an image, if it is short
        image_info = fetch_image_from_pexels(text)
        return image_info
    
def get_joke(text):
    try:
        completion = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "user", "content": f"Tell me a joke that relates to the context of the following text: {text}"}
            ]
        )
        # Accessing the joke from the response (checking the structure)
        if completion.choices and completion.choices[0].message:
            return completion.choices[0].message.content
        else:
            return None
    except Exception as e:
        return f"An error occurred: {str(e)}"

@dp.message(CommandStart())
async def command_start_handler(message: Message) -> None:
    """
    This handler receives messages with `/start` command
    """
    await message.answer(f"Hello, you scatterbrain! I can remind you about things. Use /help to see available commands.")


@dp.message(Command("remindme"))
async def command_remindme_handler(message: Message) -> None:
    """
    This handler receives messages with `/remindme` command
    """
    message_text = message.text[len("/remindme "):].strip() 
    parts = message_text.split(maxsplit=1)
    if len(parts)>0:    
        # Checking if it's a time string or specific time
        if re.match(r"^\d{1,2}:\d{2}(?:[apAP][mM])?$", parts[0]):  
            try:
                if "am" in parts[0].lower() or "pm" in parts[0].lower():
                    scheduled_time_t = datetime.strptime(parts[0], "%I:%M%p").time()  # 12-hour format
                else:
                    scheduled_time_t = datetime.strptime(parts[0], "%H:%M").time()  # 24-hour format

                formatted_time = scheduled_time_t.strftime("%I:%M %p") # Example: "05:30 PM"
                now = datetime.now()
                scheduled_time = datetime.combine(now.date(), scheduled_time_t)

                # Scheduling for tomorrow, if scheduled_time is earlier than now
                if scheduled_time < now:
                    scheduled_time += timedelta(days=1)

                if  len(parts) > 1:
                    task_text = parts[1]
                else:
                    await message.reply("Failed to parse the task. Make sure to include a space before and after the time. \nExample: /remindme 2h15m Buy milk")
                    return
            except ValueError:
                return await message.reply("Invalid time format! \nUse HH:MM (24h) or HH:MMam/pm (12h).")
        elif any(unit in parts[0] for unit in time_units):
            # Handling flexible time (like 10h15m, 2h2m4s)
            delay = parse_time(parts[0])
            if not delay:
                await message.reply("Please provide time in the correct format. \nUse /help to learn more. \nExample: /remindme 2h15m Buy milk")
                return 
            if  len(parts) > 1:
                task_text = parts[1]
                scheduled_time = datetime.now() + timedelta(seconds=delay)
                formatted_time = scheduled_time.strftime("%I:%M %p")  # Example: "05:30 PM"
            else:
                await message.reply("Failed to parse the task. Make sure to include a space before and after the time. \nExample: /remindme 2h15m Buy milk")
                return       
        else:
            await message.reply("Please make sure to use the correct format. \nExample: /remindme 2h15m Buy milk \nUse /help to learn more.")
            return
        image_info = get_image_from_text(task_text)        
        joke=get_joke(task_text)
        task_id = len(reminders) + 1
        chat_id=message.chat.id
        task = asyncio.create_task(schedule_reminder(chat_id, task_text, scheduled_time, task_id, image_info, joke))
        reminders[task_id] = (chat_id, task_text, task)             
        await message.reply(f"Reminder set! I'll remind you to: {task_text} at {formatted_time}.")
    else:
        await message.reply("Please make sure to use the correct format. \nExample: /remindme 2h15m Buy milk \nUse /help to learn more.")
        return

# Definition of FSM states
class CancelReminder(StatesGroup):
    waiting_for_id = State()

@dp.message(Command("cancel"))
async def cancel_reminder(message: Message, state: FSMContext):
    user_id = message.from_user.id

    if not reminders:
        return await message.reply("No active reminders.")

    # Showing active reminders
    response = "\n".join([f"{task_id}: {text}" for task_id, (_, text, _) in reminders.items()])
    await message.reply(f"Choose a reminder to cancel by sending its ID:\n{response}")

    # Setting FSM state to wait for user input
    await state.set_state(CancelReminder.waiting_for_id)

@dp.message(CancelReminder.waiting_for_id)
async def process_cancel_reply(message: Message, state: FSMContext):
    user_input = message.text.strip()

    # Checking if the user entered a number
    if not user_input.isdigit():
        return await message.reply("Invalid input. Please enter a valid reminder ID.")

    task_id = int(user_input)

    if task_id in reminders:
        # Cancelling the reminder
        reminders[task_id][2].cancel() 
        del reminders[task_id]
        await message.reply(f"Reminder {task_id} cancelled.")
        await state.clear()  # Clearing state after successful cancellation
    else:
        await message.reply("Invalid reminder ID. Please enter a valid one or use another command to exit.")
        
@dp.message(Command("help"))
async def help_command_handler(message: Message) -> None:
    """
    This handler receives messages with `/help` command and shows the bot's usage.
    """
    help_text = (
        "Here are the commands you can use:\n\n"
        "<b>/help</b> - See a list of available commands (you triggered this message by using /help)\n"
        "<b>/start</b> - Get started with the bot!\n"
        "<b>/remindme</b> - Set a reminder with the following formats:\n"
        "<blockquote>"
        "   1. <b>For a delay</b>: Use hours (h), minutes (m), and seconds (s), like:\n"
        "      - <code>10h</code>, <code>15m</code>, <code>23s</code>, <code>10h12m32s</code>, <code>32m50s</code>, <code>10h20s</code>, <code>2h5m</code>\n"
        "   2. <b>For a specific time</b>: Use the format <code>HH:MM</code> or <code>HH:MMam/pm</code>, like:\n"
        "      - <code>13:49</code>, <code>20:12</code>, <code>7:15</code>, <code>12:00pm</code>, <code>6:51pm</code>, <code>3:02am</code>\n"
        "   After the time, add a space and then your task, like:\n"
        "      - <code>buy milk</code>, <code>water the plants</code>, etc.\n"
        "   <b>Example 1:</b> <code>/remindme 3h12m buy milk</code>\n"
        "   <b>Example 2:</b> <code>/remindme 3:00pm Water the plants</code>\n"
        "</blockquote>"
        "<b>/cancel</b> - Choose a reminder to cancel\n"
        "\nUse these commands to interact with me!"
    )

    await message.answer(help_text)

async def main() -> None:
    await dp.start_polling(bot)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    asyncio.run(main())