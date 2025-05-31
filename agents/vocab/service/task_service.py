from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy import and_, func, asc
from bamboo_shared.models.Chat import ChatReference, ChatMessage
from bamboo_shared.enums.vocabulary import VocabularyPhase
from bamboo_shared.enums.chat import ReferenceType
from bamboo_shared.models.Vocabulary import (
    Vocabulary,
    UserLearningTask,
    BookInfo,
    VocabularyBook,
)
from sqlalchemy.sql import text
from logger import get_logger
from bamboo_shared.database import async_session_maker
from sqlalchemy import select
import json

from bamboo_shared.utils import time_now

logger = get_logger(__name__)


@dataclass
class WordTask:
    """单词学习任务"""
    word_id: int
    word: str
    chat_id: Optional[str] = None
    phase: Optional[str] = VocabularyPhase.ROOT_AFFIX_ANALYSIS.value
    message_list: list[ChatMessage] = field(default_factory=list)


class TaskService:
    async def get_book_info(self, user_id: int):
        sql = """
            SELECT 
                JSON_UNQUOTE(JSON_EXTRACT(us.study_config, '$.bookId')) as book_id,
                bi.book_type as selected_book_type,
                (
                    SELECT filter_data.filter
                    FROM JSON_TABLE(
                        us.filter_config,
                        '$[*]' COLUMNS(
                            filter_id VARCHAR(255) PATH '$.id',
                            filter VARCHAR(255) PATH '$.filter'
                        )
                    ) as filter_data
                    WHERE filter_id = bi.book_type
                    LIMIT 1
                ) as book_filter_type,
                CAST(JSON_UNQUOTE(JSON_EXTRACT(us.study_config, '$.dailyTarget.value')) AS SIGNED) as daily_target
            FROM user_settings us
            LEFT JOIN book_info bi ON bi.id = CAST(JSON_UNQUOTE(JSON_EXTRACT(us.study_config, '$.bookId')) AS SIGNED)
            WHERE us.user_id = :user_id
        """

        async with async_session_maker() as session:
            result = await session.execute(text(sql), {"user_id": user_id})
            row = result.first()

            if not row:
                raise ValueError("User settings not found")

            return {
                "bookId": row.book_id,
                "selected_book_type": row.selected_book_type,
                "book_filter_type": None if row.book_filter_type == "null" else row.book_filter_type,
                "daily_target": row.daily_target
            }

    async def get_word_chats(self, user_id: int):
        book_info = await self.get_book_info(user_id)
        filter_type = book_info["book_filter_type"]

        # 基础 SQL
        base_sql = """
            SELECT 
                c.chat_id,
                c.message_list,
                w.word_id
            FROM user_learning_task t
            JOIN JSON_TABLE(
                t.word_list,
                '$[*]' COLUMNS(
                    word_id INT PATH '$.id',
                    position FOR ORDINALITY
                )
            ) w
            LEFT JOIN chat c ON 
                c.word_id = w.word_id
                AND c.type = 'vocabulary'
                AND c.user_id = :user_id
                AND c.deleted = false
            WHERE t.user_id = :user_id
            AND t.date = CURRENT_DATE
            AND t.book_id = :book_id
        """

        params = {
            "user_id": user_id,
            "book_id": book_info["bookId"]
        }

        if filter_type is None or filter_type == "null":
            sql = base_sql + " AND t.filter IS NULL ORDER BY w.position"
        else:
            sql = base_sql + " AND t.filter = :filter ORDER BY w.position"
            params["filter"] = filter_type

        async with async_session_maker() as session:
            result = await session.execute(text(sql), params)
            return result.fetchall()

    async def generate_daily_word_task(self, user_id: int) -> UserLearningTask:
        try:
            book_info = await self.get_book_info(user_id)
            logger.info(f"book_info: {book_info}")
            if not book_info["daily_target"]:
                raise ValueError("Daily target not set")

            selected_book_id = book_info["bookId"]
            selected_book_type = book_info["selected_book_type"]
            book_filter_type = book_info["book_filter_type"]
            daily_target = book_info["daily_target"]

            # Build the filter condition separately
            filter_condition = ""
            if book_filter_type and book_filter_type != "null":
                filter_condition = f"and v.{book_filter_type} = 0"

            sql = f"""
                with known_words as (
                    select vb.word_id
                    from book_info bi 
                    join vocabulary_book vb on bi.id = vb.book_id
                    where bi.user_id = :user_id 
                    and bi.book_type = 'known'
                ),
                filtered_vocabulary as (
                    select v.id, v.word, v.detail_cn, v.sentence_image_key
                        from vocabulary_book vb
                            left join vocabulary v on v.id = vb.word_id
                            left join chat_reference cr on 
                                cr.reference_id = v.id 
                                    and cr.reference_type = 'vocabulary'
                                    and cr.user_id = :user_id
                    where 
                        v.{selected_book_type} = 1
                        and vb.book_id = :selected_book_id
                        and cr.id is null
                        {filter_condition}
                        and v.id not in (select word_id from known_words)
                )
                SELECT v.* 
                FROM filtered_vocabulary v
                WHERE 
                    v.sentence_image_key IS NOT NULL
                    and v.detail_cn is not null
                LIMIT :daily_target
            """.format(selected_book_type=selected_book_type, book_filter_type=book_filter_type)

            params = {
                "selected_book_id": selected_book_id,
                "user_id": user_id,
                "daily_target": daily_target,
            }

            async with async_session_maker() as session:
                result = await session.execute(text(sql), params)
                new_words = result.fetchall()

                if not new_words:
                    raise ValueError("All words have been learned")

                # Check existing task
                stmt = select(UserLearningTask).where(
                    and_(
                        UserLearningTask.user_id == user_id,
                        UserLearningTask.book_id == selected_book_id,
                        UserLearningTask.date == datetime.now().date(),
                        UserLearningTask.filter == book_filter_type
                    )
                )
                result = await session.execute(stmt)
                existing_task = result.scalar_one_or_none()

                if existing_task:
                    return existing_task
                else:
                    # Create new task
                    task = UserLearningTask(
                        user_id=user_id,
                        book_id=selected_book_id,
                        word_list=[{"id": word.id, "word": word.word} for word in new_words],
                        date=datetime.now().date(),
                        filter=book_filter_type
                    )
                    session.add(task)
                    await session.commit()
                    return task

        except Exception as e:
            logger.error(f"Error generating daily word task: {e}")
            raise e

    async def ensure_today_word_task(self, user_id: int) -> UserLearningTask:
        date = datetime.now().date()
        book_info = await self.get_book_info(user_id)
        logger.info(f"book_info: {book_info}")

        async with async_session_maker() as session:
            # Get existing task
            stmt = select(UserLearningTask).where(
                and_(
                    UserLearningTask.user_id == user_id,
                    UserLearningTask.date == date,
                    UserLearningTask.book_id == book_info["bookId"],
                    UserLearningTask.filter == book_info["book_filter_type"]
                )
            )
            result = await session.execute(stmt)
            task = result.scalar_one_or_none()

            if not task:
                task = await self.generate_daily_word_task(user_id)

            return task

    async def get_custom_books(self, user_id: int):
        async with async_session_maker() as session:
            # Build query
            stmt = (
                select(
                    BookInfo.id,
                    BookInfo.book_type,
                    BookInfo.book_name,
                    BookInfo.book_description,
                    BookInfo.book_cover,
                    func.count(VocabularyBook.word_id).label("word_count"),
                )
                .outerjoin(
                    VocabularyBook,
                    and_(
                        VocabularyBook.book_id == BookInfo.id,
                        VocabularyBook.user_id == user_id,
                    ),
                )
                .where(BookInfo.user_id == user_id)
                .group_by(
                    BookInfo.id,
                    BookInfo.book_name,
                    BookInfo.book_description,
                    BookInfo.book_cover,
                    BookInfo.book_image,
                )
                .order_by(asc(BookInfo.id))
            )

            result = await session.execute(stmt)
            books = result.all()

            # Format results
            return [
                {
                    "id": book.id,
                    "type": book.book_type,
                    "cover": book.book_cover,
                    "name": book.book_name,
                    "description": book.book_description,
                    "total_count": book.word_count,
                }
                for book in books
            ]

    async def get_daily_word_task_detail(self, user_id: int) -> list[WordTask]:
        """Get today's word task with chat information for each word"""
        async with async_session_maker() as session:
            task = await self.ensure_today_word_task(user_id)

            word_ids = [word["id"] for word in task.word_list]
            sql = """
                WITH reference_chats AS (
                    SELECT cr.*
                    FROM chat_reference cr
                    WHERE cr.reference_id IN :word_ids
                        AND cr.reference_type = :reference_type
                        AND cr.user_id = :user_id
                ),
                all_messages AS (
                    SELECT 
                        rc.chat_id, 
                        json_object(
                            'id', cm.id,
                            'author', cm.author,
                            'content', cm.content,
                            'create_time', cm.create_time
                        ) as message
                    FROM reference_chats rc 
                        inner join chat_message cm on cm.chat_id = rc.chat_id
                    where cm.chat_id is not null
                    order by cm.create_time
                )
                select
                    rc.chat_id,
                    rc.reference_id as word_id,
                    rc.phase,
                    if(am.message is null, JSON_ARRAY(), JSON_ARRAYAGG(am.message)) as message_list
                from reference_chats rc
                left join all_messages am on rc.chat_id = am.chat_id
                group by rc.chat_id, rc.reference_id
            """

            chats_result = await session.execute(
                text(sql),
                {
                    "word_ids": word_ids,
                    "reference_type": ReferenceType.VOCABULARY.value,
                    "user_id": user_id
                }
            )
            chats = {row.word_id: row for row in chats_result}

            # Build word list with chat info
            word_list = []
            for word in task.word_list:
                chat = chats.get(word["id"])
                word_list.append(WordTask(
                    word_id=word["id"],
                    word=word["word"],
                    message_list=json.loads(chat.message_list) if chat else [],
                    chat_id=chat.chat_id if chat else None,
                    phase=chat.phase if chat else None
                ))

            return word_list

    async def get_today_vocab_chat_ids(self, user_id: int):
        """Get today's vocabulary chat IDs"""
        async with async_session_maker() as session:
            # Get today's date in Beijing time
            beijing_now = time_now()
            today_start = beijing_now.replace(hour=0, minute=0, second=0, microsecond=0)
            today_end = today_start + timedelta(days=1)
            
            result = await session.execute(
                select(ChatReference).where(
                    and_(
                        ChatReference.user_id == user_id,
                        ChatReference.reference_type == 'vocabulary',
                        ChatReference.create_time >= today_start,
                        ChatReference.create_time < today_end
                    )
                ).order_by(ChatReference.create_time)
            )
            rows = result.scalars().all()
            return [row.chat_id for row in rows]

    async def get_current_word_task(self, user_id: int):
        """Get the current word task (first unfinished word) from today's task list"""
        async with async_session_maker() as session:
            # Get today's task
            task = await self.ensure_today_word_task(user_id)
            if not task or not task.word_list:
                return None

            # Get word IDs from task
            word_ids = [word["id"] for word in task.word_list]

            # Get chat references to check progress
            sql = """
                SELECT cr.reference_id as word_id, cr.phase, cr.chat_id
                FROM chat_reference cr
                WHERE cr.reference_id IN :word_ids
                    AND cr.reference_type = 'vocabulary'
                    AND cr.user_id = :user_id
            """
            result = await session.execute(
                text(sql),
                {"word_ids": tuple(word_ids), "user_id": user_id}
            )
            word_learning_phases = {row.word_id: {"phase": row.phase, "chat_id": row.chat_id} for row in result}

            chat_ids = []
            # Find first incomplete word
            for word in task.word_list:
                word_id = word["id"]
                learning_info = word_learning_phases.get(word_id, {})
                chat_id = learning_info.get("chat_id")
                if chat_id:
                    chat_ids.append(chat_id)
                if word_id not in word_learning_phases or learning_info["phase"] != 'question_answer':
                    # Get full word info
                    stmt = select(Vocabulary).where(Vocabulary.id == word_id)
                    result = await session.execute(stmt)
                    vocabulary = result.scalar_one_or_none()

                    if vocabulary:
                        return {
                            "word": vocabulary,
                            "learn_started": word_id in word_learning_phases,
                            "chat_ids": chat_ids,
                            "total": len(task.word_list),
                            "book_id": task.book_id,
                        }

            return None