from livekit.agents import (
    Agent,
    RunContext,
)
from livekit.agents.llm import function_tool
from agents.vocab.agents.cooccurrence import CooccurrenceAgent
from agents.vocab.context import AgentContext
from bamboo_shared.agent.instructions import TemplateVariables, get_instructions
from logger import get_logger

logger = get_logger(__name__)

class SynonymAgent(Agent):
    def __init__(self, context: AgentContext) -> None:
        self.template_variables = TemplateVariables(
            word=context.word,
            nickname=context.user_info.nickname,
            user_english_level=context.user_info.english_level,
            user_characteristics=context.user_characteristics
        )
        instructions = get_instructions(
            self.template_variables,
            "synonym",
        )
        super().__init__(instructions=instructions)
        self.context = context

    async def on_enter(self):
        await self.session.generate_reply(
            instructions=f"In Chinese, start discussing synonyms for '{self.template_variables.word}'. Introduce just one aspect (e.g., one synonym or one difference). Explain briefly in Chinese. Ask a question."
        )

    @function_tool
    async def start_cooccurrence(
        self,
        context: RunContext[AgentContext],
    ):
        """Call this function ONLY after interactively discussing the main synonyms and differences."""
        logger.info("Handing off to CooccurrenceAgent after completing synonym discussion.")
        cooccurrence_agent = CooccurrenceAgent(context=context.userdata)
        return cooccurrence_agent, None

