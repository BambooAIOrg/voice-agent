from livekit.agents import (
    RunContext,
)
from livekit.agents.llm import function_tool, ChatContext
from agents.vocab.context import AgentContext
from bamboo_shared.agent.instructions import TemplateVariables, get_instructions
from bamboo_shared.logger import get_logger
from livekit.agents import Agent as LivekitAgent

logger = get_logger(__name__)

class CoOccurrenceAgent(LivekitAgent):
    def __init__(self, context: AgentContext) -> None:
        self.template_variables = TemplateVariables(
            word=context.word,
            nickname=context.user_info.nick_name,
            user_english_level=context.get_formatted_english_level(),
            user_characteristics=context.user_characteristics
        )
        instructions = get_instructions(
            self.template_variables,
            "co_occurrence",
            voice_mode=True
        )
        super().__init__(
            instructions=instructions,
            chat_ctx=context.chat_context
        )

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
        from agents.vocab.agents.sentence_practice import SentencePracticeAgent
        logger.info("Handing off to SentencePracticeAgent after completing co-occurrence discussion.")
        context.userdata.chat_context = context.session._chat_ctx
        practice_agent = SentencePracticeAgent(context=context.userdata)
        return practice_agent, None
