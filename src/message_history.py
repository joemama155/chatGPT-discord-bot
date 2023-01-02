import os
import json
from typing import List, Optional, Tuple
import abc

from pydantic import BaseModel
import redis.asyncio as redis
from redis.asyncio.lock import Lock as RedisLock

class UsernamesMapper(abc.ABC):
    """ Converts user IDs to usernames.
    """

    @abc.abstractmethod
    async def get_username(self, user_id: int) -> str:
        """ Get a user's name.
        Arguments:
        - user_id: ID of user

        Raises: Any error if fails to get username

        Returns: Username
        """
        raise NotImplementedError()

class HistoryMessage(BaseModel):
    """ One message sent by one user.
    Fields:
    - author_id: ID of user who sent message
    - body: The text sent in the message
    """
    author_id: int
    body: str

    async def as_transcript_str(self, usernames_mapper: UsernamesMapper) -> str:
        """ Convert history message into a script format string.
        Arguments:
        - usernames_mapper: Implementation of username mapper
        Returns: History message in format <username>: <body>
        """
        return f"{await usernames_mapper.get_username(self.author_id)}: {self.body}"

class ConversationHistoryLock:
    redis_lock: RedisLock
    history: "ConversationHistory"

    def __init__(self, redis_lock: RedisLock, history: "ConversationHistory"):
        """ Initializes.
        Arguments:
        - redis_lock: Redis lock for conversation history, should not be acquired yet
        - history: The conversation history item
        """
        self.redis_lock = redis_lock
        self.history = history

    async def __enter__(self) -> "ConversationHistory":
        """ Acquire the lock.
        Returns: History item
        """
        await self.redis_lock.acquire(blocking=True)
        return self.history

    async def __exit__(self):
        """ Release the lock.
        """
        await self.redis_lock.release()

    
class ConversationHistory(BaseModel):
    """ History of messages between users.
    Fields:
    - interacting_user_id: ID of the user (not the bot) with which the conversation is being had
    - messages: List of messages, ordered where first message is the oldest and last message is the newest
    """
    interacting_user_id: int
    messages: List[HistoryMessage]

class ConversationHistoryRepoObject(ConversationHistory):
    """ Extends the pure dataclass ConversationHistory with database operations.
    Fields:
    - redis_client: The Redis client
    - username_mapper: Implementation of usernames mapper
    """    
    _redis_client: redis.Redis
    _usernames_mapper: UsernamesMapper
    _redis_key: str

    def __init__(self, redis_client: redis.Redis, usernames_mapper: UsernamesMapper, redis_key: str, interacting_user_id: int, messages: List[HistoryMessage]):
        """ Initializes.
        """
        super().__init__(interacting_user_id=interacting_user_id, messages=messages)

        self._redis_client = redis_client
        self._usernames_mapper = usernames_mapper
        self._redis_key = redis_key

    async def save(self):
        """ Save conversation history.
        """
        raw_json = json.dumps(self.dict())

        await self._redis_client.set(self._redis_key, raw_json)

    async def lock(self) -> ConversationHistoryLock:
        return ConversationHistoryLock(
            redis_lock=self._redis_client.lock(f"{self._redis_key}:lock"),
            history=self,
        )

    async def as_transcript_lines(self) -> Tuple[List[str], int]:
        """ Converts history into transcript lines.
        Arguments:
        - usernames_mapper: Implementation of username mapper

        Returns: (List of transcript lines, Total length of transcript lines in characters)
        """
        lines = []
        total_len = 0
        for msg in self.messages:
            line = await msg.as_transcript_str(self._usernames_mapper)
            lines.append(line)
            total_len += len(line)

        return (lines, total_len)

    async def trim(self, max_characters: int):
        """ Remove the oldest conversation history items until the length of all the transcript lines is less than max_characters.
        Arguments:
        - max_characters: Length which to trim
        """
        _, transcript_len = await self.as_transcript_lines(self._usernames_mapper)

        while transcript_len > max_characters:
            # Remove oldest messages
            removed_msg = self.messages.pop(0)
            transcript_len -= len(removed_msg.as_transcript_str(self._usernames_mapper))

class ConversationHistoryRepo:
    """ Retrieves conversation history objects.
    Fields:
    - redis_client: The Redis client
    - username_mapper: Implementation of usernames mapper
    """
    redis_client: redis.Redis
    usernames_mapper: UsernamesMapper

    def __init__(self, redis_client: redis.Redis, usernames_mapper: UsernamesMapper):
        """ Initializes.
        """
        self.redis_client = redis_client
        self.usernames_mapper = usernames_mapper

    def get_redis_key(self, interacting_user_id: int) -> str:
        """ Generate the Redis key for a conversation history item.
        Arguments:
        - interacting_user_id: ID of user (not bot) with which the conversation is being had

        Returns: The redis key
        """
        return f"conversation-history:interacting-user-id:{interacting_user_id}"

    async def get(self, interacting_user_id: int) -> ConversationHistoryRepoObject:
        """ Retrieve history for a conversation.
        Arguments:
        - interacting_user_id: ID of user (not bot) with which the conversation is being had

        Returns: The conversation history item, or None if not stored for the interacting_user_id
        """
        redis_key = self.get_redis_key(interacting_user_id)

        # Retrieve data from Redis
        raw_json = await self.redis_client.get(redis_key)
        if raw_json is None:
            # Redis key does not exist
            return ConversationHistoryRepoObject(
                redis_client=self.redis_client,
                usernames_mapper=self.usernames_mapper,
                redis_key=redis_key,
                interacting_user_id=interacting_user_id,
                messages=[],
            )
        
        parsed_json = json.loads(raw_json)

        return ConversationHistoryRepoObject(
            redis_client=self.redis_client,
            usernames_mapper=self.usernames_mapper,
            redis_key=redis_key,
            **parsed_json,
        )