from __future__ import annotations

import asyncio
import base64
import json
import os
import tempfile
import weakref
import time
from dataclasses import dataclass
from typing import Any, Literal, Optional, Union
from wsgiref.util import request_uri

import aiohttp

from livekit.agents import (
    APIConnectionError,
    APIConnectOptions,
    APIStatusError,
    APITimeoutError,
    APIError,
    tokenize,
    tts,
    utils,
)
from livekit.agents.types import (
    DEFAULT_API_CONNECT_OPTIONS,
    NOT_GIVEN,
    NotGivenOr,
)
from livekit.agents.utils import is_given

from .log import logger
from .models import (
    TTSEncoding,
    TTSLanguages,
    TTSModels,
    TTSVoiceDefault,
    TTSVoiceEmotion,
    TTSVoiceSpeed,
)

API_KEY_HEADER = "Authorization"
GROUP_ID_PARAM = "GroupId"
API_VERSION = "2024-06-10"

NUM_CHANNELS = 1
SAMPLE_RATE = 24000  # Minimax uses 24kHz sample rate

# Audio format types supported by MiniMax
AudioFormatType = Literal["mp3", "pcm", "flac"]
# Sample rate options
SampleRateType = Literal[8000, 16000, 22050, 24000, 32000, 44100]
# Bitrate options
BitrateType = Literal[32000, 64000, 128000, 256000]
# Channel options
ChannelType = Literal[1, 2]

@dataclass
class _TTSOptions:
    model: TTSModels | str
    encoding: TTSEncoding
    sample_rate: SampleRateType
    voice_id: str
    speed: NotGivenOr[TTSVoiceSpeed | str]
    emotion: NotGivenOr[TTSVoiceEmotion | str]
    api_key: str
    group_id: str
    language: NotGivenOr[TTSLanguages | str]
    base_url: str
    # Audio settings
    bitrate: BitrateType
    channels: ChannelType

    def get_http_url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def get_ws_url(self, path: str) -> str:
        return f"{self.base_url.replace('http', 'ws', 1)}{path}"


