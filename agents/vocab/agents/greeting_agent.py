from datetime import datetime
from livekit.agents import (
    Agent,
    RunContext,
)
from livekit.agents.llm import function_tool
import pytz

from agents.vocab.context import AgentContext
from bamboo_shared.logger import get_logger

logger = get_logger(__name__)


class GreetingAgent(Agent):
    def __init__(self, context: AgentContext) -> None:
        nickname = context.user_info.nick_name

        # 获取北京时间
        beijing_tz = pytz.timezone('Asia/Shanghai')
        now = datetime.now(beijing_tz)

        last_communication_time = context.last_communication_time
        instructions = ''
        if last_communication_time:
            instructions = f"The user, {nickname}, has returned to continue their learning session. Their last interaction was at {last_communication_time.isoformat()}. Please give the user welcome back and ask if they are ready to pick up where they left off."
        else:
            instructions = f"This is the first learning session of the day for the user {nickname}. The current time is {now.isoformat()}. Greeting with the user. Just a simple greeting is enough."

        instructions += """
            \n\nAfter the greeting, call the start_learning to start the learning session.
        """

        logger.info(f"instructions: {instructions}")
        super().__init__(
            instructions=instructions,
        )
        self.context = context

    async def on_enter(self):
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
