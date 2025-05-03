from collections import deque
import json
import logging
from dataclasses import dataclass, field
import os
from typing import Optional
import psutil
from dotenv import load_dotenv
load_dotenv(dotenv_path=".env.local")
from livekit import api
from livekit.agents import (
    Agent,
    AgentSession,
    ChatContext,
    JobContext,
    JobProcess,
    RoomInputOptions,
    RoomOutputOptions,
    RunContext,
    WorkerOptions,
    cli,
    metrics,
)
from livekit.agents.job import JobRequest
from livekit.agents.llm import function_tool
from livekit.agents.voice import MetricsCollectedEvent
from livekit.plugins import openai, silero
from livekit.plugins import noise_cancellation
# from plugins.aliyun.stt import AliSTT
from plugins.minimax.tts import TTS as MinimaxTTS

logger = logging.getLogger("multi-agent-word-learning")


# New Base Template with placeholders
BASE_INSTRUCTION_TEMPLATE = """
System context:
You are part of a multi-agent system, designed to make agent coordination and execution easy. 
Transfers between agents are handled seamlessly in the background; do not mention or draw attention to these transfers in your conversation with the user.

Role:
You are a friendly and patient English tutor specifically helping Chinese students learning the English word '{target_word}'. 
Use clear and simple **Chinese** for explanations and instructions, but use English for the target word, synonyms, example sentences, etc. 
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


class GreetingAgent(Agent):
    def __init__(self, target_word: str) -> None:
        # Define the specific task description for this agent
        specific_task = (
            "Your specific role now is to welcome the student warmly in **Chinese**. "
            "Introduce the English word you are teaching today (already mentioned in the intro). Keep the introduction very brief. "
            "Then, ask in Chinese if they are ready to start exploring the word's origins (词源). "
            "Once they confirm, call the 'start_etymology' function."
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

def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()


async def entrypoint(ctx: JobContext):
    await ctx.connect()

    target_word = "extraordinary"

    session = AgentSession[WordLearningData](
        vad=ctx.proc.userdata["vad"],
        llm=openai.LLM(model="gpt-4.1"),
        stt=openai.STT(model="gpt-4o-transcribe"),
        tts=MinimaxTTS(
            model="speech-02-hd",
            voice_id="Cantonese_CuteGirl",
            sample_rate=32000,
            bitrate=128000,
            emotion="happy"
        ),
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

    await session.start(
        # Pass target_word when creating the first agent
        agent=GreetingAgent(target_word=target_word),
        room=ctx.room,
        room_input_options=RoomInputOptions(
            noise_cancellation=noise_cancellation.BVC(),
        ),
        room_output_options=RoomOutputOptions(transcription_enabled=True),
    )


async def request_fnc(request: JobRequest):
    logger.info(f"Received request: {request.room.metadata}")
    logger.info(f"ENV: {os.getenv('ENV')}")
    metadata = json.loads(request.room.metadata)
    if metadata.get("env") == os.getenv("ENV"):
        logger.info(f"Accepting request: {metadata}")
        await request.accept(attributes=metadata)
    else:
        logger.info(f"Rejecting request: {metadata}")
        await request.reject()

def load_fnc(*args, window_size=120, interval=0.5):
    """
    custom load function, collect sliding average of one minute
    
    window_size=120: keep 120 samples, 0.5 second interval approximately one minute
    interval=0.5: sample interval 0.5 second
    """
    if not hasattr(load_fnc, "samples"):
        load_fnc.samples = deque(maxlen=window_size)
        load_fnc._initialized = False

    if not load_fnc._initialized:
        psutil.cpu_percent(interval=None)  # initialize, discard first sample
        load_fnc._initialized = True
        return 0.0

    value = psutil.cpu_percent(interval=interval) / 100.0
    load_fnc.samples.append(value)

    if len(load_fnc.samples) == 0:
        return 0.0
    
    load = sum(load_fnc.samples) / len(load_fnc.samples)
    
    # only print when load is high, reduce log volume
    if load > 0.5:
        logger.info(f"load: {load:.4f}, current: {value:.4f}, samples: {len(load_fnc.samples)}")
    
    return load

if __name__ == "__main__":
    cli.run_app(WorkerOptions(
        entrypoint_fnc=entrypoint,
        prewarm_fnc=prewarm,
        request_fnc=request_fnc,
        load_fnc=load_fnc
    ))
