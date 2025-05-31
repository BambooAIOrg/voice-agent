from livekit.agents import (
    Agent,
    RunContext,
)
from livekit.agents.llm import function_tool
from agents.vocab.agents.etymology import EtymologyAgent
from agents.vocab.context import AgentContext
from bamboo_shared.agent.instructions import TemplateVariables, get_instructions
from logger import get_logger

logger = get_logger(__name__)


class GreetingAgent(Agent):
    def __init__(self, context: AgentContext) -> None:
            
        self.template_variables = TemplateVariables(
            word=context.word,
            nickname=context.user_info.nickname,
            user_english_level=context.user_info.english_level,
            user_characteristics=context.user_characteristics
        )
        instructions = get_instructions(
            self.template_variables,
            "greeting",
        )
        super().__init__(instructions=instructions)
        self.context = context

    async def on_enter(self):
        # Reply prompt can be simpler as core instructions are set
        await self.session.generate_reply(
            instructions=f"Welcome the student warmly in Chinese. Briefly re-introduce the word '{self.template_variables.word}' and ask if they\'re ready for etymology (词源)."
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
