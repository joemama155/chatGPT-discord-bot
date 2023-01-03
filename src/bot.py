import discord
import redis.asyncio as redis

from src.openai_client import OpenAI, MAX_PROMPT_LENGTH
from src.message_history import ConversationHistoryRepo, UsernamesMapper, HistoryMessage

from typing import Optional, List, Dict, Protocol
import logging
import os
import re

TRIM_FRONT_PATTERN = re.compile("[ \r\n]")

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

class NullUsernamesMapper(UsernamesMapper):
    async def get_username(self, user_id: int) -> str:
        return ""

class DiscordUsernamesMapper(UsernamesMapper):
    """ Implements UsernamesMapper using Discord.
    Fields:
    - discord_client: Discord client
    - cache: Records usernames which have already been retrieved, keys: user IDs, values: usernames
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

class DiscordInteractionHandler(Protocol):
    def __call__(self, interaction: discord.Interaction, *args, **kwargs) -> None: ...

class DiscordBot(discord.Bot):
    """ Discord bot client.
    Fields:
    - logger: Logger
    - guild_ids: Discord server IDs for which bot will respond
    - channel_id: ID of channel which bot is allowed to be used, if None then responds in every channel
    - conversation_history_repo: Message history repository
    - openai_client: OpenAI API client
    """
    logger: logging.Logger
    guild_ids: List[int]
    channel_id: Optional[int]
    conversation_history_repo: ConversationHistoryRepo
    openai_client: OpenAI

    def __init__(
        self,
        logger: logging.Logger,
        guild_ids: List[int],
        channel_id: Optional[int],
        conversation_history_repo: ConversationHistoryRepo,
        openai_client: OpenAI
    ) -> None:
        super().__init__(intents=discord.Intents.default())
        self.logger = logger

        self.guild_ids = guild_ids
        self.channel_id = channel_id

        self.conversation_history_repo = conversation_history_repo
        self.conversation_history_repo.usernames_mapper = DiscordUsernamesMapper(self)

        self.openai_client = openai_client

        self.application_command(name="chat", description="Chat with GPT3", guild_ids=self.guild_ids)(self.chat)
        self.application_command(name="transcript", description="Reveal the chat transcript being recorded by the bot", guild_ids=self.guild_ids)(self.transcript)
        self.application_command(name="clear-transcript", description="Clear the transcript of you and the bots previous messages", guild_ids=self.guild_ids)(self.clear_transcript)

    async def on_ready(self):
        self.logger.info("Ready")

    def compose_error_msg(self, msg: str) -> str:
        return f"> Error: {msg}"

    async def check_channel_allowed(self, interaction: discord.Interaction) -> bool:
        # Check if we are being limited to a channel
        if self.channel_id is not None and interaction.channel_id != self.channel_id:
            self.logger.error("Message in wrong channel %d (only allowed in: %d)", interaction.channel_id, self.channel_id)
            await interaction.followup.send_message(
                ephemeral=True,
                content=self.compose_error_msg(f"Only allowed to respond to messages in the <#{self.channel_id}> channel")
            )

            return False

        return True

    async def chat(self, interaction: discord.Interaction, prompt: str):
        """ /chat <prompt>
        User gives the bot a prompt and it responds with GPT3.
        Arguments:
        - interaction: Slash command interaction
        - prompt: Slash command prompt argument
        """
        try:
            self.logger.info("received /chat %s", prompt)

            await interaction.response.defer()

            if not await self.check_channel_allowed(interaction):            
                return

            # Check prompt isn't too long
            if len(prompt) > MAX_PROMPT_LENGTH:
                await interaction.followup.send(content=self.compose_error_msg(f"Prompt cannot me longer than {MAX_PROMPT_LENGTH} characters"))
                return

            # Record the user's prompt in their history
            history = await self.conversation_history_repo.get(interaction.user.id)
            async with await history.lock():
                # Record user's prompt and a blank message for the AI
                history.messages.extend([
                    HistoryMessage(
                        author_id=interaction.user.id,
                        body=prompt,
                    ),
                    HistoryMessage(
                        author_id=self.user.id,
                        body="",
                    ),
                ])
                await history.trim(MAX_PROMPT_LENGTH)

                # Ask AI
                transcript = "\n".join((await history.as_transcript_lines())[0])
                ai_resp = await self.openai_client.create_completion(transcript)
                if ai_resp is None:
                    self.logger("No AI response")
                    await interaction.followup.send(self.compose_error_msg("The AI did not know what to say"))
                    return

                trimmed_resp = ""

                for c in ai_resp:
                    if TRIM_FRONT_PATTERN.match(c) is not None and len(trimmed_resp) == 0:
                        continue
                    else:
                        trimmed_resp += c

                history.messages[-1].body = trimmed_resp
                await history.trim(MAX_PROMPT_LENGTH)

                await history.save()

                self.logger.info("%s -> %s", prompt, trimmed_resp)

                resp_txt = """\
