from enum import Enum
from dataclasses import dataclass
from typing import Any, Dict, List
from uuid import uuid4
from bamboo_shared.models import (
    User,
    Vocabulary,
    VocabularyWebContent,
    ChatMessage,
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
from bamboo_shared.utils import time_now
from agents.vocab.service.message_service import MessageService
from agents.vocab.service.task_service import TaskService, WordTask
from bamboo_shared.logger import get_logger

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

    async def create_cross_chat_transition_message(
        self,
        parent_chat_id: str, 
        parent_message_id: str, 
        word: str
    ) -> ChatMessage:
        """
        create cross-chat transition message to connect different word learning sessions
        Args:
            parent_chat_id: the ID of the previous chat
            parent_message_id: the ID of the last message of the previous chat
            word: the new word to learn
            
        Returns:
            the transition message
        """
        message_id = str(uuid4())
        
        # create a special system message to connect different chats
        meta_data = {
            "is_transition": True,
            "parent_chat_id": parent_chat_id,
            "parent_message_id": parent_message_id,
            "new_word": word,
            "is_visually_hidden": True
        }
        
        transition_message = ChatMessage(
            id=message_id,
            author={"role": "system"},
            chat_id=self.chat_id,
            user_id=self.user_info.id,
            parent_message_id=None,  # this message has no regular parent message
            content=f"Start learning the new word: {word}",
            status="finished_successfully",
            meta_data=meta_data,
            create_time=time_now()
        )
        
        # save the message
        await self.chat_repo.save_messages([transition_message])
        return transition_message

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

            transition_message = await self.create_cross_chat_transition_message(
                parent_chat_id=parent_chat_id,
                parent_message_id=prev_chat.current_node,
                word=next_word.word
            )
            await chat_repo.update_chat_current_node(transition_message.id, chat_id)
            self.word = next_word
            self.phase = VocabularyPhase.ROOT_AFFIX_ANALYSIS
            self.chat_reference = await vocab_repo.ensure_word_reference(
                next_word.id, chat_id
            )

            logger.info(f"go to next word: {next_word.word}")
            return next_word

        return None


class AgentContext(Context):
    def __init__(self, chat_id: str, user_id: int, word_id: int):
        self.chat_id = chat_id
        self.user_id = user_id
        self.word_id = word_id
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

    async def initialize_async_context(self):
        await asyncio.gather(
            self._initialize_chat_context(),
            self._initialize_user_info(),
            self._initialize_chat_reference(),
            self._initialize_web_content(),
            self._initialize_word_task()
        )

    async def _initialize_chat_context(self):
        message_service = MessageService(self.user_id, self.chat_id)
        chat_context, phase = await message_service.get_chat_context_and_phase()
        self.chat_context = chat_context
        self.phase = phase

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
        service = TaskService()
        self.word = await self.word_repo.get_by_id(self.word_id)
        self.task_list = await service.get_daily_word_task_detail(self.user_id)
