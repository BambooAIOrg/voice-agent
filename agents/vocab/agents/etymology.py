from bamboo_shared.agent.instructions import TemplateVariables, get_instructions
from livekit.agents import (
    Agent,
    RunContext,
)
from livekit.agents.llm import function_tool
from agents.vocab.context import AgentContext
from agents.vocab.agents.synonym import SynonymAgent
from logger import get_logger

logger = get_logger(__name__)

# Placeholder for the next agent - will be implemented next
class EtymologyAgent(Agent):
    def __init__(self, context: AgentContext) -> None:
        self.template_variables = TemplateVariables(
            word=context.word,
            nickname=context.user_info.nickname,
            user_english_level=context.user_info.english_level,
            user_characteristics=context.user_characteristics
        )
        instructions = get_instructions(
            self.template_variables,
            "etymology",
        )
        super().__init__(instructions=instructions)
        self.context = context

    async def on_enter(self):
        logger.info(f"etymology agent enter")
        await self.session.generate_reply(
            instructions=f"In Chinese, start explaining the origin (来源) of '{self.template_variables.word}'. Keep it brief. Ask if understood."
        )

    @function_tool
    async def start_synonyms(
        self,
        context: RunContext[AgentContext],
    ):
        """Call this function ONLY after interactively discussing origin, root, and affixes in Chinese."""
        logger.info("Handing off to SynonymAgent after completing etymology discussion.")
        synonym_agent = SynonymAgent(context=context.userdata)
        return synonym_agent, None
