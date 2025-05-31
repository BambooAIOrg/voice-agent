from bamboo_shared.agent.instructions import TemplateVariables, get_instructions
from livekit.agents import (
    Agent,
    RunContext,
)
from livekit.agents.llm import function_tool
from agents.vocab.entry import WordLearningData
from agents.vocab.context import AgentContext
from logger import get_logger

logger = get_logger(__name__)

class SentencePracticeAgent(Agent):
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
        )
        super().__init__(instructions=instructions)
        self.context = context

    async def on_enter(self):
        await self.session.generate_reply(
            instructions=f"In Chinese, start sentence practice for '{self.template_variables.word}'. Generate the first scenario (described in Chinese) and prompt the student for an English sentence using the word."
        )

    @function_tool
    async def finish_practice_session(self, context: RunContext[WordLearningData]):
        """Call this function ONLY when you decide the student has had enough practice."""
        logger.info("LLM decided to finish practice session.")
        context.userdata.practice_finished = True
        await self.session.generate_reply(
            instructions=f"Congratulate the student in Chinese on completing practice for '{self.template_variables.word}'. Give final encouraging words in Chinese. End the session.",
            allow_interruptions=False
        )
        return None
