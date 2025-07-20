from bamboo_shared.agent.official_website.instructions import TemplateVariables, get_instructions
from livekit.agents import (
    Agent,
    RunContext,
)
from livekit.agents.llm import function_tool, ChatContext
from bamboo_shared.logger import get_logger
from livekit.plugins import cartesia
from plugins.minimax.tts import TTS as MinimaxTTS

logger = get_logger(__name__)

instructions = """
## Core Information
**Agent Name**: Doug
**Context**: Official Website Environment

## Role & Goal
你是Doug，BambooAI Chat模块的专家，你要向访客展示 BambooAI Chat 模块的双重价值，Chat模块既是一个价值20美金/月的顶级AI助手（接入了OpenAI，Grok的最新模型)，同时也是英语学习生态的智能大脑。

**重要提醒**：这是语音对话，要：
- 根据用户的具体问题和兴趣点针对性回应
- 避免一次性输出大量信息
- 避免任何格式化的内容，如：**、#、-、*、等，所有的强调，转折，过渡都必须来自语言本身而非格式化内容
- 保持对话节奏，让用户有参与感
- 循序渐进地展示产品优势
- 根据用户反馈调整介绍重点

## 核心产品优势
1. 独家AI模型接入优势
技术门槛突破：翻墙+国外银行卡的双重障碍
模型优势：OpenAI GPT系列 + Grok的独特价值
单独价值：即使不考虑英语学习，仅凭顶级AI接入就有巨大价值
无障碍体验：一键直达，无需任何额外操作

2. 智能数据反哺系统
词汇偏好识别：为AI记单词提供个性化推荐
表达能力评估：为场景对话调整难度
写作风格分析：为写作模块提供针对性训练
学习进度跟踪：优化整体学习路径

3. 数据价值的四个特点
真实性：反映用户真实语言习惯
丰富性：大量对话数据提供全面画像
动态性：持续更新确保方案精准
个性化：形成专属学习档案
"""

# Placeholder for the next agent - will be implemented next
class ChatAgent(Agent):
    def __init__(self, chat_ctx: ChatContext) -> None:
        super().__init__(
            instructions=instructions,
            chat_ctx=chat_ctx,
            tts=MinimaxTTS(
                model="speech-02-turbo",
                voice_id="Chinese (Mandarin)_Reliable_Executive",
                sample_rate=32000,
                bitrate=128000,
                emotion="happy"
            )
        )
        # self.context = context

    async def on_enter(self):
        logger.info(f"chat agent enter")
        await self.session.say(
            text="Hello, I'm Doug, 我可以帮你了解我们的Chat模块，回答关于Chat对话的各种问题。今天有什么可以帮您？",
            allow_interruptions=True
        )

    # @function_tool
    # async def start_synonyms(
    #         self,
    #         context: RunContext[AgentContext],
    # ):
    #     """Call this function ONLY after interactively discussing origin, root, and affixes in Chinese."""
    #     logger.info("Handing off to SynonymAgent after completing etymology discussion.")
    #     synonym_agent = SynonymAgent(context=context.userdata, chat_ctx=context.session._chat_ctx)
    #     return synonym_agent, None
