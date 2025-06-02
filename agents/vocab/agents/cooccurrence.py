from livekit.agents import (
    Agent,
    RunContext,
)
from livekit.agents.llm import function_tool
from agents.vocab.context import AgentContext
from bamboo_shared.agent.instructions import TemplateVariables, get_instructions
from agents.vocab.agents.sentence_practice import SentencePracticeAgent
from bamboo_shared.logger import get_logger


logger = get_logger(__name__)

class CooccurrenceAgent(Agent):
    def __init__(self, context: AgentContext) -> None:
        self.template_variables = TemplateVariables(
            word=context.word,
            nickname=context.user_info.nickname,
            user_english_level=context.user_info.english_level,
            user_characteristics=context.user_characteristics
        )
        instructions = get_instructions(
            self.template_variables,
            "cooccurrence",
        )
        super().__init__(instructions=instructions)
        self.context = context

    async def on_enter(self):
        await self.session.generate_reply(
            instructions=f"In Chinese, start discussing co-occurring words for '{self.template_variables.word}'. Introduce just one type or example. Explain briefly in Chinese. Ask a question."
        )

    @function_tool
    async def start_practice(
        self,
        context: RunContext[AgentContext],
    ):
        """Call this function ONLY after interactively discussing the main co-occurrence patterns."""
        logger.info("Handing off to SentencePracticeAgent after completing co-occurrence discussion.")
        practice_agent = SentencePracticeAgent(context=context.userdata)
        return practice_agent, None
