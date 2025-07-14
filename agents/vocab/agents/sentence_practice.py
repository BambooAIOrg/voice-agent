from bamboo_shared.agent.instructions import TemplateVariables, get_instructions
from livekit.agents import (
    RunContext,
)
from livekit.agents.llm import function_tool
from agents.vocab.context import AgentContext
from bamboo_shared.logger import get_logger
from livekit.agents import Agent as LivekitAgent

logger = get_logger(__name__)

class SentencePracticeAgent(LivekitAgent):
    def __init__(self, context: AgentContext) -> None:
        self.template_variables = TemplateVariables(
            word=context.word,
            nickname=context.user_info.nickname,
            user_english_level=context.user_info.english_level,
            user_characteristics=context.user_characteristics
        )
        instructions = get_instructions(
            self.template_variables,
            "sentence_practice",
            voice_mode=True
        )
        super().__init__(
            instructions=instructions,
            chat_ctx=context.chat_context
        )

    async def on_enter(self):
        await self.session.generate_reply(
            instructions=f"In Chinese, start sentence practice for '{self.template_variables.word}'. Generate the first scenario (described in Chinese) and prompt the student for an English sentence using the word."
        )

    @function_tool
    async def transfer_to_next_word_agent(
        self,
        context: RunContext[AgentContext],
    ):
        """Call this function when the student confirms they are ready to start learning about etymology."""
        from agents.vocab.agents.route_analysis import RouteAnalysisAgent
        logger.info("Handing off to EtymologyAgent.")
        context.userdata.chat_context = context.session._chat_ctx
        agent = RouteAnalysisAgent(context=context.userdata)
        return agent, None
