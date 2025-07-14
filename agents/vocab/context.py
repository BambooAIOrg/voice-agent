from datetime import datetime
from enum import Enum
from dataclasses import dataclass
from typing import Any, Dict, List
from bamboo_shared.models import (
    User,
    Vocabulary,
    VocabularyWebContent,
    ChatReference,
)
from bamboo_shared.enums.vocabulary import VocabularyPhase
from bamboo_shared.repositories import (
    ChatRepository,
    UserRepository,
    ChatReferenceRepository,
    VocabularyRepository,
    VocabularyWebContentRepository,
)
from bamboo_shared.service.vocabulary import WordTask, VocabPlanService
from agents.vocab.service.message_service import MessageService
from bamboo_shared.logger import get_logger
from livekit.agents.llm.chat_context import ChatContext
import asyncio

logger = get_logger(__name__)

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
    web_content: VocabularyWebContent
    # learning status
    chat_reference: ChatReference
    phase: VocabularyPhase
    task_list: List[WordTask]
    last_communication_time: datetime | None
    chat_context: ChatContext | None

    def __init__(self, user_info: User, user_characteristics: str, english_level: UserEnglishLevel, word: Vocabulary, web_content: VocabularyWebContent, chat_reference: ChatReference, task_list: List[WordTask]):
        self.user_info = user_info
        self.user_characteristics = user_characteristics
        self.english_level = english_level
        self.word = word
        self.web_content = web_content
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

    def get_web_image_results(self) -> list:
        return self.web_content.image_results

    def get_web_content_results(self) -> dict:
        return {
            "news_results": self.web_content.news_results,
            "interesting_results": self.web_content.interesting_results,
        }

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

            self.chat_id = chat_id
            
            if not prev_chat or not prev_chat.current_node:
                raise ValueError(f"prev_chat.current_node is None, parent_chat_id: {parent_chat_id} prev_chat: {prev_chat}")

            self.word = next_word
            self.phase = VocabularyPhase.WORD_CREATION_LOGIC
            self.chat_reference = await vocab_repo.ensure_word_reference(
                next_word.id, chat_id
            )

            logger.info(f"go to next word: {next_word.word}")
            return next_word

        return None


class AgentContext(Context):
    def __init__(self, chat_id: str, user_id: int, word_id: int, message_service: MessageService):
        self.chat_id = chat_id
        self.user_id = user_id
        self.word_id = word_id
        self.message_service = message_service
        self.chat_repo = ChatRepository(user_id)
        self.word_repo = VocabularyRepository(user_id)
        self.user_repo = UserRepository(user_id)
        self.web_content_repo = VocabularyWebContentRepository(user_id, chat_id)
        self.english_level = UserEnglishLevel(
            listening=EnglishLevel.A1,
            reading=EnglishLevel.A1,
            writing=EnglishLevel.A1,
            speaking=EnglishLevel.A1
        )
        self.chat_context = None

    async def initialize_async_context(self):
        await asyncio.gather(
            self._initialize_chat_context(),
            self._initialize_user_info(),
            self._initialize_chat_reference(),
            self._initialize_web_content(),
            self._initialize_word_task()
        )

    async def _initialize_chat_context(self):
        chat_context, phase, last_communication_time = await self.message_service.get_chat_context_and_phase()
        self.chat_context = chat_context
        self.phase = phase
        self.last_communication_time = last_communication_time

    async def _initialize_user_info(self):
        user = await self.user_repo.get_by_id(self.user_id)
        if not user:
            raise ValueError(f"user not found, user_id: {self.user_id}")
        
        if not user.hobbies:
            user.hobbies = ""
        
        self.user_info = user
        self.user_characteristics = f"""
            Hobbies: {user.hobbies}
        """.strip()

    async def _initialize_chat_reference(self):
        chat_reference = await self.word_repo.ensure_word_reference(
            self.word_id,
            self.chat_id
        )
        self.chat_reference = chat_reference

    async def _initialize_web_content(self):
        web_content = await self.web_content_repo.get_web_content(self.word_id)
        self.web_content = web_content

    async def _initialize_word_task(self):
        service = VocabPlanService()
        self.word = await self.word_repo.get_by_id(self.word_id)
        self.task_list = await service.get_daily_word_task_detail(self.user_id)
