from livekit.agents import (
    RunContext,
)
from livekit.agents.llm import function_tool, ChatContext
from agents.vocab.context import AgentContext
from bamboo_shared.agent.instructions import TemplateVariables, get_instructions
from bamboo_shared.logger import get_logger
from livekit.agents import Agent as LivekitAgent

logger = get_logger(__name__)

class SynonymAgent(LivekitAgent):
    def __init__(self, context: AgentContext) -> None:
        self.template_variables = TemplateVariables(
            word=context.word,
            nickname=context.user_info.nick_name,
            user_english_level=context.user_info.english_level,
            user_characteristics=context.user_characteristics
        )
        instructions = get_instructions(
            self.template_variables,
            "synonym",
            voice_mode=True
        )
        super().__init__(
            instructions=instructions,
            chat_ctx=context.chat_context
        )
        self.context = context

    async def on_enter(self):
        logger.info(f"SynonymAgent on_enter: {self.template_variables}")
        await self.session.generate_reply(
            instructions=f"In Chinese, start discussing synonyms for '{self.template_variables.word}'. Introduce just one aspect (e.g., one synonym or one difference). Explain briefly in Chinese. Ask a question."
        )

    @function_tool
    async def start_cooccurrence(
        self,
        context: RunContext[AgentContext],
    ):
        """Call this function ONLY after interactively discussing the main synonyms and differences."""
        from agents.vocab.agents.co_occurrence import CoOccurrenceAgent
        logger.info("Handing off to CoOccurrenceAgent after completing synonym discussion.")
        co_occurrence_agent = CoOccurrenceAgent(context=context.userdata)
        return co_occurrence_agent, None

