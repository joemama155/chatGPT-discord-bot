import discord
from discord import app_commands
from src import responses
from src import log
import time
from typing import Optional
import random
import sys

logger = log.setup_logger(__name__)

config = responses.get_config()

isPrivate = False

BACKUP_PROMPTS = []
with open("backup-prompts.txt", 'r') as f:
    for line in f:
        BACKUP_PROMPTS.append(line.strip())

message_history = {} # keys: non bot user ID, values: list of tuples where (is bot?, message)
myname = "Bot"
usernames = {} # keys: user IDs, values: strings


class aclient(discord.Client):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.messages = True
        intents.message_content = True
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self.activity = discord.Activity(type=discord.ActivityType.watching)
        

async def gracefully_send_error(message: discord.Message):
    response = await get_gpt_response(f"Argue with the following message, and end with a question: {message.content}")

    if response is None:
        logger.info("Failed to get non-empty backup prompt response, so sending a question")
        await respond(message, random.choice(BACKUP_PROMPTS))

    await respond(message, response)

async def get_gpt_response(prompt: str) -> Optional[str]:
    logger.info("gtp prompt: %s", prompt)
    response = await responses.handle_response(prompt)
    tries = 0
    while len(response) == 0 and tries < 5:
        response = await responses.handle_response(prompt)
        logger.info("gpt gave an empty response (tries: %d)", tries)
        tries += 1
        
    if len(response) == 0:
        logger.info("despite multiple attempts GPT responded with nothing")
        return None

    return response

async def respond(received_message: discord.Message, response: str):
    message_history[received_message.author.id].append((True, response))
    await received_message.channel.send(response)

def generate_history(user_id: int) -> str:
    global myname
    out = []

    for history_item in message_history[user_id]:
        name = usernames[user_id]
        if history_item[0] is True:
            name = myname

        txt = history_item[1].replace('\n', '.')
        out.append(f"{name}: {txt}")

    return out

async def send_message(message: discord.Message, user_message: str):
    global myname
    try:
        history = generate_history(message.author.id)

        history.append(f"{myname}:")
        response = await get_gpt_response("\n".join(history))
        
        if response is None:
            logger.exception("tried to get a non empty response 5 times in a row but failed")
            await gracefully_send_error(message)
            return
        
        if len(response) > 1900:
            # Split the response into smaller chunks of no more than 1900 characters each(Discord limit is 2000 per chunk)
            await respond(message, response[:1900])
        else:
            await respond(message, response)
    except Exception as e:
        await gracefully_send_error(message)
        #await message.reply("> **Error: Something went wrong, please try again later!**")
        logger.exception(f"Error while sending message: {e}")


async def send_start_prompt(client):
    import os
    import os.path

    config_dir = os.path.abspath(__file__ + "/../../")
    prompt_name = 'starting-prompt.txt'
    prompt_path = os.path.join(config_dir, prompt_name)
    try:
        if os.path.isfile(prompt_path) and os.path.getsize(prompt_path) > 0:
            with open(prompt_path, "r") as f:
                prompt = f.read()
                logger.info(f"Send starting prompt with size {len(prompt)}")
                responseMessage = await responses.handle_response(prompt)
                if (config['discord_channel_id']):
                    channel = client.get_channel(int(config['discord_channel_id']))
                    await channel.send(responseMessage)
            logger.info(f"Starting prompt response:{responseMessage}")
        else:
            logger.info(f"No {prompt_name}. Skip sending starting prompt.")
    except Exception as e:
        logger.exception(f"Error while sending starting prompt: {e}")


def run_discord_bot():
    client = aclient()

    @client.event
    async def on_ready():
        global myname
        myname = client.user.name
        await send_start_prompt(client)
        await client.tree.sync()
        logger.info(f'{client.user} is now running!')

    @client.event
    async def on_message(message: discord.Message):
        logger.info("got message '%s' from %s", message.content, message.author.name)

        if message.author.id not in usernames:
            usernames[message.author.id] = message.author.name

        # Ignore messages from myself
        if message.author == client.user:
            logger.info("the message was from me, ignoring")
            return
        
        # Ignore messages not in the right channel
        if str(message.channel.id) != str(config['discord_channel_id']):
            logger.info("the message is not in the right channel (got: %s, needs: %s), ignoring", message.channel.id, config['discord_channel_id'])
            return

        # Record message history
        if message.author.id not in message_history:
            message_history[message.author.id] = []

        message_history[message.author.id].append((False, message.content))

        # Log the message
        username = str(message.author)
        user_message = message.content
        channel = str(message.channel)
        logger.info(
            f"\x1b[31m{username}\x1b[0m : '{user_message}' ({channel})")

        time.sleep(2)

        await send_message(message, user_message)

    @client.tree.command(name="help", description="Show help for the bot")
    async def help(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=False)
        await interaction.followup.send(":star:**BASIC COMMANDS** \n    `/chat [message]` Chat with ChatGPT!\n    `/public` ChatGPT switch to public mode \n    For complete documentation, please visit https://github.com/Zero6992/chatGPT-discord-bot")
        logger.info(
            "\x1b[31mSomeone need help!\x1b[0m")

    TOKEN = config['discord_bot_token']
    client.run(TOKEN)