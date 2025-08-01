from datetime import datetime
from enum import Enum
from dataclasses import dataclass
from typing import Any, Dict, List, Sequence
from bamboo_shared.models import (
    User,
    Vocabulary,
    ChatReference,
    ChatMessage,
    Chat,
)
from bamboo_shared.enums.vocabulary import VocabularyPhase
from bamboo_shared.repositories import (
    ChatRepository,
    UserRepository,
    ChatReferenceRepository,
    VocabularyRepository,
)
from bamboo_shared.service.vocabulary import WordTask, VocabPlanService
from bamboo_shared.logger import get_logger
from livekit.agents.llm.chat_context import ChatContext, ChatItem, FunctionCall, FunctionCallOutput, ChatMessage as LivekitChatMessage
import asyncio
import uuid

logger = get_logger(__name__)


class ContextInitializationError(Exception):
    """Raised when agent context initialization fails"""
    pass

class EnglishLevel(Enum):
    """CEFR English level enum"""

    A1 = "A1"
    A2 = "A2"
    B1 = "B1"
    B2 = "B2"
    C1 = "C1"
    C2 = "C2"


@dataclass
class UserEnglishLevel:
    """user's English level"""

    listening: EnglishLevel
    reading: EnglishLevel
    writing: EnglishLevel
    speaking: EnglishLevel

    def __str__(self) -> str:
        """format the english level"""
        return (
            f"listening: {self.listening.value}, "
            f"reading: {self.reading.value}, "
            f"writing: {self.writing.value}, "
            f"speaking: {self.speaking.value}"
        )



@dataclass
class Context:
    """vocabulary learning context"""

    # user info
    user_info: User
    user_characteristics: str  # user's interests, learning preferences, etc.
    english_level: UserEnglishLevel

    # word info
    word: Vocabulary
    # learning status
    chat_reference: ChatReference
    phase: VocabularyPhase
    task_list: List[WordTask]
    last_communication_time: datetime | None
    chat_context: ChatContext

    def __init__(self, user_info: User, user_characteristics: str, english_level: UserEnglishLevel, word: Vocabulary, chat_reference: ChatReference, task_list: List[WordTask]):
        self.user_info = user_info
        self.user_characteristics = user_characteristics
        self.english_level = english_level
        self.word = word
        self.chat_reference = chat_reference
        self.task_list = task_list
        self.chat_repo = ChatRepository(user_info.id)

    def get_formatted_characteristics(self) -> str:
        """get the formatted user characteristics"""
        return self.user_characteristics

    def get_formatted_english_level(self) -> str:
        """get the formatted English level"""
        return str(self.english_level)

    def get_image_url(self) -> str:
        IMAGE_URL_PREFIX = "https://platform.bambooai.top/api/file/images/key"
        return f"{IMAGE_URL_PREFIX}/{self.word.sentence_image_key}"

    def get_example_sentence(self) -> str:
        return self.word.sentence

    def get_metadata(self) -> Dict[str, Any]:
        return {
            "phase": self.phase.value,
            "word_id": self.word.id,
            "word": self.word.word,
        }
    
    async def go_next_word(self):
        """进入下一个单词的学习"""
        chat_reference_repo = ChatReferenceRepository(self.user_info.id)
        await chat_reference_repo.update_phase(self.chat_reference.id, VocabularyPhase.QUESTION_ANSWER)

        # 获取当前chat的最后一条消息ID，用于连接到下一个单词的chat
        chat_repo = ChatRepository(self.user_info.id)
        
        next_word_task = None
        # 从word_list中找到下一个还没学完的单词
        for task in self.task_list:
            if task.word_id == self.word.id:
                continue

            if task.phase is None or (
                task.phase != VocabularyPhase.QUESTION_ANSWER.value
            ):
                next_word_task = task
                break

        if next_word_task is None:
            # 如果没有找到下一个未完成的单词，返回None
            return None

        # 获取下一个单词的详细信息
        vocab_repo = VocabularyRepository(self.user_info.id)
        next_word = await vocab_repo.get_by_id(next_word_task.word_id)

        if next_word:
            chat_id = await chat_repo.ensure_chat(
                chat_id=next_word_task.chat_id,
                chat_type="vocabulary",
                title=next_word.word
            )
            parent_chat_id = self.chat_reference.chat_id
            prev_chat = await chat_repo.get_chat(parent_chat_id)

            logger.info(f"Transitioning to next word: {next_word.word}, prev_chat: {prev_chat.to_dict() if prev_chat else None}, parent_chat_id: {parent_chat_id}")
            self.chat_id = chat_id
            
            if not prev_chat or not prev_chat.current_node:
                raise ValueError(f"prev_chat.current_node is None, parent_chat_id: {parent_chat_id} prev_chat: {prev_chat}")

            self.word = next_word
            self.phase = VocabularyPhase.WORD_CREATION_LOGIC
            self.chat_reference = await vocab_repo.ensure_chat_reference(
                next_word.id, chat_id
            )

            logger.info(f"go to next word: {next_word.word}")
            return next_word

        return None


