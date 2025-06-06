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
class EtymologyAgent(Agent):
    def __init__(self, context: AgentContext, chat_ctx: ChatContext) -> None:
        self.template_variables = TemplateVariables(
            word=context.word.word,
            nickname=context.user_info.nick_name,
            user_english_level=context.get_formatted_english_level(),
            user_characteristics=context.get_formatted_characteristics()
        )
        instructions = get_instructions(
            self.template_variables,
            "etymology",
        )
        super().__init__(
            instructions=instructions,
            chat_ctx=chat_ctx
        )
        self.context = context

    async def on_enter(self):
        logger.info(f"etymology agent enter")
        await self.session.generate_reply(
            instructions=f"start the etymology part of the lesson"
        )

    @function_tool
    async def start_synonyms(
        self,
        context: RunContext[AgentContext],
    ):
        """Call this function ONLY after interactively discussing origin, root, and affixes in Chinese."""
        logger.info("Handing off to SynonymAgent after completing etymology discussion.")
        synonym_agent = SynonymAgent(context=context.userdata, chat_ctx=context.session._chat_ctx)
        return synonym_agent, None
