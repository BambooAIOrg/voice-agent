from livekit.agents import (
    Agent,
    RunContext,
)
from livekit.agents.llm import function_tool
from agents.vocab.agents.word_creation_analysis import WordCreationAnalysisAgent
from agents.vocab.context import AgentContext
from bamboo_shared.agent.instructions import TemplateVariables, get_instructions
from bamboo_shared.logger import get_logger


logger = get_logger(__name__)


class RouteAnalysisAgent(Agent):
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
        )
        super().__init__(
            instructions=instructions,
            chat_ctx=context.chat_context
        )
        self.context = context

    @function_tool
    async def start_etymology(
        self,
        context: RunContext[AgentContext],
    ):
        """Call this function when the student confirms they are ready to start learning about etymology."""
        logger.info("Handing off to EtymologyAgent.")
        context.userdata.chat_context = context.session._chat_ctx
        etymology_agent = WordCreationAnalysisAgent(context=context.userdata)
        return etymology_agent, None
