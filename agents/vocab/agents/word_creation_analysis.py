from bamboo_shared.agent.instructions import TemplateVariables, get_instructions
from livekit.agents import (
    Agent,
    RunContext,
)
from livekit.agents.llm import function_tool

from agents.vocab.context import AgentContext
from bamboo_shared.logger import get_logger

logger = get_logger(__name__)

# Placeholder for the next agent - will be implemented next
class WordCreationAnalysisAgent(Agent):
    def __init__(self, context: AgentContext) -> None:
        self.template_variables = TemplateVariables(
            word=context.word.word,
            nickname=context.user_info.nick_name,
            user_english_level=context.get_formatted_english_level(),
            user_characteristics=context.get_formatted_characteristics()
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
    async def transfer_to_main_schedule_agent(
        self,
        context: RunContext[AgentContext],
    ):
        """Call this function ONLY after interactively discussing origin, root, and affixes in Chinese."""
        from agents.vocab.agents.cooccurrence import CooccurrenceAgent
        from agents.vocab.agents.synonym import SynonymAgent
        similar_words = await self.context.word.similar_words

        if similar_words and len(similar_words) > 0:
            agent = SynonymAgent(context=context.userdata)
            return agent, None
        else:
            agent = CooccurrenceAgent(context=context.userdata)
            return agent, None
