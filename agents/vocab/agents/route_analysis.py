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
        logger.info(f"RouteAnalysisAgent initialized for user_id: {context.user_id}, word_id: {context.word_id}")
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
        user_demonstrates_clear_mastery: bool,
        reason_for_mastery_status: str,
        user_accepts_word_creation_logic: bool = True,
    ):
        """Handoff to the Main Schedule Agent agent to handle the request.
        
        Args:
            user_demonstrates_clear_mastery: Whether the user demonstrates clear mastery of the word
            reason_for_mastery_status: A brief teacher comment explaining *why* `user_demonstrates_clear_mastery` is True or False
            user_accepts_word_creation_logic: Whether the user wants to learn about the word's creation logic and etymology. Defaults to True for users who didn't demonstrate mastery (no need to ask). Only set explicitly when user demonstrated mastery and was asked about their preference.
        """
        from agents.vocab.agents.main_schedule_agent import MainScheduleAgent
        logger.info(f"Handing off to MainScheduleAgent. Mastery: {user_demonstrates_clear_mastery}, Reason: {reason_for_mastery_status}, Accepts logic: {user_accepts_word_creation_logic}")
        context.userdata.chat_context = context.session._chat_ctx
        main_schedule_agent = MainScheduleAgent(context=context.userdata)
        return main_schedule_agent, None
    
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
