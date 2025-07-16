
from agents.vocab.context import Context


CORE_INFORMATION_TEMPLATE = """
User Information:
{user_information}

Target Word: {curr_word}
"""

USER_INFORMATION_TEMPLATE = """
The student's nickname is {nickname}.
The student's native language is Chinese.
The student's English proficiency CEFRlevel is {user_english_level}.
The student's characteristics are:
    - {user_characteristics}
"""

def format_core_information(context: Context) -> str:
    """Format user information that apply to all vocabulary teaching agents.
    
    Args:
        context: The teaching context with user and word information
        
    Returns:
        Formatted common instructions
    """
    user_info_str = USER_INFORMATION_TEMPLATE.format(
        target_word=context.word.word,
        nickname=context.user_info.nick_name,
        user_english_level=context.get_formatted_english_level(),
        user_characteristics=context.get_formatted_characteristics()
    ) 
    return CORE_INFORMATION_TEMPLATE.format(
        user_information=user_info_str,
        curr_word=context.word.word
    )
