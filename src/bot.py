import discord

from src.openai_client import OpenAI
from src.message_history import MessageHistoryRepo, UsernamesMapper

from typing import Optional, List
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
    discord_client: discord.Client

    def __init__(self, discord_client: discord.Client):
        """ Initializes.
        Arguments:
        - discord_client: Discord client
        """
        self.discord_client = discord_client

    def get_username(self, user_id: int) -> str:
        """ Get a user's Discord username.
        Raises:
        - DiscordUsernameNotFound: If user was not found

        Returns: Discord username
        """
        user = self.discord_client.get_user(user_id)
        if user is None:
            raise DiscordUsernameNotFound(user_id)

        return user.display_name
        
""" class DiscordCommands(discord):
     Cog which implements bot slash commands.
    Fields:
    - bot: Discord bot client instance
    
    bot: commands.Bot
    logger: logging.Logger

    def __init__(self, bot: commands.Bot, logger: logging.Logger):
        self.bot = bot
        self.logger = logger

        self.bot.slash(name="chat", description="Chat with GPT3", guild_id=int(os.getenv('DISCORD_GUILD_ID')))(self.chat)

    @commands.Cog.listener()
    async def on_ready(self):
        self.logger.info("Ready")

    async def chat(self, ctx: commands.Context, prompt: str):
        ctx.reply("hello world")
 """
class DiscordBot(discord.Bot):
    """ Discord bot client.
    Fields:
    - logger: Logger
    - guild_ids: Discord server IDs for which bot will respond
    - msg_history: Message history repository
    """
    logger: logging.Logger
    guild_ids: List[int]
    msg_history: MessageHistoryRepo

    def __init__(self, logger: logging.Logger, guild_ids: List[int], msg_history: MessageHistoryRepo) -> None:
        super().__init__(intents=discord.Intents.default())
        self.logger = logger
        self.guild_ids = guild_ids

        self.msg_history = msg_history

        self.slash_command(name="chat", description="Chat with GPT3", guild_ids=self.guild_ids)(self.chat)

    async def on_ready(self):
        self.logger.info("Ready")
        await self.msg_history.init(
            usernames_mapper=DiscordUsernamesMapper(self),
            redis_host=os.getenv('REDIS_HOST', "redis"),
            redis_port=int(os.getenv('REDIS_PORT', "6379")),
            redis_db=int(os.getenv('REDIS_DB', "0")),
        )

    async def chat(self, interaction: discord.Interaction, prompt: str):
        await interaction.response.send_message(f"hello world: {prompt}")


async def run_bot():
    logger.info("Run bot started")

    bot = DiscordBot(
        logger=logger.getChild("discord.bot"),
        guild_ids=[int(os.getenv('DISCORD_GUILD_ID'))],
        msg_history=MessageHistoryRepo()
    )
    bot.msg_history.discord_client = bot
    
    """   await bot.add_cog(DiscordCommands(
            bot=bot,
            logger=logger.getChild("commands"),
    )) """
    await bot.start(os.getenv('DISCORD_BOT_TOKEN'))