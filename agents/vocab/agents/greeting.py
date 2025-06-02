from livekit.agents import (
    Agent,
    RunContext,
)
from livekit.agents.llm import function_tool
from agents.vocab.agents.etymology import EtymologyAgent
from agents.vocab.context import AgentContext
from bamboo_shared.agent.instructions import TemplateVariables, get_instructions
from bamboo_shared.logger import get_logger
import random
from datetime import datetime
import pytz


logger = get_logger(__name__)


class GreetingAgent(Agent):
    def __init__(self, context: AgentContext) -> None:
        self.template_variables = TemplateVariables(
            word=context.word.word,
            nickname=context.user_info.nick_name,
            user_english_level=context.get_formatted_english_level(),
            user_characteristics=context.get_formatted_characteristics()
        )

        logger.info(f"template_variables: {self.template_variables}")
        logger.info(f"context: {context}")
        instructions = get_instructions(
            self.template_variables,
            "warmup",
        )
        super().__init__(instructions=instructions)
        self.context = context

    async def on_enter(self):
        nickname = self.context.user_info.nick_name

        # 获取北京时间
        beijing_tz = pytz.timezone('Asia/Shanghai')
        now = datetime.now(beijing_tz)
        hour = now.hour

        # 早上招呼
        morning_greetings = [
            f"Morning, {nickname}! Did you have breakfast yet?",
            f"Good morning, {nickname}! Hope you slept well.",
            f"Hey {nickname}, bright and early today, huh?",
            f"Hi {nickname}, ready to kick off the day?",
            f"Rise and shine, {nickname}! Let's make today awesome!",
        ]
        # 晚上招呼
        evening_greetings = [
            f"Good evening, {nickname}! How was your day?",
            f"Evening, {nickname}! Studying at night—impressive!",
            f"Hi {nickname}, winding down with some English?",
            f"Nice to see you this evening, {nickname}!",
            f"Hi {nickname}, hope you had a good one!",
        ]
        # 深夜招呼
        night_greetings = [
            f"Hey {nickname}, burning the midnight oil?",
            f"Still up, {nickname}? Night owl mode—respect!",
            f"Hi {nickname}, learning English at this hour? That's dedication!",
            f"Hi {nickname}, can't sleep or just love English?",
            f"Hey {nickname}, it's pretty late—let's learn something cool!",
        ]
        # 通用招呼
        general_greetings = [
            f"Hey {nickname}, great to see you!",
            f"Yo {nickname}! You bring the energy, I'll bring the words!",
            f"Hiya {nickname}, how's going today?",
            f"Hey there, {nickname}! Ready for some English?",
            f"Hi {nickname}, how are you today?",
            f"Hi {nickname}, great to have you here!",
        ]

        # 判断时间段
        if 5 <= hour < 12:
            greetings = morning_greetings + general_greetings
        elif 18 <= hour < 23:
            greetings = evening_greetings + general_greetings
        elif 23 <= hour or hour < 5:
            greetings = night_greetings + general_greetings
        else:
            greetings = general_greetings

        greeting = random.choice(greetings)
        await self.session.say(greeting)

    @function_tool
    async def start_etymology(
        self,
        context: RunContext[AgentContext],
    ):
        """Call this function when the student confirms they are ready to start learning about etymology."""
        logger.info("Handing off to EtymologyAgent.")
        etymology_agent = EtymologyAgent(context=context.userdata)
        return etymology_agent, None