> {prompt}
> 
> ~ <@{author_id}>

{trimmed_resp}""".format(
                    prompt=prompt,
                    trimmed_resp=trimmed_resp,
                    author_id=interaction.user.id,
                )
                await interaction.followup.send(content=resp_txt)
        except Exception as e:
            self.logger.exception("Failed to run /chat handler: %s", e)

            try:
                await interaction.followup.send(content=self.compose_error_msg("An unexpected error occurred"))
            except Exception as e:
                self.logger.exception("While trying to send an 'unknown error' message to the user, an exception occurred: %s", e)

    async def transcript(self, interaction: discord.Interaction):
        """ /transcript
        Prints the user and bots transcript.
        Arguments:
        - interaction: Slash command interaction
        """
        try:
            self.logger.info("received /transcript")

            await interaction.response.defer()

            if not await self.check_channel_allowed(interaction):            
                return

            history = await self.conversation_history_repo.get(interaction.user.id)

            transcript_lines = []
            for msg in history.messages:
                username = await self.conversation_history_repo.usernames_mapper.get_username(msg.author_id)
                transcript_lines.append(f"**{username}:** {msg.body}")

            transcript = ""
            if len(history.messages) > 0:
                transcript = "\n".join(transcript_lines)
            else:
                transcript = "*No transcript history*"

            interaction_txt = """\
Here is our conversation:

{transcript}""".format(transcript=transcript)

            await interaction.followup.send(content=interaction_txt)

        except Exception as e:
            self.logger.exception("Failed to run /transcript handler: %s", e)

            try:
                await interaction.followup.send(content=self.compose_error_msg("An unexpected error occurred"))
            except Exception as e:
                self.logger.exception("While trying to send an 'unknown error' message to the user, an exception occurred: %s", e)

    async def clear_transcript(self, interaction: discord.Interaction):
        """ /clear-transcript
        Delete the user's message history.
        Arguments:
        - interaction: Slash command interaction
        """
        try:
            self.logger.info("received /clear-transcript")

            await interaction.response.defer()

            if not await self.check_channel_allowed(interaction):            
                return

            history = await self.conversation_history_repo.get(interaction.user.id)

            async with await history.lock():
                history.messages = []

                await history.save()

            await interaction.followup.send(content="I have cleared our conversation history, all is forgotten :wink:")

        except Exception as e:
            self.logger.exception("Failed to run /transcript handler: %s", e)

            try:
                await interaction.followup.send(content=self.compose_error_msg("An unexpected error occurred"))
            except Exception as e:
                self.logger.exception("While trying to send an 'unknown error' message to the user, an exception occurred: %s", e)

async def run_bot():
    logger.info("Run bot started")

    logger.info("Connecting to Redis")

    redis_client = redis.Redis(
        host=os.getenv('REDIS_HOST', "redis"),
        port=int(os.getenv('REDIS_PORT', "6379")),
        db=int(os.getenv('REDIS_DB', "0")),
    )

    await redis_client.ping()

    logger.info("Connected to Redis")

    channel_id = os.getenv('DISCORD_CHANNEL_ID')
    if len(channel_id) == 0:
        channel_id = None
    if channel_id is not None:
        channel_id = int(channel_id)

    bot = DiscordBot(
        logger=logger.getChild("discord.bot"),
        guild_ids=[int(os.getenv('DISCORD_GUILD_ID'))],
        channel_id=channel_id,
        conversation_history_repo=ConversationHistoryRepo(
            redis_client=redis_client,
            usernames_mapper=NullUsernamesMapper(),
        ),
        openai_client=OpenAI(),
    )

    logger.info("Starting bot")
    
    await bot.start(os.getenv('DISCORD_BOT_TOKEN'))