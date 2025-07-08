from datetime import datetime
from dataclasses import dataclass
from typing import Any, Dict
from bamboo_shared.enums.official_website import OfficialWebsitePhase
from bamboo_shared.repositories import ChatRepository
from agents.official_website.service.message_service import MessageService
from bamboo_shared.logger import get_logger
from livekit.agents.llm.chat_context import ChatContext
import asyncio

logger = get_logger(__name__)


@dataclass
class Context:
    """official_website learning context"""

    visitor_id: str
    current_word: str
    chat_context: ChatContext
    phase: OfficialWebsitePhase
    last_communication_time: datetime | None

    def __init__(self, visitor_id: str, current_word: str, chat_context: ChatContext, phase: OfficialWebsitePhase, last_communication_time: datetime | None):
        self.visitor_id = visitor_id
        self.current_word = current_word
        self.chat_context = chat_context
        self.phase = phase
        self.last_communication_time = last_communication_time
        self.chat_repo = ChatRepository(0)

    def get_metadata(self) -> Dict[str, Any]:
        return {
            "phase": self.phase.value,
        }


class AgentContext(Context):
    def __init__(self, visitor_id: str):
        self.visitor_id = visitor_id

    async def initialize_async_context(self):
        await asyncio.gather(
            self._initialize_chat_context(),
            self._initialize_word(),
        )

    async def _initialize_chat_context(self):
        message_service = MessageService(self.visitor_id)
        chat_context, phase, last_communication_time = await message_service.get_chat_context_and_phase()
        self.chat_context = chat_context
        self.phase = phase
        self.last_communication_time = last_communication_time

    async def _initialize_word(self):
        # 官网用于演示的单词列表,随机选择一个
        self.current_word = "item"