from datetime import datetime
from livekit.agents import (
    RunContext,
)
from livekit.agents.llm import function_tool
import pytz

from agents.vocab.context import AgentContext
from bamboo_shared.logger import get_logger
from livekit.agents import Agent as LivekitAgent
from livekit.agents.llm.chat_context import ChatMessage as LivekitChatMessage
from bamboo_shared.agent.instructions import prompt_with_voice_mindset_instructions
from livekit import rtc

logger = get_logger(__name__)

class GreetingAgent(LivekitAgent):
    def __init__(self, context: AgentContext, room: rtc.Room) -> None:
        self.context = context
        self.room = room
        nickname = context.user_info.nick_name

        # 获取北京时间
        beijing_tz = pytz.timezone('Asia/Shanghai')
        now = datetime.now(beijing_tz)

        instructions = self._build_instructions(nickname, now, context.last_communication_time)

        super().__init__(
            instructions=instructions,
        )

    def _get_history_chat_str(self) -> str:
        history_str = ""
        for item in self.context.chat_context.items:
            if not isinstance(item, LivekitChatMessage):
                continue

            match item.role:
                case "user":
                    history_str += f"User：{item.text_content}\n"
                case "assistant":
                    history_str += f"AI Teacher：{item.text_content}\n"
                case _:
                    continue

        return history_str

    def _build_instructions(self, nickname: str, now: datetime, last_communication_time: datetime | None) -> str:
        """Build greeting instructions based on user context."""

        if last_communication_time:
            time_info = f"\n - The last interaction was at {last_communication_time.isoformat()}, current time is {now.isoformat()}"
        else:
            time_info = f"\n - This is the first vocabulary learning session of the day, current time is {now.isoformat()}"
  
        history_str = self._get_history_chat_str()
        if history_str:
            history_context = f"- Previous conversation history for context: ```{history_str}```"
        else:
            history_context = ""

        return prompt_with_voice_mindset_instructions(
            f"Begin by exchanging pleasantries with the user {nickname} and wait for the user's reply."
            f"Be like a friend or a foreigner english teacher, not an assistant. "
            f"Keep it simple and natural. Just one short sentence."
            f"Once the user responds, silently call the start_learning function to hand off the conversation to the teaching agent, without exposing the switch."
            f"\n Here is some information that may be useful for context: "
            f"{time_info}"
            f"{history_context}"
        )

    async def on_enter(self):
        logger.info(f"GreetingAgent on_enter")
        await self.session.generate_reply(allow_interruptions=False)

    @function_tool
    async def transfer_to_teaching_agent(
        self,
        context: RunContext[AgentContext],
    ):
        """Dispatch the conversation to the appropriate teaching agent based on user context."""
        
        from agents.vocab.agents.route_analysis import RouteAnalysisAgent
        from agents.vocab.agents.main_schedule_agent import MainScheduleAgent
        from agents.vocab.context import VocabularyPhase
        
        try:
            logger.info(f"handoff_to_teaching_agent: {context.userdata.phase}")
            agent_context = context.userdata

            for item in self._chat_ctx.items:
                agent_context.chat_context.insert(item)

            logger.info(f"chat_context: {self._chat_ctx.to_dict()}")
            logger.info(f"chat_context: {agent_context.chat_context.to_dict()}")
            if context.userdata.phase == VocabularyPhase.ANALYSIS_ROUTE:
                agent = RouteAnalysisAgent(context=agent_context, room=context.room)
            else:
                agent = MainScheduleAgent(context=agent_context, room=context.room)

            return agent, None
        except Exception as e:
            logger.error(f"Error in handoff_to_teaching_agent: {e}")
            return None, "An error occurred while handing off to the teaching agent."
