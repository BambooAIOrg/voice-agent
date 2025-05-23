from dotenv import load_dotenv
from plugins.tokenizer.mixedLanguangeTokenizer import install_mixed_language_tokenize
load_dotenv(dotenv_path=".env.local")
install_mixed_language_tokenize()

from dataclasses import dataclass

from livekit.agents import (
    Agent,
    AgentSession,
    JobContext,
    RoomInputOptions,
    RoomOutputOptions,
    RunContext,
    metrics,
)
from livekit.agents.llm import function_tool
from livekit.agents.voice import MetricsCollectedEvent
from livekit.plugins import openai
from livekit.plugins import noise_cancellation
from plugins.aliyun.stt import AliSTT
from plugins.minimax.tts import TTS as MinimaxTTS
from logger import get_logger

logger = get_logger(__name__)

# Import GreetingAgent from the agents module
from agents.vocab.agents.greeting import GreetingAgent

# New Base Template with placeholders
BASE_INSTRUCTION_TEMPLATE = """
System context:
You are part of a multi-agent system, designed to make agent coordination and execution easy. 
Transfers between agents are handled seamlessly in the background; do not mention or draw attention to these transfers in your conversation with the user.

Role:
You are a friendly and patient English tutor specifically helping students learning the English word '{target_word}'. 
Keep your responses very short and conversational. Ask questions frequently to ensure the student understands and stays engaged. 
Avoid long lectures. Break down information into small, easy-to-digest pieces. Be very encouraging. 

Your specific task:
{specific_task}
"""


@dataclass
class WordLearningData:
    target_word: str
    etymology_explored: bool = False
    synonyms_explored: bool = False
    cooccurrence_explored: bool = False
    practice_finished: bool = False



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

# Function to get the current job context (replace if needed)
# def get_job_context() -> JobContext:
#     # This function needs to be implemented or imported correctly
#     # based on how JobContext is managed in your setup.
#     # For now, it's a placeholder.
#     pass

async def vocab_entrypoint(ctx: JobContext, metadata: dict):
    """Entrypoint for vocabulary learning agents"""
    target_word = metadata.get("target_word", "extraordinary")  # Use word from metadata or default

    session = AgentSession[WordLearningData](
        vad=ctx.proc.userdata["vad"],
        llm=openai.LLM(model="gpt-4.1-mini"),
        # stt=openai.STT(
        #     model="gpt-4o-mini-transcribe",
        #     language="zh",
        #     prompt="The following audio is from a Chinese student who is learning English with AI tutor."
        # ),
        stt=AliSTT(),
        tts=MinimaxTTS(
            model="speech-02-turbo",
            voice_id="Cantonese_CuteGirl",
            sample_rate=32000,
            bitrate=128000,
            emotion="happy"
        ),
        # tts=cartesia.TTS(
        #     voice="7d6adbc0-3c4f-4213-9030-50878d391ccd",
        #     language="zh",
        #     speed='slowest',
        # ),
        userdata=WordLearningData(target_word=target_word),
    )

    usage_collector = metrics.UsageCollector()

    @session.on("metrics_collected")
    def _on_metrics_collected(ev: MetricsCollectedEvent):
        metrics.log_metrics(ev.metrics)
        usage_collector.collect(ev.metrics)

    async def log_usage():
        summary = usage_collector.get_summary()
        logger.info(f"Usage: {summary}")

    ctx.add_shutdown_callback(log_usage)

    logger.info(f"session started")
    await session.start(
        # Pass target_word when creating the first agent
        agent=GreetingAgent(target_word=target_word),
        room=ctx.room,
        room_input_options=RoomInputOptions(
            noise_cancellation=noise_cancellation.BVC(),
        ),
        room_output_options=RoomOutputOptions(transcription_enabled=True),
    )