class TTS(tts.TTS):
    def __init__(
        self,
        *,
        model: TTSModels | str = "speech-01-hd",
        language: NotGivenOr[TTSLanguages | str] = NOT_GIVEN,
        encoding: TTSEncoding = "pcm_s16le",
        voice_id: str = TTSVoiceDefault,
        speed: NotGivenOr[TTSVoiceSpeed | str] = NOT_GIVEN,
        emotion: NotGivenOr[TTSVoiceEmotion | str] = NOT_GIVEN,
        sample_rate: SampleRateType = 32000,
        bitrate: BitrateType = 128000,
        channels: ChannelType = 1,
        api_key: NotGivenOr[str] = NOT_GIVEN,
        group_id: NotGivenOr[str] = NOT_GIVEN,
        http_session: aiohttp.ClientSession | None = None,
        base_url: str = "https://api.minimaxi.chat",
    ) -> None:
        """
        Create a new instance of Minimax TTS.

        See https://www.minimax.io/platform/document/T2A%20V2?key=66719005a427f0c8a5701643 for more details on the Minimax API.

        Args:
            model (TTSModels, optional): The Minimax TTS model to use. Defaults to "speech-01-hd".
            language (TTSLanguages, optional): The language code for synthesis. Use "zh" for Chinese, "en" for English.
            encoding (TTSEncoding, optional): The audio encoding format. Defaults to "pcm_s16le".
            voice_id (str, optional): The voice ID to use.
            speed (TTSVoiceSpeed | str, optional): Voice speed control (0.5 to 2.0)
            emotion (TTSVoiceEmotion, optional): Voice emotion type
            sample_rate (int, optional): The audio sample rate in Hz. Defaults to 32000.
                                         Available options: 8000, 16000, 22050, 24000, 32000, 44100
            bitrate (int, optional): Bitrate of generated sound. Options: 32000, 64000, 128000, 256000. Defaults to 128000.
            channels (int, optional): Number of channels for the audio. 1 for mono, 2 for stereo. Defaults to 1.
            api_key (str, optional): The Minimax API key. If not provided, it will be read from the MINIMAX_API_KEY environment variable.
            group_id (str, optional): The Minimax group ID. If not provided, it will be read from the MINIMAX_GROUP_ID environment variable.
            http_session (aiohttp.ClientSession | None, optional): An existing aiohttp ClientSession to use. If not provided, a new session will be created.
            base_url (str, optional): The base URL for the Minimax API. Defaults to "https://api.minimaxi.chat".
        """

        super().__init__(
            capabilities=tts.TTSCapabilities(streaming=True),
            sample_rate=sample_rate,
            num_channels=channels,
        )
        minimax_api_key = api_key if is_given(api_key) else os.environ.get("MINIMAX_API_KEY")
        if not minimax_api_key:
            raise ValueError("MINIMAX_API_KEY must be set")

        minimax_group_id = group_id if is_given(group_id) else os.environ.get("MINIMAX_GROUP_ID")
        if not minimax_group_id:
            raise ValueError("MINIMAX_GROUP_ID must be set")

        # Strip "Bearer " prefix if it exists
        if minimax_api_key.startswith("Bearer "):
            minimax_api_key = minimax_api_key[7:]

        # Ensure the API key is properly formatted with Bearer prefix
        minimax_api_key = f"Bearer {minimax_api_key}"

        self._opts = _TTSOptions(
            model=model,
            language=language,
            encoding=encoding,
            sample_rate=sample_rate,
            voice_id=voice_id,
            speed=speed,
            emotion=emotion,
            api_key=minimax_api_key,
            group_id=minimax_group_id,
            base_url=base_url,
            bitrate=bitrate,
            channels=channels,
        )
        self._session = http_session
        # Add connection pool for WebSocket connections
        self._pool = utils.ConnectionPool[aiohttp.ClientWebSocketResponse](
            connect_cb=self._connect_ws,
            close_cb=self._close_ws,
            max_session_duration=300,  # 5 minutes max session duration
            mark_refreshed_on_get=True,
        )
        self._streams = weakref.WeakSet[SynthesizeStream]()

    async def _connect_ws(self) -> aiohttp.ClientWebSocketResponse:
        """Create a new WebSocket connection."""
        session = self._ensure_session()
        url = self._opts.get_ws_url(f"/ws/v1/t2a_v2")
        headers = {API_KEY_HEADER: self._opts.api_key}
        
        logger.debug(f"Connecting to WebSocket: {url}")
        ws = await asyncio.wait_for(
            session.ws_connect(url, headers=headers, heartbeat=30.0),
            timeout=self._conn_options.timeout
        )

        logger.debug(f"start task")
        await self._start_task(ws)
        return ws
    
    async def _start_task(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        start_msg = {
            "event": "task_start",
            "model": self._opts.model,
            "voice_setting": {
                "voice_id": self._opts.voice_id,
                "speed": 1.0 if not is_given(self._opts.speed) else float(self._opts.speed),
                "vol": 1.0,
                "pitch": 0,
                "emotion": "neutral" if not is_given(self._opts.emotion) else self._opts.emotion
            },
            "audio_setting": {
                "sample_rate": self._opts.sample_rate,
                "bitrate": self._opts.bitrate,
                "format": "pcm",
                "channel": self._opts.channels
            }
        }
        logger.debug(f"Sending task_start message: {start_msg}")
        await ws.send_json(start_msg)
        
    async def _close_ws(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        await ws.close()

    def _ensure_session(self) -> aiohttp.ClientSession:
        if not self._session:
            self._session = utils.http_context.http_session()

        return self._session

    def prewarm(self) -> None:
        """Prewarm the connection pool by creating a connection in advance."""
        self._pool.prewarm()

    def update_options(
        self,
        *,
        model: NotGivenOr[TTSModels | str] = NOT_GIVEN,
        language: NotGivenOr[TTSLanguages | str] = NOT_GIVEN,
        voice_id: NotGivenOr[str] = NOT_GIVEN,
        speed: NotGivenOr[TTSVoiceSpeed | str] = NOT_GIVEN,
        emotion: NotGivenOr[TTSVoiceEmotion | str] = NOT_GIVEN,
    ) -> None:
        """
        Update the Text-to-Speech (TTS) configuration options.

        This method allows updating the TTS settings, including model type, language, voice, speed,
        and emotion. If any parameter is not provided, the existing value will be retained.

        Args:
            model (TTSModels, optional): The Minimax TTS model to use.
            language (TTSLanguages, optional): The language code for synthesis.
            voice_id (str, optional): The voice ID to use.
            speed (TTSVoiceSpeed | str, optional): Voice speed control (0.5 to 2.0)
            emotion (TTSVoiceEmotion, optional): Voice emotion type
        """
        if is_given(model):
            self._opts.model = model
        if is_given(language):
            self._opts.language = language
        if is_given(voice_id):
            self._opts.voice_id = voice_id
        if is_given(speed):
            self._opts.speed = speed
        if is_given(emotion):
            self._opts.emotion = emotion

    def synthesize(
        self,
        text: str,
        *,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
    ):
        pass

    def stream(
        self, *, conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS
    ) -> SynthesizeStream:
        stream = SynthesizeStream(
            tts=self, 
            opts=self._opts, 
            pool=self._pool,
            conn_options=conn_options
        )
        self._streams.add(stream)
        return stream

    async def aclose(self) -> None:
        for stream in list(self._streams):
            await stream.aclose()
        self._streams.clear()
        await self._pool.aclose()
        await super().aclose()

class SynthesizeStream(tts.SynthesizeStream):
    """A stream that processes text incrementally as it arrives using WebSocket."""

    def __init__(
        self,
        *,
        tts: TTS,
        opts: _TTSOptions,
        pool: utils.ConnectionPool[aiohttp.ClientWebSocketResponse],
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
    ):
        super().__init__(tts=tts, conn_options=conn_options)
        self._tts = tts
        self._opts = opts
        self._pool = pool
        # Use a basic sentence tokenizer
        self._sent_tokenizer_stream = tokenize.basic.SentenceTokenizer().stream() 
        self._request_id = utils.shortuuid()  # Generate a request ID for this stream

        self._reconnect_event = asyncio.Event()
        self._no_tokens_sent_event = asyncio.Event()
        
        # 添加计数器跟踪未完成的任务数量
        self._pending_tasks_count = 0
        self._pending_tasks_lock = asyncio.Lock()

    async def _run(self) -> None:
        async with self._pool.connection() as ws:
            # Create and run input, send, and receive tasks ONLY after task_started
            input_task = asyncio.create_task(self._input_task())
            send_task = asyncio.create_task(self._send_task(ws))
            recv_task = asyncio.create_task(self._recv_task(ws))
            tasks = [
                input_task,
                send_task,
                recv_task,
            ]

            try:
                await asyncio.gather(*tasks)
            finally:
                await utils.aio.gracefully_cancel(*tasks)

    async def _input_task(self) -> None:
        """Reads text from the input channel and pushes it to the tokenizer."""
        try:
            async for data_item in self._input_ch:
                if isinstance(data_item, self._FlushSentinel):
                    self._sent_tokenizer_stream.flush()
                    continue
                self._sent_tokenizer_stream.push_text(data_item)

            self._sent_tokenizer_stream.end_input()
        except asyncio.CancelledError:
            logger.info(f"[{self._request_id}] Input task cancelled.")
            # Ensure tokenizer is properly closed even when cancelled
            self._sent_tokenizer_stream.end_input()
            raise
        except Exception as e:
            logger.exception(f"[{self._request_id}] Error in _input_task: {e}")
            # End tokenizer input on error to prevent hanging
            self._sent_tokenizer_stream.end_input()
            raise

    async def _send_task(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        """Reads tokens from the tokenizer and sends them to the WebSocket."""
        try:
            has_sent_any_token = False
            async for ev in self._sent_tokenizer_stream:
                token = ev.token
                if not token.strip(): # Avoid sending empty strings
                    continue
                    
                send_payload = {
                    "event": "task_continue",
                    "text": token + " "
                }
                logger.info(f"[{self._request_id}] Sending task_continue event: {send_payload}")
                self._mark_started()
                
                # 增加待处理任务计数
                async with self._pending_tasks_lock:
                    self._pending_tasks_count += 1
                    logger.debug(f"[{self._request_id}] Incremented pending tasks count to {self._pending_tasks_count}")
                
                await ws.send_json(send_payload)
                has_sent_any_token = True

            logger.info(f"[{self._request_id}] Tokenizer stream completed.")
            if not has_sent_any_token:
                self._no_tokens_sent_event.set()
        except Exception as e:
            logger.exception(f"[{self._request_id}] Error in _send_task: {e}")
            raise

    async def _recv_task(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        """Receives messages from the WebSocket and processes audio/errors."""
        # Create an AudioByteStream to handle chunking into AudioFrames
        audio_bstream = utils.audio.AudioByteStream(self._opts.sample_rate, self._opts.channels)
        emitter = tts.SynthesizedAudioEmitter(
            event_ch=self._event_ch,
            request_id=self._request_id,
        )       
        try:
            while True:
                # 等待 WebSocket 消息 或 _no_tokens_sent_event 被设置
                receive_ws_task = asyncio.create_task(ws.receive())
                wait_no_tokens_event_task = asyncio.create_task(self._no_tokens_sent_event.wait())

                done, pending = await asyncio.wait(
                    [receive_ws_task, wait_no_tokens_event_task],
                    return_when=asyncio.FIRST_COMPLETED
                )

                # 总是先取消未完成的任务
                for task in pending:
                    task.cancel()
                    try:
                        await task # 等待取消完成
                    except asyncio.CancelledError:
                        pass # 预期的

                if wait_no_tokens_event_task in done:
                    logger.info(f"[{self._request_id}] _no_tokens_sent_event was set. "
                                   f"Assuming no response from server is expected. Ending _recv_task.")
                    break # 跳出主循环，结束 _recv_task

                # 如果是 ws.receive() 完成
                msg = receive_ws_task.result() # 获取 ws.receive() 的结果

                if msg.type in (
                    aiohttp.WSMsgType.CLOSED,
                    aiohttp.WSMsgType.CLOSE,
                    aiohttp.WSMsgType.CLOSING,
                ):
                    # Properly end the stream when WebSocket connection closes
                    for frame in audio_bstream.flush():
                        emitter.push(frame)
                    emitter.flush()
                    break
                
                if msg.type == aiohttp.WSMsgType.TEXT:
                    data = json.loads(msg.data)
                    api_error = data.get("event") == "error"
                    audio_present = "data" in data and "audio" in data["data"]
                    is_final = data.get("is_final", False)

                    if api_error:
                        error_msg = data.get('message', 'Unknown streaming error')
                        logger.error(f"[{self._request_id}] Minimax returned error: {error_msg}")
                        self._emit_error(APIStatusError(error_msg, status_code=400), recoverable=False)
                        # End the stream for critical errors
                        for frame in audio_bstream.flush():
                            emitter.push(frame)
                        emitter.flush()
                        break

                    if audio_present:
                        audio_hex = data["data"]["audio"]
                        try:
                            # Decode the hex data first
                            audio_data = bytes.fromhex(audio_hex)
                            
                            # Feed the raw PCM bytes into the AudioByteStream
                            # and push the resulting frames using the emitter
                            for frame in audio_bstream.write(audio_data):
                                emitter.push(frame)
                                
                        except ValueError as hex_e:
                            logger.exception(f"[{self._request_id}] Failed to decode hex audio:")
                            self._emit_error(APIError(f"Failed to decode hex audio", body=hex_e), recoverable=False)
                        except Exception as frame_e:
                             logger.exception(f"[{self._request_id}] Failed to process audio bytes or push frame:")
                             self._emit_error(APIError(f"Failed to process audio", body=frame_e), recoverable=False)

                    if is_final:
                        logger.debug(f"[{self._request_id}] Received is_final=True. Flushing audio stream and emitter.")
                        # Flush any remaining buffered audio in AudioByteStream
                        for frame in audio_bstream.flush():
                             emitter.push(frame)
                             logger.debug(f"[{self._request_id}] Pushed flushed frame of duration {frame.duration:.3f}s")
                        # Mark the end of the segment for this text chunk
                        emitter.flush()
                        
                        # decrease the pending tasks count
                        async with self._pending_tasks_lock:
                            self._pending_tasks_count -= 1
                            logger.debug(f"[{self._request_id}] Decremented pending tasks count to {self._pending_tasks_count}")
                            
                            # break the loop if all tasks are completed
                            if self._pending_tasks_count <= 0:
                                logger.debug(f"[{self._request_id}] All tasks completed. Breaking recv_task loop.")
                                break
        except asyncio.TimeoutError:
            # Standard timeout occurred - server didn't respond or close connection in time
            logger.error(f"[{self._request_id}] Timeout waiting for WebSocket message or closure.")
            raise APITimeoutError("Timeout waiting for Minimax message or closure")
        except asyncio.CancelledError:
            logger.info(f"[{self._request_id}] Receive task cancelled.")
            raise
        except Exception as e:
            logger.exception(f"[{self._request_id}] Error in _recv_task:")
            # Propagate error
            raise
        finally:
            # Ensure any remaining audio in the buffer is flushed when the task ends
            try:
                logger.debug(f"[{self._request_id}] Flushing final audio bytes in _recv_task finally block.")
                for frame in audio_bstream.flush():
                    emitter.push(frame)
                    logger.debug(f"[{self._request_id}] Pushed final flushed frame of duration {frame.duration:.3f}s")
                # Signal completion for clean termination
                emitter.flush()
            except Exception as flush_e:
                 logger.exception(f"[{self._request_id}] Error flushing audio buffer in finally block:")
            # reset the event, so the next stream call can be reused
            self._no_tokens_sent_event.clear()

def _to_minimax_options(opts: _TTSOptions) -> dict[str, Any]:
    """Convert TTSOptions to Minimax API options."""
    payload: dict[str, Any] = {
        "model": opts.model,
        "voice_id": opts.voice_id,
    }

    # Add optional parameters if provided
    if is_given(opts.language):
        payload["language"] = opts.language
    
    if is_given(opts.speed):
        payload["speed"] = opts.speed
    
    if is_given(opts.emotion):
        payload["emotion"] = opts.emotion
        
    # Add audio format settings
    payload["audio_format"] = {
        "format": "pcm",  # Default for streaming
        "sample_rate": opts.sample_rate,
        "bitrate": opts.bitrate,
        "channel": opts.channels
    }

    return payload