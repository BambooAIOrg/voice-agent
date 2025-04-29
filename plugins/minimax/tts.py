from __future__ import annotations

import asyncio
import base64
import json
import os
import tempfile
import weakref
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
        self._conn_options = DEFAULT_API_CONNECT_OPTIONS
        self._streams = weakref.WeakSet[SynthesizeStream]()

    def _ensure_session(self) -> aiohttp.ClientSession:
        if not self._session:
            self._session = utils.http_context.http_session()

        return self._session

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
    ) -> ChunkedStream:
        return ChunkedStream(
            tts=self,
            input_text=text,
            opts=self._opts,
            session=self._ensure_session(),
            conn_options=conn_options,
        )

    def stream(
        self, *, conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS
    ) -> SynthesizeStream:
        stream = SynthesizeStream(tts=self, opts=self._opts, session=self._ensure_session())
        self._streams.add(stream)
        return stream

    async def aclose(self) -> None:
        for stream in list(self._streams):
            await stream.aclose()


class ChunkedStream(tts.ChunkedStream):
    """A stream that processes text as a single chunk."""

    def __init__(
        self,
        *,
        tts: TTS,
        input_text: str,
        opts: _TTSOptions,
        session: aiohttp.ClientSession,
        conn_options: APIConnectOptions,
    ) -> None:
        super().__init__(tts=tts, input_text=input_text)
        self._tts = tts
        self._input_text = input_text
        self._opts = opts
        self._session = session
        self._conn_options = conn_options
        self._audio_bytes = bytearray()
        self._audio_event = asyncio.Event()
        self._completion_event = asyncio.Event()
        self._error_msg: Optional[str] = None
        self._task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        try:
            # Get url with query parameters
            url = self._opts.get_http_url(f"/v1/t2a")
            params = {GROUP_ID_PARAM: self._opts.group_id}
            
            # Prepare headers
            headers = {
                API_KEY_HEADER: self._opts.api_key,
                "Content-Type": "application/json"
            }

            # Prepare payload
            payload = _to_minimax_options(self._opts)
            payload["text"] = self._input_text

            # Make API call
            timeout = aiohttp.ClientTimeout(total=self._conn_options.timeout)
            async with self._session.post(
                url,
                params=params,
                headers=headers,
                json=payload,
                timeout=timeout,
            ) as resp:
                if resp.status != 200:
                    try:
                        error_json = await resp.json()
                        error_message = error_json.get("base_resp", {}).get("status_msg", "Unknown error")
                    except Exception:
                        error_message = await resp.text()
                    raise APIStatusError(
                        f"Minimax API returned error {resp.status}: {error_message}",
                        status_code=resp.status,
                    )

                # Process the response
                response_json = await resp.json()
                
                if "audio_file" in response_json:
                    # Base64 encoded audio data
                    audio_data = base64.b64decode(response_json["audio_file"])
                    
                    # If the audio is in MP3 format, we need to convert it to PCM
                    if self._opts.encoding == "mp3":
                        # For now, just use the raw data without conversion
                        # MP3 to PCM conversion would require additional dependencies
                        pass
                    
                    self._audio_bytes.extend(audio_data)
                    self._audio_event.set()
                else:
                    error_message = response_json.get("base_resp", {}).get("status_msg", "No audio data returned")
                    raise APIStatusError(
                        f"Minimax API failed: {error_message}",
                        status_code=400,
                    )
        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.error(f"Error in TTS chunked stream: {e}")
            self._error_msg = str(e)
        finally:
            self._completion_event.set()

    async def read(self, n: int = -1) -> bytes:
        """Read audio data from the stream."""
        if self._error_msg:
            raise RuntimeError(self._error_msg)

        # Wait for some data to be available
        if not self._audio_bytes and not self._completion_event.is_set():
            audio_wait = asyncio.create_task(self._audio_event.wait())
            completion_wait = asyncio.create_task(self._completion_event.wait())
            await asyncio.wait(
                [audio_wait, completion_wait],
                return_when=asyncio.FIRST_COMPLETED,
            )
            if not audio_wait.done():
                audio_wait.cancel()
            if not completion_wait.done():
                completion_wait.cancel()
            self._audio_event.clear()

        if not self._audio_bytes and self._error_msg is not None:
            raise RuntimeError(self._error_msg)

        # Return all available data if n is -1
        if n == -1:
            data = bytes(self._audio_bytes)
            self._audio_bytes.clear()
            return data

        # Otherwise, return at most n bytes
        if len(self._audio_bytes) <= n:
            data = bytes(self._audio_bytes)
            self._audio_bytes.clear()
            return data

        data = bytes(self._audio_bytes[:n])
        del self._audio_bytes[:n]
        return data

    async def aclose(self) -> None:
        """Close the stream."""
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass


