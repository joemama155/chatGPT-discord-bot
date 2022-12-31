import os
import json
from typing import List, Optional

from pydantic import BaseModel
import redis.asyncio as redis

class HistoryMessage(BaseModel):
    """ One message sent by one user.
    Fields:
    - author_id: ID of user who sent message
    - body: The text sent in the message
    """
    author_id: int
    body: str
    
class ConversationHistory(BaseModel):
    """ History of messages between users.
    Fields:
    - interacting_user_id: ID of the user (not the bot) with which the conversation is being had
    - messages: List of messages, ordered where first message is the oldest and last message is the newest
    """
    interacting_user_id: int
    messages: List[HistoryMessage]

    def all_messages_body_len(self) -> int:
        """ Count the length of all message body's.
        Returns: Count of characters.
        """
        count = 0
        for msg in self.messages:
            count += len(msg.body)

        return count

class MessageHistoryRepo:
    """ Records, retrieves, and manipulates message history.
    Message history is stored for conversations between the bot and a user. The history between the bot and multiple users is not stored because there is a maximum length which a prompt can be for GPT3, so the most relevant data (aka data between a specific user and the bot) is stored.
    
    Fields:
    - redis_client: The Redis client
    """
    redis_client: redis.Redis

    async def __init__(self):
        """ Initializes.
        Creates the Redis client from the REDIS_{HOST,PORT,DB} env vars.
        """
        self.redis_client = redis.Redis(
            host=os.getenv('REDIS_HOST', "redis"),
            port=int(os.getenv('REDIS_PORT', "6379")),
            db=int(os.getenv('REDIS_DB', "0")),
        )

    def get_conversation_history_key(self, interacting_user_id: int) -> str:
        """ Generate the Redis key for a conversation history item.
        Arguments:
        - interacting_user_id: ID of user (not bot) with which the conversation is being had

        Returns: The redis key
        """
        return f"conversation-history:interacting-user-id:{interacting_user_id}"

    def get_conversation_history_lock_key(self, interacting_user_id: int) -> str:
        """ Generate the Redis key for a conversation history item's lock.
        Arguments:
        - interacting_user_id: ID of user (not bot) with which the conversation is being had

        Returns: The redis lock key
        """
        return f"conversation-history:interacting-user-id:{interacting_user_id}:lock"

    async def get_conversation_history(self, interacting_user_id: int) -> Optional[ConversationHistory]:
        """ Retrieve history for a conversation.
        Arguments:
        - interacting_user_id: ID of user (not bot) with which the conversation is being had

        Returns: The conversation history item, or None if not stored for the interacting_user_id
        """
        redis_key = self.get_conversation_history_key(interacting_user_id)

        # Retrieve data from Redis
        raw_json = await self.redis_client.get(redis_key)
        if raw_json is None:
            # Redis key does not exist
            return None
        
        parsed_json = json.loads(raw_json)

        return ConversationHistory(**parsed_json)

    async def save_conversation_history(self, history: ConversationHistory):
        """ Save conversation history.
        Arguments:
        - history: The conversation history to save
        """
        redis_key = self.get_conversation_history_key(history.interacting_user_id)
        raw_json = json.dumps(history.dict())

        await self.redis_client.set(redis_key, raw_json)

    async def append_message(self, interacting_user_id: int, msg: HistoryMessage, max_conversation_characters: int) -> ConversationHistory:
        """ Store a new message as part of a conversation.
        Ensures that with the new message the total size of all messages in the history does not exceed max_conversation_characters. If adding the message would exceed this limit then the oldest messages will be removed to make the new message fit.
        Arguments:
        - interacting_user_id: ID of the user (not the bot) with which this conversation is being had
        - msg: The message to store, should be the most recent message in the conversation
        - max_conversation_characters: The maximum number of characters which the total of all conversation items should not exceed

        Returns: The conversation history with the message added
        """
        # Acquire a lock so no one else modifies this history
        async with self.redis_client.lock(self.get_conversation_history_lock_key(interacting_user_id)):
            # Get existing history
            history = await self.get_conversation_history(interacting_user_id)

            if history is None:
                # Initialize new history
                history = ConversationHistory(
                    interacting_user_id=interacting_user_id,
                    messages=[],
                )

            # Append message
            history.messages.append(msg)

            # Remove messages until below max length
            history_len = history.all_messages_body_len()

            while history_len > max_conversation_characters:
                # Remove oldest messages
                removed_msg = history.messages.pop(0)
                history_len -= len(removed_msg.body)

            # Save new history
            await self.save_conversation_history(history)

            return history
