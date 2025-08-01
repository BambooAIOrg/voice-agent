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
from plugins.tokenizer.mixedLanguageTokenizer import MixedLanguageTokenizer
from .log import logger
from .models import (
    TTSEncoding,
    TTSLanguages,
    TTSModels,
    TTSVoiceDefault,
    TTSVoiceEmotion,
    TTSVoiceSpeed,
)


class TTSAuthenticationError(Exception):
    """Raised when TTS authentication fails"""
    pass


class TTSConfigurationError(Exception):
    """Raised when TTS configuration is invalid"""
    pass

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
        # Validate and retrieve API credentials
        minimax_api_key = self._validate_api_key(api_key)
        minimax_group_id = self._validate_group_id(group_id)
        
        # Format API key securely
        minimax_api_key = self._format_api_key(minimax_api_key)

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
        # Set to 100 seconds to avoid Minimax server's 120-second timeout
        self._pool = utils.ConnectionPool[aiohttp.ClientWebSocketResponse](
            connect_cb=self._connect_ws,
            close_cb=self._close_ws,
            max_session_duration=100,  # Less than Minimax's 120s server timeout
            mark_refreshed_on_get=True,
        )
        logger.info("TTS initialized with connection pool, max_session_duration=100s")
        self._streams = weakref.WeakSet[SynthesizeStream]()
    
    def _validate_api_key(self, api_key: NotGivenOr[str]) -> str:
        """Validate and retrieve API key with proper error handling"""
        key = api_key if is_given(api_key) else os.environ.get("MINIMAX_API_KEY")
        
        if not key:
            raise TTSConfigurationError(
                "MINIMAX_API_KEY must be set either as parameter or environment variable"
            )
        
        # Basic validation - ensure it's not empty or placeholder
        if not key.strip() or key.strip() in ["your_api_key", "placeholder", "test"]:
            raise TTSAuthenticationError(
                "Invalid API key format. Please provide a valid Minimax API key."
            )
        
        return key.strip()
    
    def _validate_group_id(self, group_id: NotGivenOr[str]) -> str:
        """Validate and retrieve group ID with proper error handling"""
        gid = group_id if is_given(group_id) else os.environ.get("MINIMAX_GROUP_ID")
        
        if not gid:
            raise TTSConfigurationError(
                "MINIMAX_GROUP_ID must be set either as parameter or environment variable"
            )
        
        # Basic validation
        if not gid.strip():
            raise TTSAuthenticationError(
                "Invalid group ID format. Please provide a valid Minimax group ID."
            )
        
        return gid.strip()
    
    def _format_api_key(self, api_key: str) -> str:
        """Format API key with Bearer prefix securely"""
        # Strip existing Bearer prefix if present
        if api_key.startswith("Bearer "):
            api_key = api_key[7:]
        
        # Ensure the API key is properly formatted with Bearer prefix
        return f"Bearer {api_key}"

    async def _connect_ws(
        self,
        timeout: float | None = None,
    ) -> aiohttp.ClientWebSocketResponse:
        """Create a new WebSocket connection.

        The ``utils.ConnectionPool`` helper passes a single positional
        ``timeout`` argument to the ``connect_cb`` callback. To remain
        compatible we accept this argument (defaulting to ``None``) and use it
        when opening the underlying WebSocket.  If *timeout* is *None* we fall
        back to the value provided by ``self._conn_options``.
        """

        session = self._ensure_session()
        url = self._opts.get_ws_url("/ws/v1/t2a_v2")
        headers = {API_KEY_HEADER: self._opts.api_key}

        # Fallback to the instance-level connect options if provided, otherwise
        # use a sensible default.  We ignore typing here because ``_conn_options``
        # is injected by the LiveKit base class at runtime.
        if timeout is not None:
            ws_timeout = timeout
        else:
            ws_timeout = getattr(self, "_conn_options", type("_", (), {"timeout": 30.0})()).timeout  # type: ignore[attr-defined]

        try:
            ws = await asyncio.wait_for(
                session.ws_connect(url, headers=headers, heartbeat=10.0),
                timeout=ws_timeout,
            ) 
        except (asyncio.TimeoutError, aiohttp.ClientConnectionError, OSError) as e:
            logger.error(f"Failed to connect to WebSocket: {type(e).__name__}")
            raise APIConnectionError(f"Failed to connect to WebSocket: {type(e).__name__}")

        try:
            await self._start_task(ws)
        except Exception as e:
            logger.error(f"Failed to start task on WebSocket: {type(e).__name__}")
            await ws.close()
            raise APIConnectionError(f"Failed to start task on WebSocket: {type(e).__name__}")
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
        try:
            await ws.send_json(start_msg)
        except (aiohttp.ClientConnectionError, ConnectionResetError) as e:
            logger.error(f"Failed to send task_start message: {e}")
            raise APIConnectionError(f"Failed to send task_start message: {e}")
        
    async def _close_ws(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        logger.info(f"Closing WebSocket connection, current state: closed={ws.closed}")
        await ws.close()
        logger.info("WebSocket connection closed")

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
    """Stream implementation that tokenizes input text incrementally and
    produces synthesized audio frames via Minimax WebSocket API."""

    def __init__(
        self,
        *,
        tts: TTS,
        opts: _TTSOptions,
        pool: utils.ConnectionPool[aiohttp.ClientWebSocketResponse],
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
    ) -> None:
        super().__init__(tts=tts, conn_options=conn_options)

        self._tts = tts
        self._opts = opts
        self._pool = pool

        # Tokenize input text stream-wise for better latency
        self._sent_tokenizer_stream = (
            MixedLanguageTokenizer(
                min_sentence_len=3,
                stream_context_len=5,
                retain_format=True,
            ).stream()
        )

        self._request_id = utils.shortuuid()

        self._reconnect_event = asyncio.Event()
        self._no_tokens_sent_event = asyncio.Event()

        # Track pending tasks from server (per token) so we can know when to end
        self._pending_tasks_count = 0
        self._pending_tasks_lock = asyncio.Lock()
        self._tokenizer_finished = False
        self._tokenizer_stream_closed = False

    # ---------------------------------------------------------------------
    # Core run-loop required by livekit.agents.tts.SynthesizeStream
    # ---------------------------------------------------------------------

    async def _run(self, output_emitter: "tts.AudioEmitter") -> None:  # type: ignore[override]
        """Implementation of the synthesis pipeline.

        The LiveKit TTS framework will retry this function transparently on
        recoverable errors, passing in an ``AudioEmitter`` instance that we
        must use to push synthesized frames back to the SDK.
        """

        # Initialise emitter – enable *streaming* so we can push frames as we
        # receive them from the server.
        output_emitter.initialize(
            request_id=self._request_id,
            sample_rate=self._opts.sample_rate,
            num_channels=self._opts.channels,
            mime_type="audio/pcm",
            stream=True,
        )

        # Start first segment so the emitter collects frames immediately.
        output_emitter.start_segment(segment_id="0")

        start_time = time.time()
        async with self._pool.connection(timeout=self._conn_options.timeout) as ws:
            logger.info(f"retrieve connection: take time: {time.time() - start_time:.2f}s")

            if ws.closed:
                logger.error(f"[{self._request_id}] WebSocket connection from pool is already closed")
                raise APIConnectionError("WebSocket connection from pool is already closed")
            
            # Launch concurrent tasks: push text, send to WS, receive audio.
            input_task = asyncio.create_task(self._input_task())
            send_task = asyncio.create_task(self._send_task(ws))
            recv_task = asyncio.create_task(self._recv_task(ws, output_emitter))

            tasks = [input_task, send_task, recv_task]

            try:
                results = await asyncio.gather(*tasks, return_exceptions=True)

                # Log any exception encountered within sub-tasks.
                for idx, res in enumerate(results):
                    if isinstance(res, Exception):
                        name = ["input_task", "send_task", "recv_task"][idx]
                        logger.warning(f"[{self._request_id}] {name} exited with: {res}")
                        raise res
            finally:
                logger.info(f"[{self._request_id}] Finishing _run, WebSocket state: closed={ws.closed}")
                await utils.aio.gracefully_cancel(*tasks)

    async def _input_task(self) -> None:
        """Reads text from the input channel and pushes it to the tokenizer."""
        try:
            async for data_item in self._input_ch:
                if isinstance(data_item, self._FlushSentinel):
                    self._sent_tokenizer_stream.flush()
                    continue
                self._sent_tokenizer_stream.push_text(data_item)

            self._end_tokenizer_input()
        except asyncio.CancelledError:
            logger.info(f"[{self._request_id}] Input task cancelled.")
            # Ensure tokenizer is properly closed even when cancelled
            self._end_tokenizer_input()
            raise
        except Exception as e:
            logger.exception(f"[{self._request_id}] Error in _input_task: {e}")
            # End tokenizer input on error to prevent hanging
            self._end_tokenizer_input()
            raise
    
    def _end_tokenizer_input(self) -> None:
        """Safely end tokenizer input, ensuring it's only called once."""
        if not self._tokenizer_stream_closed:
            try:
                self._sent_tokenizer_stream.end_input()
                self._tokenizer_stream_closed = True
            except Exception as e:
                logger.warning(f"[{self._request_id}] Error ending tokenizer input: {e}")
                # Still mark as closed to prevent further attempts
                self._tokenizer_stream_closed = True

    async def _send_task(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        """Reads tokens from the tokenizer and sends them to the WebSocket."""
        try:
            has_any_token_to_send = False
            async for ev in self._sent_tokenizer_stream:
                token = ev.token
                if not token.strip(): # Avoid sending empty strings
                    continue
                    
                has_any_token_to_send = True
                send_payload = {
                    "event": "task_continue",
                    "text": token + " "
                }
                logger.info(f"[{self._request_id}] Sending task_continue event: {send_payload}")
                self._mark_started()
                
                # 增加待处理任务计数
                async with self._pending_tasks_lock:
                    self._pending_tasks_count += 1
                
                # Check if WebSocket is still open before sending
                if ws.closed:
                    logger.error(f"[{self._request_id}] WebSocket connection is closed, cannot send data. Close code: {ws.close_code}, Close reason: {ws.exception()}")
                    raise APIConnectionError("WebSocket connection closed by server")
                
                try:
                    await ws.send_json(send_payload)
                except (aiohttp.ClientConnectionError, ConnectionResetError) as e:
                    logger.error(f"[{self._request_id}] WebSocket send failed: {e}")
                    raise APIConnectionError(f"WebSocket send failed: {e}")

            # Mark tokenizer as finished
            async with self._pending_tasks_lock:
                self._tokenizer_finished = True
                logger.info(f"[{self._request_id}] Tokenizer stream completed. Total tasks sent: {self._pending_tasks_count}")
            
            # Only set _no_tokens_sent_event if there were genuinely no tokens to send
            if not has_any_token_to_send:
                logger.info(f"[{self._request_id}] No tokens to send, setting _no_tokens_sent_event")
                self._no_tokens_sent_event.set()
        except (aiohttp.ClientError, ConnectionResetError, OSError) as e:
            logger.error(f"[{self._request_id}] WebSocket connection error in _send_task: {e}")
            raise APIConnectionError(f"WebSocket connection failed: {e}")
        except Exception as e:
            logger.exception(f"[{self._request_id}] Error in _send_task: {e}")
            raise

    async def _recv_task(self, ws: aiohttp.ClientWebSocketResponse, emitter: "tts.AudioEmitter") -> None:
        """Receives messages from the WebSocket and processes audio/errors."""
        # AudioEmitter expects raw audio bytes. We'll forward the PCM chunk
        # bytes we receive from the server directly to the provided emitter.
        try:
            while True:
                # 先检查是否应该退出
                async with self._pending_tasks_lock:
                    if self._tokenizer_finished and self._pending_tasks_count <= 0:
                        break

                # 等待 WebSocket 消息或 _no_tokens_sent_event 被设置
                receive_ws_task = asyncio.create_task(ws.receive())
                wait_no_tokens_event_task = asyncio.create_task(self._no_tokens_sent_event.wait())
                
                tasks_to_wait = [receive_ws_task, wait_no_tokens_event_task]
                
                timeout_task = None
                async with self._pending_tasks_lock:
                    if self._tokenizer_finished and self._pending_tasks_count > 0:
                        # 给每个等待中的响应更短的超时时间
                        timeout_task = asyncio.create_task(asyncio.sleep(5))
                        tasks_to_wait.append(timeout_task)

                done, pending = await asyncio.wait(
                    tasks_to_wait,
                    return_when=asyncio.FIRST_COMPLETED
                )

                # 取消未完成的任务
                for task in pending:
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass

                if wait_no_tokens_event_task in done:
                    logger.info(f"[{self._request_id}] _no_tokens_sent_event was set. "
                                   f"Assuming no response from server is expected. Ending _recv_task.")
                    break
                
                if timeout_task and timeout_task in done:
                    async with self._pending_tasks_lock:
                        logger.warning(f"[{self._request_id}] Timeout waiting for remaining responses. "
                                     f"Tokenizer finished but {self._pending_tasks_count} tasks still pending. Ending _recv_task.")
                    break

                # 如果是 ws.receive() 完成
                try:
                    msg = receive_ws_task.result()
                except (aiohttp.ClientConnectionError, ConnectionResetError) as e:
                    logger.error(f"[{self._request_id}] WebSocket receive failed: {e}")
                    raise APIConnectionError(f"WebSocket receive failed: {e}")

                if msg.type in (
                    aiohttp.WSMsgType.CLOSED,
                    aiohttp.WSMsgType.CLOSE,
                    aiohttp.WSMsgType.CLOSING,
                ):
                    # Properly end the stream when WebSocket connection closes
                    logger.info(f"[{self._request_id}] WebSocket connection closed by server, msg_type={msg.type}, close_code={ws.close_code}, close_reason={ws.exception()}")
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
                        emitter.flush()
                        break

                    if audio_present:
                        audio_hex = data["data"]["audio"]
                        try:
                            # Decode the hex data first
                            audio_data = bytes.fromhex(audio_hex)
                            
                            # Forward raw PCM bytes to emitter
                            emitter.push(audio_data)
                            
                        except ValueError as hex_e:
                            logger.exception(f"[{self._request_id}] Failed to decode hex audio:")
                            self._emit_error(APIError(f"Failed to decode hex audio", body=hex_e), recoverable=False)
                        except Exception as frame_e:
                             logger.exception(f"[{self._request_id}] Failed to process audio bytes or push frame:")
                             self._emit_error(APIError(f"Failed to process audio", body=frame_e), recoverable=False)

                    if is_final:
                        # Indicate end-of-segment so emitter can emit final frame
                        emitter.flush()
                        
                        # decrease the pending tasks count
                        async with self._pending_tasks_lock:
                            self._pending_tasks_count -= 1
                            # break the loop if tokenizer is finished and all tasks are completed
                            if self._tokenizer_finished and self._pending_tasks_count <= 0:
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
            try:
                emitter.flush()
            except Exception as flush_e:
                 logger.exception(f"[{self._request_id}] Error flushing emitter in finally block:")
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