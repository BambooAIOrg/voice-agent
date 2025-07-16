from bamboo_shared.agent.instructions import TemplateVariables, get_instructions
from livekit.agents import (
    RunContext,
)
from livekit.agents.llm import function_tool, ChatContext
from agents.vocab.context import AgentContext
from bamboo_shared.logger import get_logger
from livekit.agents import Agent as LivekitAgent
from bamboo_shared.enums.vocabulary import (
    VocabularyPhase,
    SentenceType
)
from typing import Annotated
from bamboo_shared.models import UserWrittenSentence
from bamboo_shared.repositories.user_written_sentence import UserWrittenSentenceRepository

logger = get_logger(__name__)

class MainScheduleAgent(LivekitAgent):
    def __init__(self, context: AgentContext) -> None:
        self.context = context
        instructions = self._get_current_instructions()
        
        super().__init__(
            instructions=instructions,
            chat_ctx=context.chat_context
        )

    def _get_current_instructions(self) -> str:
        """Get instructions for the current phase from context"""
        similar_words = self.context.word.similar_words
        if similar_words:
            similar_words = ", ".join(similar_words)
        else:
            similar_words = ""

        template_variables = TemplateVariables(
            word=self.context.word.word,
            nickname=self.context.user_info.nick_name,
            user_english_level=self.context.get_formatted_english_level(),
            user_characteristics=self.context.get_formatted_characteristics(),
            similar_words=similar_words
        )
        
        # Map phase to instruction key
        phase_mapping = {
            VocabularyPhase.WORD_CREATION_LOGIC: "word_creation_logic",
            VocabularyPhase.SYNONYM_DIFFERENTIATION: "synonym_differentiation", 
            VocabularyPhase.CO_OCCURRENCE: "co_occurrence",
            VocabularyPhase.QUESTION_ANSWER: "sentence_practice"
        }
        
        instruction_key = phase_mapping.get(self.context.phase, "word_creation_logic")
        return get_instructions(template_variables, instruction_key, voice_mode=True)

    async def on_enter(self):
        await self.session.generate_reply()

    @function_tool
    async def transfer_to_main_schedule_agent(
        self,
        context: RunContext[AgentContext],
    ):
        """Handoff to the Main Schedule Agent agent to handle the request."""
        current_phase = self.context.phase
        
        # 定义阶段转换逻辑
        if current_phase == VocabularyPhase.WORD_CREATION_LOGIC:
            # 检查是否有相似词，决定下一阶段
            similar_words = self.context.word.similar_words
            if similar_words and len(similar_words) > 0:
                self.context.phase = VocabularyPhase.SYNONYM_DIFFERENTIATION
            else:
                self.context.phase = VocabularyPhase.CO_OCCURRENCE
                
        elif current_phase == VocabularyPhase.SYNONYM_DIFFERENTIATION:
            self.context.phase = VocabularyPhase.CO_OCCURRENCE
            
        elif current_phase == VocabularyPhase.CO_OCCURRENCE:
            self.context.phase = VocabularyPhase.QUESTION_ANSWER
            
        elif current_phase == VocabularyPhase.QUESTION_ANSWER:
            # 完成当前单词，转到下一个单词
            from agents.vocab.agents.route_analysis import RouteAnalysisAgent
            logger.info("Current word completed, transferring to RouteAnalysisAgent for next word")
            context.userdata.chat_context = context.session._chat_ctx
            agent = RouteAnalysisAgent(context=context.userdata)
            return agent, None
        
        # 更新指令并继续当前代理
        await self.update_instructions(self._get_current_instructions())
        logger.info(f"Proceeded to phase: {self.context.phase.value}")
        
        return self, None

    @function_tool
    async def transfer_to_next_word_agent(
        self,
        context: RunContext[AgentContext],
    ):
        """Handoff to the Next Word Agent agent to handle the request."""
        from agents.vocab.agents.route_analysis import RouteAnalysisAgent
        logger.info("Current word completed, transferring to RouteAnalysisAgent for next word")
        context.userdata.chat_context = context.session._chat_ctx
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