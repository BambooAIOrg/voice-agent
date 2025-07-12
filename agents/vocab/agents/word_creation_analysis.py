from bamboo_shared.agent.instructions import TemplateVariables, get_instructions
from livekit.agents import (
    Agent,
    RunContext,
)
from livekit.agents.llm import function_tool, ChatContext

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
            voice_mode=True
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

    async def llm_node(self, chat_ctx: ChatContext, tools, model_settings):
        logger.info(f"llm_node: {chat_ctx.to_dict()}")
        # 调用父类的默认实现
        return Agent.default.llm_node(self, chat_ctx, tools, model_settings)
    
    @function_tool
    async def transfer_to_main_schedule_agent(
        self,
        context: RunContext[AgentContext],
    ):
        """Call this function ONLY after interactively discussing origin, root, and affixes in Chinese."""
        from agents.vocab.agents.co_occurrence import CoOccurrenceAgent
        from agents.vocab.agents.synonym import SynonymAgent
        similar_words = self.context.word.similar_words

        logger.info(f"similar_words: {similar_words}")
        logger.info(f"chat ctx: {context.userdata.chat_context}")
        if similar_words and len(similar_words) > 0:
            agent = SynonymAgent(context=context.userdata)
            return agent, None
        else:
            agent = CoOccurrenceAgent(context=context.userdata)
            return agent, None
