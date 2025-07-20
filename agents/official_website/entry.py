from dotenv import load_dotenv
import json
import asyncio
from livekit.rtc import DataPacket
from bamboo_shared.enums.official_website import OfficialWebsitePhase
from agents.official_website.context import AgentContext
from plugins.tokenizer.mixedLanguageTokenizer import install_mixed_language_tokenize
from agents.official_website.agents.chat import ChatAgent
from agents.official_website.agents.scene import SceneAgent
from agents.official_website.agents.vocabulary import VocabularyAgent
from agents.official_website.agents.writing import WritingAgent

import random

load_dotenv(dotenv_path=".env.local")
install_mixed_language_tokenize()

from dataclasses import dataclass

from livekit.agents import (
    AgentSession,
    JobContext,
    RoomInputOptions,
    RoomOutputOptions,
    metrics,
    voice,
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
    context = AgentContext(visitor_id=visitor_id)
    await context.initialize_async_context()

    session = AgentSession[AgentContext](
        vad=ctx.proc.userdata["vad"],
        llm=openai.LLM(model="gpt-4.1"),
        stt=AliSTT(),
        tts=MinimaxTTS(
            model="speech-02-turbo",
            voice_id="Chinese (Mandarin)_Gentle_Senior",
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

    def get_agent_by_phase(phase: OfficialWebsitePhase):
        """根据阶段创建对应的 Agent"""
        match phase:
            case OfficialWebsitePhase.VOCABULARY:
                return VocabularyAgent()
            case OfficialWebsitePhase.SCENE:
                return SceneAgent()
            case OfficialWebsitePhase.WRITING:
                return WritingAgent()
            case OfficialWebsitePhase.CHAT:
                return ChatAgent()
            case _:
                raise ValueError(f"Invalid phase: {phase}")

    async def switch_agent(phase: OfficialWebsitePhase):
        asyncio.create_task(
            ctx.room.local_participant.publish_data(
                payload=json.dumps({"type": "agent_switched", "phase": phase.value}).encode("utf-8"),
                reliable=True,
                topic="agent_control"
            )
        )
        session.interrupt()
        phrases = ["上!", "该你了!", "Over to you!"]
        selected_phrase = random.choice(phrases)
        await session.say(text=f"Sure，{context.get_character_name(phase.value)}, {selected_phrase}")
        context.update_phase(phase)
        agent = get_agent_by_phase(context.phase)
        
        session.update_agent(agent)

    # 监听前端消息
    @ctx.room.on("data_received")
    def _on_data_received(payload: DataPacket):
        try:
            data = json.loads(payload.data.decode("utf-8"))
            if data.get("type") == "switch_agent":
                phase_str = data.get("phase")
                try:
                    phase = OfficialWebsitePhase(phase_str)
                except ValueError:
                    raise ValueError(f"Unknown phase string: {phase_str}")
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

    await session.start(
        agent=VocabularyAgent(),
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
