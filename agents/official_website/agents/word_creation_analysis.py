from bamboo_shared.agent.instructions import TemplateVariables, get_instructions
from livekit.agents import (
    Agent,
    RunContext,
)
from livekit.agents.llm import function_tool, ChatContext
from agents.vocab.context import AgentContext
from agents.vocab.agents.synonym import SynonymAgent
from bamboo_shared.logger import get_logger


logger = get_logger(__name__)

# Placeholder for the next agent - will be implemented next
class WordCreationAnalysisAgent(Agent):
    def __init__(self, context: AgentContext) -> None:
        self.template_variables = TemplateVariables(
            word='sss',
            nickname='sss',
            user_english_level='sss',
            user_characteristics='sss'
        )
        instructions = get_instructions(
            self.template_variables,
            "word_creation_logic",
        )
        super().__init__(
            instructions=instructions,
            chat_ctx=context.chat_context
        )
        self.context = context

    # async def on_enter(self):
    #     logger.info(f"etymology agent enter")
    #     await self.session.generate_reply(
    #         instructions=f"start the etymology part of the lesson"
    #     )

    @function_tool
    async def start_synonyms(
        self,
        context: RunContext[AgentContext],
    ):
        """Call this function ONLY after interactively discussing origin, root, and affixes in Chinese."""
        logger.info("Handing off to SynonymAgent after completing etymology discussion.")
        synonym_agent = SynonymAgent(context=context.userdata, chat_ctx=context.session._chat_ctx)
        return synonym_agent, None
