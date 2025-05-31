
from livekit.agents import (
    Agent,
    RunContext,
)
from livekit.agents.llm import function_tool
from logger import get_logger

logger = get_logger(__name__)

class SentencePracticeAgent(Agent):
    def __init__(self, target_word: str) -> None:
        specific_task = (
            "Your specific role now is sentence practice. "
            "Dynamically generate practical, conversational scenarios described in **Chinese**. Include a simple, spoken-style Chinese phrase representing the core meaning. "
            f"Ask the student to express this meaning in English using '{target_word}'. "
            "Provide brief, encouraging feedback on their attempt. "
            "Continue presenting new scenarios. When you judge the student has had sufficient practice, call 'finish_practice_session'."
        )
        formatted_instructions = BASE_INSTRUCTION_TEMPLATE.format(
            target_word=target_word,
            specific_task=specific_task
        )
        super().__init__(instructions=formatted_instructions)
        self.target_word = target_word

    async def on_enter(self):
        await self.session.generate_reply(
            instructions=f"In Chinese, start sentence practice for '{self.target_word}'. Generate the first scenario (described in Chinese) and prompt the student for an English sentence using the word."
        )

    @function_tool
    async def finish_practice_session(self, context: RunContext[WordLearningData]):
        """Call this function ONLY when you decide the student has had enough practice."""
        logger.info("LLM decided to finish practice session.")
        context.userdata.practice_finished = True
        await self.session.generate_reply(
            instructions=f"Congratulate the student in Chinese on completing practice for '{self.target_word}'. Give final encouraging words in Chinese. End the session.",
            allow_interruptions=False
        )
        return None
