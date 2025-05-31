from livekit.agents import (
    Agent,
    RunContext,
)
from livekit.agents.llm import function_tool
from logger import get_logger

logger = get_logger(__name__)

class CooccurrenceAgent(Agent):
    def __init__(self, target_word: str) -> None:
        specific_task = (
            "Your specific task now is to discuss co-occurring words interactively. "
            "Introduce *one type* of co-occurring English word (e.g., typical adjectives, common verbs) or *one English example phrase* at a time. Explain briefly in **Chinese**. "
            "After each point, ask a simple question in Chinese"
            "Keep turns short. Wait for the student's response. "
            "When main co-occurrence patterns are covered, call 'start_practice'."
        )
        formatted_instructions = BASE_INSTRUCTION_TEMPLATE.format(
            target_word=target_word,
            specific_task=specific_task
        )
        super().__init__(instructions=formatted_instructions)
        self.target_word = target_word

    async def on_enter(self):
        await self.session.generate_reply(
            instructions=f"In Chinese, start discussing co-occurring words for '{self.target_word}'. Introduce just one type or example. Explain briefly in Chinese. Ask a question."
        )

    @function_tool
    async def start_practice(
        self,
        context: RunContext[WordLearningData],
    ):
        """Call this function ONLY after interactively discussing the main co-occurrence patterns."""
        logger.info("Handing off to SentencePracticeAgent after completing co-occurrence discussion.")
        context.userdata.cooccurrence_explored = True
        practice_agent = SentencePracticeAgent(target_word=context.userdata.target_word)
        return practice_agent, None
