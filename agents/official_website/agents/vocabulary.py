from agents.official_website.agents.scene import SceneAgent
from bamboo_shared.agent.official_website.instructions import TemplateVariables, get_instructions
from livekit.agents import (
    Agent,
    RunContext,
)
from livekit.agents.llm import function_tool, ChatContext
from agents.official_website.context import AgentContext
from bamboo_shared.logger import get_logger
from plugins.minimax.tts import TTS as MinimaxTTS

logger = get_logger(__name__)


# Placeholder for the next agent - will be implemented next
class VocabularyAgent(Agent):
    def __init__(self) -> None:
        super().__init__(
            instructions="You are a helpful assistant that can answer questions about the official website.",
            chat_ctx=None,
            tts=MinimaxTTS(
                model="speech-02-turbo",
                voice_id="Chinese (Mandarin)_Soft_Girl",
                sample_rate=32000,
                bitrate=128000,
                emotion="happy"
            )
        )
        # super().__init__(
        #     instructions="You are a helpful assistant that can answer questions about the official website.",
        #     chat_ctx=context.chat_context
        # )
        # self.context = context

    async def on_enter(self):
        await self.session.say(f"""
            Hi there! I'm Haley, 我可以帮你了解我们的智能记单词模块，回答关于词汇学习的各种问题。今天有什么可以帮您？
            """,
            allow_interruptions=True
        )

    @function_tool
    async def start_scene(
            self,
            context: RunContext[AgentContext],
    ):
        """Call this function ONLY after interactively discussing origin, root, and affixes in Chinese."""
        logger.info("Handing off to SynonymAgent after completing etymology discussion.")
        synonym_agent = SceneAgent()
        return synonym_agent, None