class SynthesizeStream(tts.SynthesizeStream):
    """A stream that processes text incrementally as it arrives using WebSocket,
       similar to Cartesia's implementation pattern."""

    def __init__(
        self,
        *,
        tts: TTS,
        opts: _TTSOptions,
        session: aiohttp.ClientSession,
    ):
        super().__init__(tts=tts, conn_options=tts._conn_options)
        self._tts = tts
        self._opts = opts
        self._session = session
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._task_started = False
        
        # Use a basic sentence tokenizer (can adjust buffer settings if needed)
        self._sent_tokenizer_stream = tokenize.basic.SentenceTokenizer().stream() 
        self._request_id = utils.shortuuid() # Generate a request ID for this stream
        
    def _ensure_session(self) -> aiohttp.ClientSession:
        if not self._session:
            self._session = utils.http_context.http_session()
        return self._session

    async def _run(self) -> None:
        """Main task managing WebSocket connection and sub-tasks."""
        tasks = []
        try:
            # Ensure tokenizer is reset for each attempt (including retries)
            self._sent_tokenizer_stream = tokenize.basic.SentenceTokenizer().stream()
            self._task_started = False # Reset task started flag

            session = self._ensure_session()
            url = self._opts.get_ws_url(f"/ws/v1/t2a_v2")
            headers = {API_KEY_HEADER: self._opts.api_key}

            logger.debug(f"[{self._request_id}] Attempting WebSocket connection to: {url}")
            self._ws = await asyncio.wait_for(
                session.ws_connect(url, headers=headers, heartbeat=30.0),
                timeout=self._conn_options.timeout
            )
            logger.info(f"[{self._request_id}] WebSocket connected.")

            # Wait for connected_success
            logger.debug(f"[{self._request_id}] Waiting for 'connected_success'...")
            async for msg in self._ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    data = json.loads(msg.data)
                    if data.get("event") == "connected_success":
                        logger.info(f"[{self._request_id}] Received connected_success.")
                        break
                    else:
                        # Handle potential errors during connection phase
                        err_msg = data.get("base_resp", {}).get("status_msg", "Unknown connection error")
                        logger.error(f"[{self._request_id}] Error during connection: {err_msg}")
                        raise APIConnectionError(f"Connection failed: {err_msg}")
                elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    err = self._ws.exception() or f"Connection closed unexpectedly (Type: {msg.type})"
                    logger.error(f"[{self._request_id}] WebSocket error/closed during connect phase: {err}")
                    raise APIConnectionError(str(err))
            
            # Send task_start first
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
            logger.debug(f"[{self._request_id}] Sending task_start message: {start_msg}")
            await self._ws.send_json(start_msg)

            # Now, wait for task_started response BEFORE starting other tasks
            logger.debug(f"[{self._request_id}] Waiting for 'task_started'...")
            async for msg in self._ws:
                 if msg.type == aiohttp.WSMsgType.TEXT:
                    data = json.loads(msg.data)
                    if data.get("event") == "task_started":
                        logger.info(f"[{self._request_id}] Received task_started.")
                        self._task_started = True
                        self._mark_started() # Mark stream started for metrics
                        break # Stop listening for task_started
                    elif data.get("event") == "error":
                        err_msg = data.get("message", "Unknown error starting task")
                        logger.error(f"[{self._request_id}] Error starting TTS task: {err_msg}")
                        raise APIStatusError(f"Failed to start TTS task: {err_msg}", status_code=400)
                 elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                     err = self._ws.exception() or f"Connection closed unexpectedly (Type: {msg.type}) while waiting for task_started"
                     logger.error(f"[{self._request_id}] WebSocket error/closed during task start: {err}")
                     raise APIConnectionError(str(err))

            # If we didn't get task_started, something went wrong (error already raised)
            if not self._task_started:
                 # This path should ideally not be reached due to exceptions above, but as a safeguard:
                 raise APIConnectionError("Failed to receive task_started confirmation.")

            # Create and run input, send, and receive tasks ONLY after task_started
            input_task = asyncio.create_task(self._input_task(), name=f"minimax_tts_input_{self._request_id}")
            send_task = asyncio.create_task(self._send_task(self._ws), name=f"minimax_tts_send_{self._request_id}")
            recv_task = asyncio.create_task(self._recv_task(self._ws), name=f"minimax_tts_recv_{self._request_id}")

            # Wait for tasks to complete or cancel if one fails
            tasks = [input_task, send_task, recv_task]
            await asyncio.gather(*tasks)

        except APIError as e: # Catch APIErrors specifically for retry logic in base class
            logger.error(f"[{self._request_id}] API Error in TTS stream: {e}", exc_info=False)
            # Ensure other tasks are cancelled if one fails with APIError
            for task in tasks:
                 if not task.done():
                      task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True) # Wait for cancellation
            raise # Re-raise for base class retry mechanism
        except Exception as e:
            logger.exception(f"[{self._request_id}] Unhandled exception in TTS synthesize stream _run:")
             # Ensure other tasks are cancelled on unhandled exceptions
            for task in tasks:
                 if not task.done():
                      task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True) # Wait for cancellation
            self._emit_error(APIConnectionError(f"Unhandled stream error: {e}"), recoverable=False)
            raise APIConnectionError(f"Unhandled stream error: {e}") from e
        finally:
            # Ensure ws is closed when recv_task exits for any reason
            if self._ws and not self._ws.closed:
                 try:
                     await self._ws.close()
                     logger.debug(f"[{self._request_id}] WebSocket closed in _recv_task finally.")
                 except Exception as close_e:
                     logger.warning(f"[{self._request_id}] Exception closing WebSocket in _recv_task finally: {close_e}", exc_info=False)
            
            logger.debug(f"[{self._request_id}] SynthesizeStream _run finished.")
            
    async def _input_task(self) -> None:
        """Reads text from the input channel and pushes it to the tokenizer."""
        logger.debug(f"[{self._request_id}] _input_task started, waiting for text...")
        try:
            async for data_item in self._input_ch:
                logger.debug(f"[{self._request_id}] _input_task received item: {type(data_item)}")
                if isinstance(data_item, self._FlushSentinel):
                    logger.debug(f"[{self._request_id}] Flushing tokenizer stream.")
                    self._sent_tokenizer_stream.flush()
                    continue
                
                logger.debug(f"[{self._request_id}] Pushing text to tokenizer: '{data_item[:50]}...'")
                self._sent_tokenizer_stream.push_text(data_item)

            logger.debug(f"[{self._request_id}] Input channel closed, ending tokenizer input.")
            self._sent_tokenizer_stream.end_input()
        except asyncio.CancelledError:
            logger.info(f"[{self._request_id}] Input task cancelled.")
            self._sent_tokenizer_stream.end_input()
            raise
        except Exception as e:
            logger.exception(f"[{self._request_id}] Error in _input_task:")
            self._sent_tokenizer_stream.end_input()
            raise

    async def _send_task(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        """Reads tokens from the tokenizer and sends them to the WebSocket."""
        try:
            # Now process tokens from the tokenizer immediately
            async for ev in self._sent_tokenizer_stream:
                token = ev.token
                if not token.strip(): # Avoid sending empty strings
                    continue
                    
                send_payload = {
                    "event": "task_continue",
                    "text": token
                }
                logger.debug(f"[{self._request_id}] Sending task_continue with token: '{token[:50]}...'")
                await ws.send_json(send_payload)
                logger.debug(f"[{self._request_id}] Successfully sent task_continue.")

            logger.debug(f"[{self._request_id}] Tokenizer stream finished.")
            
            # Send task_finish to server to signal end of text
            logger.info(f"[{self._request_id}] Sending task_finish event.")
            await ws.send_json({"event": "task_finish"})

        except Exception as e:
            logger.exception(f"[{self._request_id}] Error in _send_task: {e}")
            # Propagate error to potentially cancel other tasks
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
                # Wait indefinitely until task_started is confirmed by _send_task 
                # or until _send_task fails/completes
                if not self._task_started:
                    await asyncio.sleep(0.05) # Small sleep to prevent busy-waiting
                    # Check if ws is closed, indicating failure in _send_task before task_started
                    if ws.closed:
                       logger.warning(f"[{self._request_id}] WebSocket closed before task was started, exiting recv task.")
                       break
                    continue
                    
                logger.debug(f"[{self._request_id}] Waiting for message (timeout={self._conn_options.timeout}s)...")
                msg = await asyncio.wait_for(ws.receive(), timeout=self._conn_options.timeout)

                if msg.type == aiohttp.WSMsgType.TEXT:
                    logger.debug(f"[{self._request_id}] WebSocket TEXT received: {msg.data[:100]}...")
                    data = json.loads(msg.data)
                    api_error = data.get("event") == "error"
                    audio_present = "data" in data and "audio" in data["data"]
                    is_final = data.get("is_final", False)

                    if api_error:
                        error_msg = data.get('message', 'Unknown streaming error')
                        logger.error(f"[{self._request_id}] Minimax returned error: {error_msg}")
                        self._emit_error(APIStatusError(error_msg, status_code=400), recoverable=False)
                        # Decide if error is fatal, maybe break? depends on API behavior
                        # For now, continue listening in case more data/errors come

                    if audio_present:
                        audio_hex = data["data"]["audio"]
                        try:
                            # Decode the hex data first
                            audio_data = bytes.fromhex(audio_hex)
                            logger.debug(f"[{self._request_id}] Decoded {len(audio_data)} audio bytes.")
                            
                            # Feed the raw PCM bytes into the AudioByteStream
                            # and push the resulting frames using the emitter
                            for frame in audio_bstream.write(audio_data):
                                emitter.push(frame)
                                logger.debug(f"[{self._request_id}] Pushed frame of duration {frame.duration:.3f}s")
                                
                        except ValueError as hex_e:
                            logger.exception(f"[{self._request_id}] Failed to decode hex audio:")
                            self._emit_error(APIError(f"Failed to decode hex audio: {hex_e}"), recoverable=False)
                        except Exception as frame_e:
                             logger.exception(f"[{self._request_id}] Failed to process audio bytes or push frame:")
                             self._emit_error(APIError(f"Failed to process audio: {frame_e}"), recoverable=False)

                    if is_final:
                        logger.debug(f"[{self._request_id}] Received is_final=True. Flushing audio stream and emitter.")
                        # Flush any remaining buffered audio in AudioByteStream
                        for frame in audio_bstream.flush():
                             emitter.push(frame)
                             logger.debug(f"[{self._request_id}] Pushed flushed frame of duration {frame.duration:.3f}s")
                        # Mark the end of the segment for this text chunk
                        emitter.flush() 

                elif msg.type == aiohttp.WSMsgType.BINARY:
                    logger.warning(f"[{self._request_id}] Received unexpected BINARY message: {len(msg.data)} bytes")
                elif msg.type == aiohttp.WSMsgType.CLOSED or msg.type == aiohttp.WSMsgType.CLOSING:
                    logger.info(f"[{self._request_id}] WebSocket {msg.type.name} message received. Assuming clean completion.")
                    break # Connection closed, end the loop
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    err = ws.exception() or "Unknown WebSocket error"
                    logger.error(f"[{self._request_id}] WebSocket ERROR message received: {err}")
                    raise APIConnectionError(f"WebSocket error: {err}")
                else:
                    logger.warning(f"[{self._request_id}] Received unhandled WebSocket message type: {msg.type}")

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
                # Mark the absolute end of the stream if the task is ending cleanly
                # However, the emitter flush is usually tied to is_final=True from the API
                # self._emitter.flush() # Reconsider if this is needed here
            except Exception as flush_e:
                 logger.exception(f"[{self._request_id}] Error flushing audio buffer in finally block:")
                 
            logger.debug(f"[{self._request_id}] Receive task finished.")


def _to_minimax_options(opts: _TTSOptions) -> dict[str, Any]:
    """Convert TTSOptions to Minimax API options."""
    payload = {
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

    return payload