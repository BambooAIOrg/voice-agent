from datetime import datetime
from livekit.agents import (
    RunContext,
)
from livekit.agents.llm import function_tool
import pytz

from agents.vocab.context import AgentContext
from bamboo_shared.logger import get_logger
from livekit.agents import Agent as LivekitAgent

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

        logger.info(f"instructions: {instructions}")
        super().__init__(
            instructions=instructions,
        )

    async def on_enter(self):
        logger.info("GreetingAgent on_enter")
        # await super().on_enter()
        logger.info("GreetingAgent on_enter after super")
        await self.session.generate_reply()

    @function_tool
    async def start_learning(
        self,
        context: RunContext[AgentContext],
    ):
        """Call this function ONLY after interactively discussing origin, root, and affixes in Chinese."""
        from agents.vocab.agents.co_occurrence import CoOccurrenceAgent
        from agents.vocab.agents.synonym import SynonymAgent
        from agents.vocab.agents.word_creation_analysis import WordCreationAnalysisAgent
        from agents.vocab.agents.route_analysis import RouteAnalysisAgent
        from agents.vocab.agents.sentence_practice import SentencePracticeAgent
        from agents.vocab.context import VocabularyPhase
        
        agent_context = context.userdata
        match context.userdata.phase:
            case VocabularyPhase.ANALYSIS_ROUTE:
                agent = RouteAnalysisAgent(context=agent_context)
            case VocabularyPhase.WORD_CREATION_LOGIC:
                agent = WordCreationAnalysisAgent(context=agent_context)
            case VocabularyPhase.SYNONYM_DIFFERENTIATION:
                agent = SynonymAgent(context=agent_context)
            case VocabularyPhase.CO_OCCURRENCE:
                agent = CoOccurrenceAgent(context=agent_context)
            case VocabularyPhase.QUESTION_ANSWER:
                agent = SentencePracticeAgent(context=agent_context)
            case _:
                raise ValueError(f"Invalid phase: {agent_context.phase}")

        return agent, None
