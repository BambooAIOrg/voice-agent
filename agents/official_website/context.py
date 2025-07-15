from datetime import datetime
from dataclasses import dataclass
from typing import Any, Dict
import pytz
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

    def get_phase(self) -> str:
        return self.phase.value

    def update_phase(self, phase: OfficialWebsitePhase):
        self.phase = phase

    def get_phase_description(self, value: str) -> str:
        phase_description = {
            "vocabulary": "单词学习模块",
            "scene": "情境对话模块",
            "writing": "写作训练模块",
            "chat": "自由交流模块",
        }
        return phase_description[value]

    def get_say_greeting_instructions(self) -> str:
        # 获取北京时间
        beijing_tz = pytz.timezone('Asia/Shanghai')
        now = datetime.now(beijing_tz)

        last_communication_time = self.last_communication_time
        phase = self.phase
        current_word = self.current_word

        # 生成自然语言 instructions 提示词
        if last_communication_time:
            instructions = (
                f"用户上次交互时间为 {last_communication_time.isoformat()}，当前时间是 {now.isoformat()}。"
                f"目前用户正在介绍的产品功能模块的是：{self.get_phase_description(phase.value)}。"
                f"请用一句自然、热情、简洁的欢迎语欢迎用户回来，语气亲切温暖，不要太正式，可适当结合当前时间。"
            )
        else:
            instructions = (
                f"这是用户今天第一次进入产品介绍页面，当前时间是 {now.isoformat()}。"
                f"目前将介绍的产品功能模块是 {self.get_phase_description(phase.value)}。"
                f"请用一句自然、热情、简洁的欢迎语打招呼，语气亲切友好，不要太正式，可适当结合时间和模块特点。"
            )
        return  instructions


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