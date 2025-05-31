from livekit.agents import (
    Agent,
    RunContext,
)
from livekit.agents.llm import function_tool
from logger import get_logger

logger = get_logger(__name__)

class SynonymAgent(Agent):
    def __init__(self, target_word: str) -> None:
        specific_task = (
            "Your specific task now is to discuss synonyms (同义词) interactively. "
            "Introduce *one* English synonym or *one* key difference at a time. Explain the nuance briefly in **Chinese**. "
            "After each point, ask the student a simple question in Chinese"
            "Keep turns short. Wait for the student's response. "
            "When the main synonyms/differences are covered, call 'start_cooccurrence'."
        )
        formatted_instructions = BASE_INSTRUCTION_TEMPLATE.format(
            target_word=target_word,
            specific_task=specific_task
        )
        super().__init__(instructions=formatted_instructions)
        self.target_word = target_word

    async def on_enter(self):
        await self.session.generate_reply(
            instructions=f"In Chinese, start discussing synonyms for '{self.target_word}'. Introduce just one aspect (e.g., one synonym or one difference). Explain briefly in Chinese. Ask a question."
        )

    @function_tool
    async def start_cooccurrence(
        self,
        context: RunContext[WordLearningData],
    ):
        """Call this function ONLY after interactively discussing the main synonyms and differences."""
        logger.info("Handing off to CooccurrenceAgent after completing synonym discussion.")
        context.userdata.synonyms_explored = True
        cooccurrence_agent = CooccurrenceAgent(target_word=context.userdata.target_word)
        return cooccurrence_agent, None

