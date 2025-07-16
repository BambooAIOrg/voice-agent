from livekit.agents import (
    RunContext,
)
from livekit.agents.llm import function_tool
from agents.vocab.context import AgentContext
from bamboo_shared.agent.instructions import TemplateVariables, get_instructions
from bamboo_shared.logger import get_logger
from livekit.agents import Agent as LivekitAgent
from bamboo_shared.models import UserWrittenSentence
from bamboo_shared.repositories.user_written_sentence import UserWrittenSentenceRepository
from bamboo_shared.enums.vocabulary import SentenceType

logger = get_logger(__name__)


class RouteAnalysisAgent(LivekitAgent):
    def __init__(self, context: AgentContext) -> None:
        self.context = context
        self.template_variables = TemplateVariables(
            word=context.word.word,
            nickname=context.user_info.nick_name,
            user_english_level=context.get_formatted_english_level(),
            user_characteristics=context.get_formatted_characteristics()
        )

        instructions = get_instructions(
            self.template_variables,
            "analysis_route",
            voice_mode=True
        )
        logger.info(f"instructions: \n{instructions}")
        super().__init__(
            instructions=instructions,
            chat_ctx=context.chat_context
        )
    
    async def on_enter(self):
        await self.session.generate_reply(allow_interruptions=False)

    @function_tool
    async def transfer_to_main_schedule_agent(
        self,
        context: RunContext[AgentContext],
        user_demonstrates_clear_mastery: bool,
        reason_for_mastery_status: str,
        user_accepts_word_creation_logic: bool = True,
    ):
        """Handoff to the Main Schedule Agent agent to handle the request.
        
        Args:
            user_demonstrates_clear_mastery: Whether the user demonstrates clear mastery of the word
            reason_for_mastery_status: A brief teacher comment explaining *why* `user_demonstrates_clear_mastery` is True or False
            user_accepts_word_creation_logic: Whether the user wants to learn about the word's creation logic and etymology. Defaults to True for users who didn't demonstrate mastery (no need to ask). Only set explicitly when user demonstrated mastery and was asked about their preference.
        """
        from agents.vocab.agents.main_schedule_agent import MainScheduleAgent
        logger.info(f"Handing off to MainScheduleAgent. Mastery: {user_demonstrates_clear_mastery}, Reason: {reason_for_mastery_status}, Accepts logic: {user_accepts_word_creation_logic}")
        context.userdata.chat_context = context.session._chat_ctx
        main_schedule_agent = MainScheduleAgent(context=context.userdata)
        return main_schedule_agent, None
    
    @function_tool
    async def transfer_to_next_word_agent(
        self,
        context: RunContext[AgentContext],
    ):
        """Call this function when the student confirms they are ready to start learning about etymology."""
        logger.info("Handing off to EtymologyAgent.")
        context.userdata.chat_context = context.session._chat_ctx
        await context.userdata.go_next_word()
        agent = RouteAnalysisAgent(context=context.userdata)
        return agent, None

    @function_tool
    async def save_sentence_evaluation(
        self,
        sentence: str,
        grammar_accuracy: int,
        vocabulary_proficiency: int,
        sentence_complexity: int,
        sentence_type: SentenceType,
        explanation: str,
        corrected_sentence: str,
        native_sentence: str,
        user_sentence_mean_cn: str
    ):
        """
        Save the sentence evaluation result
        
        Args:
            sentence: 用户提供的原始句子
            grammar_accuracy: 语法准确性评分(0-10分)
            vocabulary_proficiency: 词汇运用评分(0-10分)
            sentence_complexity: 句子复杂度评分(0-10分)
            sentence_type: 句子类型(1-简单句, 2-复合句, 3-复杂句)
            explanation: 评分解释和详细反馈
            corrected_sentence: 语法或表达的修改建议
            native_sentence: 更地道、自然的表达方式
            user_sentence_mean_cn: 用户句子的中文含义
        
        Returns:
            操作结果确认信息
        """
        try:
            sentence_repo = UserWrittenSentenceRepository(self.context.user_id)
            await sentence_repo.add(UserWrittenSentence(
                user_id=self.context.user_id,
                chat_id=self.context.chat_id,
                word_id=self.context.word.id,
                user_sentence=sentence,
                user_sentence_mean_cn=user_sentence_mean_cn,
                grammar_accuracy=grammar_accuracy,
                vocabulary_proficiency=vocabulary_proficiency,
                sentence_complexity=sentence_complexity,
                sentence_type=sentence_type,
                gpt_analyze=explanation,
                gpt_corrected_sentence=corrected_sentence,
                gpt_native_sentence=native_sentence,
            ))
            return "evaluation saved"
        except Exception as e:
            logger.error(f"Error saving sentence evaluation: {e}")
            return "evaluation failed"
