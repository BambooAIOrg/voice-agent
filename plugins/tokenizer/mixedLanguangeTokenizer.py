import re
import functools

from livekit.agents.tokenize import tokenizer, token_stream
from livekit.agents.tokenize import basic as original_basic
from livekit.agents.tokenize import _basic_hyphenator
import logging

logger = logging.getLogger("mixed-language-tokenizer")
# 保存原始函数引用
original_hyphenate_word = _basic_hyphenator.hyphenate_word
# 中英文混合句子分割模式
# 同时支持中文和英文标点符号
MIXED_SENTENCE_PATTERN = r'([^。！？.!?]+[。！？.!?]+)'

class MixedLanguageTokenizer(tokenizer.SentenceTokenizer):
    def __init__(
        self,
        *,
        min_sentence_len: int = 5,
        stream_context_len: int = 5,
        retain_format: bool = False,
    ) -> None:
        self._min_sentence_len = min_sentence_len
        self._stream_context_len = stream_context_len
        self._retain_format = retain_format

    def tokenize(self, text: str, *, language: str | None = None) -> list[str]:
        if not text:
            return []
        
        # 使用混合语言句子切分
        sentences = re.findall(MIXED_SENTENCE_PATTERN, text)
        
        # 处理未匹配的部分
        remaining = text
        for sent in sentences:
            remaining = remaining.replace(sent, "", 1)
        if remaining and self._retain_format:
            sentences.append(remaining)
            
        return [s for s in sentences if len(s) >= self._min_sentence_len]

    def stream(self, *, language: str | None = None) -> tokenizer.SentenceStream:
        return token_stream.BufferedSentenceStream(
            tokenizer=functools.partial(
                self._split_mixed_sentences,
                min_sentence_len=self._min_sentence_len,
                retain_format=self._retain_format,
            ),
            min_token_len=self._min_sentence_len,
            min_ctx_len=self._stream_context_len,
        )
    
    def _split_mixed_sentences(self, text, min_sentence_len=5, retain_format=False):
        if not text:
            return []
        
        result = []
        sentences = re.findall(MIXED_SENTENCE_PATTERN, text)
        
        # 标记每个句子的起始和结束位置
        position = 0
        for sent in sentences:
            start_pos = text.find(sent, position)
            end_pos = start_pos + len(sent)
            if len(sent) >= min_sentence_len:
                result.append((sent, start_pos, end_pos))
            position = end_pos
        
        # 处理未匹配的部分
        if retain_format and position < len(text):
            remaining = text[position:]
            if len(remaining) >= min_sentence_len:
                result.append((remaining, position, len(text)))
        
        return result

def mixed_hyphenate_word(word: str) -> list[str]:
    """处理中英文混合单词，将中文字符单独切分，英文使用原始音节切分"""
    if not word:
        return []
    
    result = []
    # 当前处理的子串类型：0=未定义, 1=中文, 2=英文
    current_type = 0
    current_segment = ""
    
    for char in word:
        is_chinese = bool(re.match(r'[\u4e00-\u9fff]', char))
        char_type = 1 if is_chinese else 2
        
        if current_type == 0:
            # 初始化
            current_type = char_type
            current_segment = char
        elif current_type == char_type:
            # 同类型字符，继续累积
            current_segment += char
        else:
            # 类型切换，处理当前段
            if current_type == 1:  # 中文
                result.extend(list(current_segment))
            else:  # 英文
                result.extend(original_hyphenate_word(current_segment))
            
            # 重置为新类型
            current_type = char_type
            current_segment = char
    
    # 处理最后一段
    if current_segment:
        if current_type == 1:  # 中文
            result.extend(list(current_segment))
        else:  # 英文
            result.extend(original_hyphenate_word(current_segment))
    
    return result

def mixed_split_words(
    text: str,
    *,
    ignore_punctuation: bool = True,
    split_character: bool = False,
) -> list[tuple[str, int, int]]:
    """按字符级别切分中文文本，英文按单词切分。

    兼容 LiveKit `split_words()` 的签名，接受 `split_character` 可选参数。
    目前实现对 `split_character` 无特殊处理，仅为接口兼容保留。
    """
    if not text:
        return []
    
    result = []
    i = 0
    
    while i < len(text):
        char = text[i]
        
        # 跳过标点和空格（如果需要）
        if ignore_punctuation and (char.isspace() or re.match(r'\p{P}', char, re.UNICODE)):
            i += 1
            continue
            
        # 处理英文单词
        if re.match(r'[a-zA-Z]', char):
            start = i
            while i < len(text) and re.match(r'[a-zA-Z]', text[i]):
                i += 1
            result.append((text[start:i], start, i))
        # 处理中文字符（单个字符）
        elif re.match(r'[\u4e00-\u9fff]', char):
            result.append((char, i, i+1))
            i += 1
        else:
            # 其他字符
            if not ignore_punctuation:
                result.append((char, i, i+1))
            i += 1
    
    return result

def install_mixed_language_tokenize():
    """安装中英文混合tokenize功能，替换LiveKit内部的分词功能"""
    # 替换基本函数
    from livekit.agents.tokenize import _basic_hyphenator
    from livekit.agents.tokenize import basic
    from livekit.agents.tokenize import _basic_word
    
    # 完全替换原始函数
    _basic_hyphenator.hyphenate_word = mixed_hyphenate_word
    _basic_word.split_words = mixed_split_words
    basic.hyphenate_word = mixed_hyphenate_word
    basic.split_words = mixed_split_words