class AgentContext(Context):
    def __init__(self, user_id: int, word_id: int, chat_id: str | None = None):
        self.user_id = user_id
        self.word_id = word_id
        self.chat_id = chat_id
        self.chat_repo = ChatRepository(user_id)
        self.chat_reference_repo = ChatReferenceRepository(user_id)
        self.word_repo = VocabularyRepository(user_id)
        self.user_repo = UserRepository(user_id)
        self.english_level = UserEnglishLevel(
            listening=EnglishLevel.A1,
            reading=EnglishLevel.A1,
            writing=EnglishLevel.A1,
            speaking=EnglishLevel.A1
        )
        self.chat_context = ChatContext()
        self.chat_history = []
        self.last_communication_time = None
        self.current_node = None

    def update_chat_current_node(self, message_id: str):
        self.current_node = message_id

    async def initialize_async_context(self):
        """Initialize all async context components with proper error handling"""
        try:
            start_time = asyncio.get_event_loop().time()
            
            # Initialize word and user info first (they can run in parallel)
            user_task = asyncio.create_task(self._initialize_user_info())
            word_task = asyncio.create_task(self._initialize_word_task())
            
            await asyncio.gather(user_task, word_task)
            user_word_time = asyncio.get_event_loop().time()
            
            # Initialize chat context after word is available
            await self._initialize_chat_context()
            
            total_time = asyncio.get_event_loop().time() - start_time
            chat_time = asyncio.get_event_loop().time() - user_word_time
            
            logger.info(f"Context initialization completed - Total: {total_time:.2f}s, Chat context: {chat_time:.2f}s")
            
        except Exception as e:
            logger.error(f"Unexpected error during context initialization: {e}")
            raise ContextInitializationError(f"Context initialization failed: {e}") from e

    async def _initialize_chat_context(self):
        chat_start_time = asyncio.get_event_loop().time()
        
        logger.info(f"Initializing chat context for user_id: {self.user_id}, word_id: {self.word_id}, chat_id: {self.chat_id}")
        if not self.chat_id:
            # New chat creation - minimal overhead
            self.chat_id = str(uuid.uuid4())
            chat_task = asyncio.create_task(self.chat_repo.create_chat(Chat(
                id=self.chat_id,
                user_id=self.user_id,
                type="vocabulary",
                title=self.word.word,
            )))
            chat_ref_task = asyncio.create_task(self.chat_reference_repo.create(ChatReference(
                user_id=self.user_id,
                chat_id=self.chat_id,
                reference_id=self.word_id,
                reference_type="vocabulary",
                phase=VocabularyPhase.ANALYSIS_ROUTE.value
            )))
            
            chat, chat_reference = await asyncio.gather(chat_task, chat_ref_task)
            self.chat_reference = chat_reference
            self.phase = VocabularyPhase.ANALYSIS_ROUTE
            self.chat_context = ChatContext()
            
            logger.debug(f"New chat created in {asyncio.get_event_loop().time() - chat_start_time:.2f}s")
        else:
            # Existing chat - optimize heavy operations
            chat_reference = await self.word_repo.ensure_chat_reference(
                self.word_id,
                self.chat_id
            )
            self.chat_reference = chat_reference
            
            vocab_service = VocabPlanService()
            chat_task = asyncio.create_task(self.chat_repo.get_by_id(chat_reference.chat_id))
            chat_ids_task = asyncio.create_task(vocab_service.get_current_group_chat_ids(self.user_id))
            
            chat, chat_id_list = await asyncio.gather(chat_task, chat_ids_task)
            
            if not chat:
                raise ValueError(f"Chat not found for chat_reference: {chat_reference.id}")
            
            # Load and convert chat history
            chat_history = await self.chat_repo.get_chat_messages_by_chat_ids(chat_id_list)
            
            self.chat_context = await self.convert_chat_history_to_chat_context(chat_history)
            
            current_message = next((msg for msg in chat_history if msg.id == chat.current_node), None)
            if not current_message:
                raise ValueError(f"Current message not found for chat_id: {chat.id}, current_node: {chat.current_node}")
            
            self.phase = VocabularyPhase(current_message.meta_data.get("phase"))
            self.last_communication_time = current_message.create_time
            self.update_chat_current_node(current_message.id)
            

    async def _initialize_user_info(self):
        """Initialize user information with proper error handling"""
        try:
            user = await self.user_repo.get_by_id(self.user_id)
            if not user:
                raise ValueError(f"User not found, user_id: {self.user_id}")
            
            # Ensure hobbies field is not None
            if not user.hobbies:
                user.hobbies = ""
            
            self.user_info = user
            self.user_characteristics = f"""
                Hobbies: {user.hobbies}
            """.strip()
            
            logger.debug(f"User info initialized for user_id: {self.user_id}")
            
        except Exception as e:
            logger.error(f"Failed to initialize user info for user_id {self.user_id}: {e}")
            raise

    async def _initialize_word_task(self):
        """Initialize word and task information with proper error handling"""
        try:
            # Initialize word first
            self.word = await self.word_repo.get_by_id(self.word_id)
            if not self.word:
                raise ValueError(f"Word not found, word_id: {self.word_id}")
            
            # Initialize task list
            service = VocabPlanService()
            self.task_list = await service.get_daily_word_task_detail(self.user_id)
            
            logger.debug(f"Word task initialized for word_id: {self.word_id}, word: {self.word.word}")
            
        except Exception as e:
            logger.error(f"Failed to initialize word task for word_id {self.word_id}, user_id {self.user_id}: {e}")
            raise

    async def convert_chat_history_to_chat_context(self, chat_history: Sequence[ChatMessage]) -> ChatContext:
        chat_context_items: list[ChatItem] = []

        # Define agent handoff function names to filter out
        agent_handoff_functions = {
            "transfer_to_teaching_agent",
            "transfer_to_main_schedule_agent", 
            "transfer_to_next_word_agent"
        }

        for msg in chat_history:
            if msg.meta_data.get("is_transition"):
                continue

            if msg.type == "function_call":
                function_name = msg.content["function"]["name"]
                # Skip agent handoff function calls
                if function_name in agent_handoff_functions:
                    logger.debug(f"Skipping agent handoff function call: {function_name}")
                    continue
                    
                logger.info(f"msg.content: {msg.content}")
                chat_context_items.append(FunctionCall(
                    id=msg.id,
                    type="function_call",
                    call_id=msg.content["call_id"],
                    name=function_name,
                    arguments=msg.content["function"]["arguments"],
                ))
            elif msg.type == "function_call_output":
                function_name = msg.content["tool_name"]
                # Skip agent handoff function outputs
                if function_name in agent_handoff_functions:
                    logger.debug(f"Skipping agent handoff function output: {function_name}")
                    continue
                    
                chat_context_items.append(FunctionCallOutput(
                    id=msg.id,
                    type="function_call_output",
                    call_id=msg.content["tool_call_id"],
                    name=function_name,
                    output=msg.content["output"],
                    is_error=True if msg.content["error"] else False,
                ))
            elif msg.type == "message" and msg.content is not None:
                logger.info(f"msg.type: {msg.type}")
                chat_context_items.append(LivekitChatMessage(
                    id=msg.id,
                    type="message",
                    role=msg.author.get("role"),
                    content=[msg.content],
                    created_at=msg.create_time.timestamp(),
                ))

        return ChatContext(items=chat_context_items)
