from bamboo_shared.enums.vocabulary import VocabularyPhase
from dotenv import load_dotenv
from agents.vocab.context import AgentContext
from plugins.tokenizer.mixedLanguageTokenizer import install_mixed_language_tokenize
load_dotenv(dotenv_path=".env.local")
install_mixed_language_tokenize()

from dataclasses import dataclass

from livekit.agents import (
    AgentSession,
    JobContext,
    RoomInputOptions,
    RoomOutputOptions,
    metrics,
)
from livekit.agents.voice import MetricsCollectedEvent
from livekit.plugins import openai
from livekit.plugins import noise_cancellation
from plugins.aliyun.stt import AliSTT
from plugins.minimax.tts import TTS as MinimaxTTS
from agents.vocab.service.event_service import EventService
from agents.vocab.agents.greeting_agent import GreetingAgent
from bamboo_shared.logger import get_logger

logger = get_logger(__name__)

async def vocab_entrypoint(ctx: JobContext, metadata: dict):
    """Entrypoint for vocabulary learning agents"""
    word_id = metadata.get("word_id", 0)
    user_id = metadata.get("user_id", 0)
    chat_id = metadata.get("chat_id", None)
    
    # Initialize message service and context
    context = AgentContext(
        user_id=int(user_id),
        chat_id=chat_id,
        word_id=int(word_id),
    )
    # Initialize context with improved error handling
    try:
        await context.initialize_async_context()
    except Exception as e:
        logger.error(f"Failed to initialize agent context: {e}")
        ctx.shutdown()
        return
    
    session = AgentSession[AgentContext](
        vad=ctx.proc.userdata["vad"],
        llm=openai.LLM(model="gpt-4.1"),
        # stt=openai.STT(
        #     model="gpt-4o-transcribe",
        #     detect_language=True,
        #     prompt=f"The following audio is from a Chinese student who is learning English with AI tutor. The student is currently learning the word: {context.word.word}"
        # ),
        stt=AliSTT(),
        tts=MinimaxTTS(
            model="speech-02-turbo",
            voice_id="Chinese (Mandarin)_Cute_Spirit",
            sample_rate=32000,
            bitrate=128000,
            emotion="happy"
        ),
        # tts=cartesia.TTS(
        #     voice="7d6adbc0-3c4f-4213-9030-50878d391ccd",
        #     language="zh",
        #     speed='slowest',
        # ),
        userdata=context,
    )
    event_service = EventService(context, session)
    event_service.init_event_handlers()

    usage_collector = metrics.UsageCollector()

    @session.on("metrics_collected")
    def on_metrics_collected(ev: MetricsCollectedEvent):  # Callback function for metrics collection
        metrics.log_metrics(ev.metrics)
        usage_collector.collect(ev.metrics)


    async def log_usage():
        summary = usage_collector.get_summary()
        logger.info(f"Usage: {summary}")

    ctx.add_shutdown_callback(log_usage)

    await session.start(
        agent=GreetingAgent(context=context),
        room=ctx.room,
        room_input_options=RoomInputOptions(
            noise_cancellation=noise_cancellation.BVC(),
            audio_enabled=True,
        ),
        room_output_options=RoomOutputOptions(
            transcription_enabled=True,
            audio_enabled=True,
        ),
    )
