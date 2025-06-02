from livekit.agents import (
    Agent,
    RunContext,
)
from livekit.agents.llm import function_tool
from agents.vocab.agents.etymology import EtymologyAgent
from agents.vocab.context import AgentContext
from bamboo_shared.agent.instructions import TemplateVariables, get_instructions
from bamboo_shared.logger import get_logger


logger = get_logger(__name__)


class GreetingAgent(Agent):
    def __init__(self, context: AgentContext) -> None:
            

        self.template_variables = TemplateVariables(
            word=context.word.word,
            nickname=context.user_info.nick_name,
            user_english_level=context.get_formatted_english_level(),
            user_characteristics=context.get_formatted_characteristics()
        )

        logger.info(f"template_variables: {self.template_variables}")
        instructions = get_instructions(
            self.template_variables,
            "warmup",
        )
        super().__init__(instructions=instructions)
        self.context = context

    async def on_enter(self):
        logger.info(f"on_enter: {self.context.word.word}")
        # Reply prompt can be simpler as core instructions are set
        await self.session.generate_reply(
            instructions=f"Welcome the student warmly. warm up the lesson."
        )

    @function_tool
    async def start_etymology(
        self,
        context: RunContext[AgentContext],
    ):
        """Call this function when the student confirms they are ready to start learning about etymology."""
        logger.info("Handing off to EtymologyAgent.")
        etymology_agent = EtymologyAgent(context=context.userdata)
        return etymology_agent, None
