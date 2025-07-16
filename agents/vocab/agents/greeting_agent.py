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

logger = get_logger(__name__)


class GreetingAgent(LivekitAgent):
    def __init__(self, context: AgentContext) -> None:
        nickname = context.user_info.nick_name

        # 获取北京时间
        beijing_tz = pytz.timezone('Asia/Shanghai')
        now = datetime.now(beijing_tz)

        last_communication_time = context.last_communication_time
        if last_communication_time:
            instructions = f"""
            Give a casual, friendly greeting to {nickname} who just came back. Be like a friend or a foreigner english teacher, not an assistant. Keep it simple and natural. Just one short sentence.

            Here are some information to you for reference: 
            last interaction was at {last_communication_time.isoformat()}, current time is {now.isoformat()}.
            """
        else:
            instructions = f"""
            Give a casual, friendly greeting to {nickname}. Be like a friend, not an assistant. Keep it simple and natural. Just one short sentence.

            Here are some information to you for reference: this is the first learning session of the day, current time is {now.isoformat()}.
            """

        history_str = ""
        for item in context.chat_context.items:
            if not isinstance(item, LivekitChatMessage):
                continue

            if item.role == "user":
                history_str += f"User：{item.text_content}\n"
            else:
                history_str += f"AI Teacher：{item.text_content}\n"

        instructions += f"""
        After exchanging pleasantries, seamlessly hand off the conversation to the appropriate teaching agent **without exposing the agent switch to the user**.
        
        Previous conversation history is provided below for context.
        ```
        {history_str}
        ```
        """

        super().__init__(
            instructions=instructions,
        )

    async def on_enter(self):
        logger.info(f"GreetingAgent on_enter")
        await self.session.generate_reply(allow_interruptions=False)

    @function_tool
    async def handoff_to_teaching_agent(
        self,
        context: RunContext[AgentContext],
    ):
        """Dispatch the conversation to the appropriate teaching agent based on user context."""
        
        from agents.vocab.agents.route_analysis import RouteAnalysisAgent
        from agents.vocab.agents.main_schedule_agent import MainScheduleAgent
        from agents.vocab.context import VocabularyPhase
        
        logger.info(f"handoff_to_teaching_agent: {context.userdata.phase}")
        agent_context = context.userdata

        if context.userdata.phase == VocabularyPhase.ANALYSIS_ROUTE:
            agent = RouteAnalysisAgent(context=agent_context)
        else:
            agent = MainScheduleAgent(context=agent_context)

        return agent, None
