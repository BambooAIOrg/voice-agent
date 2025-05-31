from livekit.agents import (
    Agent,
    RunContext,
)
from livekit.agents.llm import function_tool
from logger import get_logger

logger = get_logger(__name__)

# Placeholder for the next agent - will be implemented next
class EtymologyAgent(Agent):
    def __init__(self, target_word: str) -> None:
        specific_task = (
            "Your specific task now is to guide the student in **Chinese** to explore the *original physical meaning* of the English word '{target_word}'. "
            "Instead of just listing facts, explore this meaning interactively. "
            "This exploration will naturally involve discussing its origin, root, relevant affixes, and perhaps related words. "
            "Introduce one aspect (e.g., the root's meaning, a related historical context) at a time. "
            "Keep explanations very short and ask simple questions in Chinese after each small piece of information to ensure understanding"
            "Wait for the student's response before proceeding. "
            "After sufficiently exploring the core original meaning, call 'start_synonyms'."
        )
        formatted_instructions = BASE_INSTRUCTION_TEMPLATE.format(
            target_word=target_word,
            specific_task=specific_task
        )
        super().__init__(instructions=formatted_instructions)
        self.target_word = target_word

    async def on_enter(self):
        logger.info(f"etymology agent enter")
        await self.session.generate_reply(
            instructions=f"In Chinese, start explaining the origin (来源) of '{self.target_word}'. Keep it brief. Ask if understood."
        )

    @function_tool
    async def start_synonyms(
        self,
        context: RunContext[WordLearningData],
    ):
        """Call this function ONLY after interactively discussing origin, root, and affixes in Chinese."""
        logger.info("Handing off to SynonymAgent after completing etymology discussion.")
        context.userdata.etymology_explored = True
        synonym_agent = SynonymAgent(target_word=context.userdata.target_word)
        return synonym_agent, None
