from livekit.agents import (
    RunContext,
)
from livekit.agents.llm import function_tool
from agents.vocab.context import AgentContext
from bamboo_shared.agent.instructions import TemplateVariables, get_instructions
from bamboo_shared.logger import get_logger
from livekit.agents import Agent as LivekitAgent

logger = get_logger(__name__)


class RouteAnalysisAgent(LivekitAgent):
    def __init__(self, context: AgentContext) -> None:
        self.template_variables = TemplateVariables(
            word=context.word.word,
            nickname=context.user_info.nick_name,
            user_english_level=context.get_formatted_english_level(),
            user_characteristics=context.get_formatted_characteristics()
        )

        logger.info(f"template_variables: {self.template_variables}")
        logger.info(f"context: {context}")
        instructions = get_instructions(
            self.template_variables,
            "analysis_route",
            voice_mode=True
        )
        super().__init__(
            instructions=instructions,
            chat_ctx=context.chat_context
        )

    @function_tool
    async def transfer_to_main_schedule_agent(
        self,
        context: RunContext[AgentContext],
    ):
        """Call this function when the student confirms they are ready to start learning about etymology."""
        from agents.vocab.agents.word_creation_analysis import WordCreationAnalysisAgent
        logger.info("Handing off to EtymologyAgent.")
        context.userdata.chat_context = context.session._chat_ctx
        etymology_agent = WordCreationAnalysisAgent(context=context.userdata)
        return etymology_agent, None
    
    @function_tool
    async def transfer_to_next_word_agent(
        self,
        context: RunContext[AgentContext],
    ):
        """Call this function when the student confirms they are ready to start learning about etymology."""
        logger.info("Handing off to EtymologyAgent.")
        context.userdata.chat_context = context.session._chat_ctx
        await context.userdata.go_next_word()
        agent = RouteAnalysisAgent(context=context.userdata)
        return agent, None
