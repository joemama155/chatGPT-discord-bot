import discord
from discord.ext import commands

from src.openai_client import OpenAI
from src.message_history import MessageHistoryRepo, UsernamesMapper

import time
from typing import Optional
import random
import logging
import os

logging.basicConfig(
    level=logging.DEBUG,
    handlers=[
        logging.StreamHandler(),
    ],
)

logger = logging.getLogger(__name__)

class DiscordUsernameNotFound(Exception):
    """ Indicates the DiscordUsernamesMapper could not find a user's username.
    Fields:
    - user_id: ID of user who's username could not be found
    """
    user_id: int

    def __init__(self, user_id: int):
        super().__init__(f"Username of user with ID '{user_id}' could not be found")
        self.user_id = user_id

class DiscordUsernamesMapper(UsernamesMapper):
    """ Implements UsernamesMapper using Discord.
    Fields:
    - discord_client: Discord client
    """
    discord_bot: discord.Client

    def __init__(self, discord_bot: discord.Client):
        """ Initializes.
        Arguments:
        - discord_client: Discord client
        """
        self.discord_bot = discord_bot

    def get_username(self, user_id: int) -> str:
        """ Get a user's Discord username.
        Raises:
        - DiscordUsernameNotFound: If user was not found

        Returns: Discord username
        """
        user = self.discord_bot.get_user(user_id)
        if user is None:
            raise DiscordUsernameNotFound(user_id)

        return user.display_name
        

class DiscordBot(commands.Cog):
    """ Discord bot implementation.
    - discord_client: Discord client
    - logger: Logger
    """
    discord_bot: discord.Client
    logger: logging.Logger

    def __init__(self, discord_bot: discord.Client, logger: logging.Logger):
        """ Initialize.
        """
        self.discord_bot = discord_bot
        self.logger = logger

    @commands.Cog.listener()
    async def on_ready(self):
        self.logger.info("Commands are ready")

class DiscordClient(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.default())
        self.tree = discord.app_commands.CommandTree(self)

    async def setup_hook(self):
        bot_guild = discord.Object(id=int(os.getenv('DISCORD_GUILD_ID')))

        self.tree.copy_global_to(guild=bot_guild)
        await self.tree.sync(guild=bot_guild)


async def run_bot():
    logger.info("Run bot started")

    discord.utils.setup_logging(level=logging.INFO)
    bot = DiscordClient()
    

    @bot.tree.command(name="chat", description="Have a chat with GPT3")
    async def chat(interaction: discord.Interaction, prompt: str):
        """ Runs when a user invokes the chat command.
        Arguments:
        - interaction: The slash command interaction
        """
        logger.info("hi")

    async with bot:
        await bot.start(os.getenv('DISCORD_BOT_TOKEN'))