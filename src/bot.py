import discord

from src.openai_client import OpenAI, MAX_PROMPT_LENGTH
from src.message_history import MessageHistoryRepo, UsernamesMapper, HistoryMessage, ConversationHistory

from typing import Optional, List, Dict
import logging
import os

logging.basicConfig(
    level=logging.INFO,
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
    cache: Dict[int, str]

    def __init__(self, discord_client: discord.Client):
        """ Initializes.
        Arguments:
        - discord_client: Discord client
        """
        self.discord_client = discord_client
        self.cache = {}

    async def get_username(self, user_id: int) -> str:
        """ Get a user's Discord username.
        Raises:
        - DiscordUsernameNotFound: If user was not found

        Returns: Discord username
        """
        if user_id in self.cache:
            return self.cache[user_id]
        
        user = await self.discord_client.get_or_fetch_user(user_id)
        if user is None:
            raise DiscordUsernameNotFound(user_id)

        self.cache[user_id] = user.display_name

        return user.display_name

class DiscordBot(discord.Bot):
    """ Discord bot client.
    Fields:
    - logger: Logger
    - guild_ids: Discord server IDs for which bot will respond
    - msg_history: Message history repository
    - openai_client: OpenAI API client
    """
    logger: logging.Logger
    guild_ids: List[int]
    msg_history: MessageHistoryRepo
    openai_client: OpenAI

    def __init__(self, logger: logging.Logger, guild_ids: List[int], msg_history: MessageHistoryRepo, openai_client: OpenAI) -> None:
        super().__init__(intents=discord.Intents.default())
        self.logger = logger
        self.guild_ids = guild_ids

        self.msg_history = msg_history
        self.openai_client = openai_client

        self.slash_command(name="chat", description="Chat with GPT3", guild_ids=self.guild_ids)(self.chat)

    async def on_ready(self):
        await self.msg_history.init(
            usernames_mapper=DiscordUsernamesMapper(self),
            redis_host=os.getenv('REDIS_HOST', "redis"),
            redis_port=int(os.getenv('REDIS_PORT', "6379")),
            redis_db=int(os.getenv('REDIS_DB', "0")),
        )
        self.logger.info("Ready")

    def compose_error_msg(self, msg: str) -> str:
        return f"> Error: {msg}"

    async def chat(self, interaction: discord.Interaction, prompt: str):
        """ /chat <prompt>
        User gives the bot a prompt and it responds with GPT3.
        Arguments:
        - interaction: Slash command interaction
        - prompt: Slash command prompt argument
        """
        self.logger.info("received /chat %s", prompt)
        try:
            await interaction.response.defer()

            # Check prompt isn't too long
            if len(prompt) > MAX_PROMPT_LENGTH:
                await interaction.followup.send(content=self.compose_error_msg(f"Prompt cannot me longer than {MAX_PROMPT_LENGTH} characters"))
                return

            # Record the user's prompt in their history
            self.logger.info("Recording transcript")
            bot_name = await self.msg_history.usernames_mapper.get_username(self.user.id)
            history = await self.msg_history.append_message(
                interaction.user.id,
                msg=HistoryMessage(
                    author_id=interaction.user.id,
                    body=prompt,
                ),
                max_conversation_characters=MAX_PROMPT_LENGTH - (len(prompt) + len(bot_name) + 2), # Length of the prompt, length of the bot username, and then length of the transcript line's ": "
            )

            # Ask AI
            history.messages.append(HistoryMessage(
                author_id=self.user.id,
                body="",
            ))
            transcript = "\n".join(await history.as_transcript_lines(self.msg_history.usernames_mapper))

            self.logger.info("Asking bot:\n%s", transcript)

            ai_resp = await self.openai_client.create_completion(transcript)
            if ai_resp is None:
                self.logger("No AI response")
                await interaction.followup.send(self.compose_error_msg("The AI did not know what to say"))
                return

            await self.msg_history.append_message(
                interacting_user_id=interaction.user.id,
                msg=HistoryMessage(
                    author_id=self.user.id,
                    body=ai_resp,
                ),
                max_conversation_characters=MAX_PROMPT_LENGTH,
            )

            await interaction.followup.send(content=ai_resp)
        except Exception as e:
            self.logger.exception("Failed to handled /chat command: %s", e)

            try:
                await interaction.followup.send(content=self.compose_error_msg("Unknown error occurred"))
            except Exception as e:
                self.logger.exception("While trying to send an 'unknown error' message to the user, an exception occurred: %s", e)


async def run_bot():
    logger.info("Run bot started")

    bot = DiscordBot(
        logger=logger.getChild("discord.bot"),
        guild_ids=[int(os.getenv('DISCORD_GUILD_ID'))],
        msg_history=MessageHistoryRepo(),
        openai_client=OpenAI(),
    )
    bot.msg_history.discord_client = bot
    
    await bot.start(os.getenv('DISCORD_BOT_TOKEN'))