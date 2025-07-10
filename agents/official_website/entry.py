from datetime import datetime
from dotenv import load_dotenv
import pytz
import json
import asyncio
from livekit.rtc import DataPacket
from bamboo_shared.enums.official_website import OfficialWebsitePhase
from agents.official_website.context import AgentContext
from plugins.tokenizer.mixedLanguangeTokenizer import install_mixed_language_tokenize
from agents.official_website.agents.vocabulary import VocabularyAgent
from agents.official_website.agents.scene import SceneAgent
from agents.official_website.agents.writing import WritingAgent
from agents.official_website.agents.chat import ChatAgent

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

    async def switch_agent(phase: OfficialWebsitePhase):
        # 更新阶段
        await context.update_phase(phase)




        # 发送确认消息
        asyncio.create_task(
            ctx.room.local_participant.publish_data(
                json.dumps({"type": "agent_switched", "phase": phase}).encode("utf-8"),
                reliable=True,
                topic="agent_control"
            )
        )
        logger.info(f"Agent 切换成功: {phase}")


    # 监听前端消息
    @ctx.room.on("data_received")
    def _on_data_received(payload: DataPacket):
        try:
            data = json.loads(payload.data.decode("utf-8"))
            if data.get("type") == "switch_agent":
                phase = data.get("phase")
                # 异步调用 switch_agent（未实现，需补充）
                asyncio.create_task(switch_agent(phase))
        except Exception as e:
            logger.error(f"处理消息失败: {e}")
            asyncio.create_task(
                ctx.room.local_participant.publish_data(
                    json.dumps({"type": "agent_switch_failed", "phase": "", "error": str(e)}).encode(
                        "utf-8"),
                    reliable=True,
                    topic="agent_control"
                )
            )


    agent = None
    match context.phase:
        case OfficialWebsitePhase.VOCABULARY:
            agent = VocabularyAgent(context=context)
        case OfficialWebsitePhase.SCENE:
            agent = SceneAgent(context=context)
        case OfficialWebsitePhase.WRITING:
            agent = WritingAgent(context=context)
        case OfficialWebsitePhase.CHAT:
            agent = ChatAgent(context=context)
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
        "vocabulary": "",
        "scene": "",
        "writing": "",
        "chat": "",
    }

    # 生成自然语言 instructions 提示词
    if last_communication_time:
        instructions = (
            f"用户上次交互时间为 {last_communication_time.isoformat()}，当前时间是 {now.isoformat()}。"
            f"目前用户正在介绍的产品功能模块的是：{phase_description[phase.value]}。"
            f"请用1句温暖自然的语气欢迎用户回来，可以酌情融入当前时间，继续介绍这个功能模块，避免正式或冗长表达。"
        )
    else:
        instructions = (
            f"这是用户今天第一次进入产品介绍页面，当前时间是 {now.isoformat()}。"
            f"目前将介绍的产品功能模块是 {phase_description[phase.value]}。"
            f"请用1句自然轻快、亲切友好的语气欢迎用户，可以酌情融入当前时间，介绍这个功能模块，避免正式或冗长表达。"
        )
    await session.generate_reply(instructions=instructions)