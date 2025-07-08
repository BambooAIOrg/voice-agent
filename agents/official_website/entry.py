from datetime import datetime
from dotenv import load_dotenv
import pytz
from agents.official_website.agents.cooccurrence import CooccurrenceAgent
from agents.official_website.agents.word_creation_analysis import WordCreationAnalysisAgent
from bamboo_shared.enums.official_website import OfficialWebsitePhase
from agents.official_website.agents.synonym import SynonymAgent
from agents.official_website.context import AgentContext
from plugins.tokenizer.mixedLanguangeTokenizer import install_mixed_language_tokenize
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
from bamboo_shared.logger import get_logger


logger = get_logger(__name__)

# Import GreetingAgent from the agents module
# from agents.vocab.agents.greeting import GreetingAgent

@dataclass
class WordLearningData:
    target_word: str
    etymology_explored: bool = False
    synonyms_explored: bool = False
    cooccurrence_explored: bool = False
    practice_finished: bool = False



# Function to get the current job context (replace if needed)
# def get_job_context() -> JobContext:
#     # This function needs to be implemented or imported correctly
#     # based on how JobContext is managed in your setup.
#     # For now, it's a placeholder.
#     pass

async def official_website_entrypoint(ctx: JobContext, metadata: dict):
    """Entrypoint for official_website learning agents"""
    visitor_id = metadata.get("visitor_id", "")
    
    context = AgentContext(
        visitor_id=visitor_id,
    )
    await context.initialize_async_context()
    
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

    agent = None

    match context.phase:
        case OfficialWebsitePhase.WORD_CREATION_LOGIC:
            agent = WordCreationAnalysisAgent(context=context)
        case OfficialWebsitePhase.SYNONYM_DIFFERENTIATION:
            agent = SynonymAgent(context=context)
        case OfficialWebsitePhase.CO_OCCURRENCE:
            agent = CooccurrenceAgent(context=context)
        case _:
            raise ValueError(f"Invalid phase: {context.phase}")

    await session.start(
        agent=agent,
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

    # 获取北京时间
    beijing_tz = pytz.timezone('Asia/Shanghai')
    now = datetime.now(beijing_tz)

    last_communication_time = context.last_communication_time
    phase = context.phase
    current_word = context.current_word

    # 简洁中文说明
    phase_description = {
        "word_creation_logic": "单词的构词逻辑模块，帮助用户掌握前缀、词根和后缀的构成方式，从而更轻松理解和记忆单词。",
        "synonym_differentiation": "同义词区分模块，帮助用户辨析含义相近的单词之间的细微区别。",
        "co_occurrence": "共现词模块，展示单词在真实语境中常见的搭配和使用方式，增强语感和语言自然度。",
    }

    # 生成自然语言 instructions 提示词
    if last_communication_time:
        instructions = (
            f"用户上次交互时间为 {last_communication_time.isoformat()}，当前时间是 {now.isoformat()}。"
            f"目前用户正在进入的是：{phase_description[phase.value]}，正在学习的单词「{current_word}」。"
            f"请用1句温暖自然的语气欢迎用户回来，可以酌情融入当前时间，自然引导他们继续学习这个单词，避免正式或冗长表达。"
        )
    else:
        instructions = (
            f"这是用户今天第一次进入学习页面，当前时间是 {now.isoformat()}。"
            f"目前将体验的是 {phase_description[phase.value]}，要学习的单词是「{current_word}」。"
            f"请用1句自然轻快、亲切友好的语气欢迎用户，可以酌情融入当前时间，自然引导他们开始学习这个单词，避免正式或冗长表达。"
        )
    await session.generate_reply(instructions=instructions)