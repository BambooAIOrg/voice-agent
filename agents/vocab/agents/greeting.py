from livekit.agents import (
    Agent,
    RunContext,
)
from livekit.agents.llm import function_tool
from logger import get_logger

logger = get_logger(__name__)

# These will be imported when needed to avoid circular imports
BASE_INSTRUCTION_TEMPLATE = None
WordLearningData = None
EtymologyAgent = None

def setup_imports():
    """Call this to set up the imports after the module is loaded"""
    global BASE_INSTRUCTION_TEMPLATE, WordLearningData, EtymologyAgent
    from agents.vocab.entry import BASE_INSTRUCTION_TEMPLATE as base_template
    from agents.vocab.entry import WordLearningData as data_class
    from agents.vocab.entry import EtymologyAgent as etymology_class
    BASE_INSTRUCTION_TEMPLATE = base_template
    WordLearningData = data_class
    EtymologyAgent = etymology_class

class GreetingAgent(Agent):
    def __init__(self, target_word: str) -> None:
        # Ensure imports are set up
        if BASE_INSTRUCTION_TEMPLATE is None:
            setup_imports()
            
        # Define the specific task description for this agent
        specific_task = (
            "Your specific role now is to welcome the student warmly. "
            "Introduce the English word you are teaching today (already mentioned in the intro). Keep the introduction very brief. "
            "Then, ask if they are ready to start exploring the word's origins. "
        )
        # Format the BASE template with the target word and this agent's specific task
        formatted_instructions = BASE_INSTRUCTION_TEMPLATE.format(
            target_word=target_word,
            specific_task=specific_task
        )
        super().__init__(instructions=formatted_instructions)
        self.target_word = target_word

    async def on_enter(self):
        # Reply prompt can be simpler as core instructions are set
        await self.session.generate_reply(
            instructions=f"Welcome the student warmly in Chinese. Briefly re-introduce the word '{self.target_word}' and ask if they\'re ready for etymology (词源)."
        )

    @function_tool
    async def start_etymology(
        self,
        context: RunContext[WordLearningData],
    ):
        """Call this function when the student confirms they are ready to start learning about etymology."""
        logger.info("Handing off to EtymologyAgent.")
        etymology_agent = EtymologyAgent(target_word=context.userdata.target_word)
        return etymology_agent, None
