"""
Conversation Agent - Example implementation for general conversation
"""
from livekit.agents import (
    Agent,
    AgentSession,
    JobContext,
    RunContext,
    RoomInputOptions,
    RoomOutputOptions,
    metrics,
)
from livekit.agents.voice import MetricsCollectedEvent
from livekit.plugins import openai, silero, noise_cancellation
from plugins.aliyun.stt import AliSTT
from plugins.minimax.tts import TTS as MinimaxTTS
from logger import get_logger

logger = get_logger(__name__)

class OnboardingAgent(Agent):
    def __init__(self, topic: str) -> None:
        instructions = f"""
        You are a friendly AI assistant engaging in natural conversation.
        {"Your conversation topic is: " + topic if topic else ""}
        Be helpful, engaging, and maintain a natural conversational flow.
        Respond in the same language as the user speaks.
        """
        super().__init__(instructions=instructions)
        self.topic = topic

    async def on_enter(self):
        greeting = "你好！我是你的AI助手。"
        if self.topic:
            greeting += f" 今天我们可以聊聊关于{self.topic}的话题。"
        greeting += " 有什么我可以帮助你的吗？"
        
        await self.session.generate_reply(
            instructions=greeting,
            allow_interruptions=False
        )

async def onboarding_entrypoint(ctx: JobContext, metadata: dict):
    """Entrypoint for conversation agents"""
    topic = metadata.get("topic", None)
    
    session = AgentSession(
        vad=ctx.proc.userdata["vad"],
        llm=openai.LLM(model="gpt-4.1-mini"),
        stt=AliSTT(),
        tts=MinimaxTTS(
            model="speech-02-turbo",
            voice_id="Cantonese_CuteGirl",
            sample_rate=32000,
            bitrate=128000,
            emotion="happy"
        ),
    )

    usage_collector = metrics.UsageCollector()

    @session.on("metrics_collected")
    def _on_metrics_collected(ev: MetricsCollectedEvent):
        metrics.log_metrics(ev.metrics)
        usage_collector.collect(ev.metrics)

    async def log_usage():
        summary = usage_collector.get_summary()
        logger.info(f"Conversation usage: {summary}")

    ctx.add_shutdown_callback(log_usage)

    logger.info(f"Conversation session started with topic: {topic}")
    await session.start(
        agent=OnboardingAgent(topic=topic),
        room=ctx.room,
        room_input_options=RoomInputOptions(
            noise_cancellation=noise_cancellation.BVC(),
        ),
        room_output_options=RoomOutputOptions(transcription_enabled=True),
    ) 