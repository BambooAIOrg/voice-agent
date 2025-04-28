# Copyright 2023 LiveKit, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import annotations

import asyncio
import base64
import json
import os
import tempfile
import weakref
from dataclasses import dataclass
from typing import Any, Literal, Optional, Union

import aiohttp

from livekit.agents import (
    APIConnectionError,
    APIConnectOptions,
    APIStatusError,
    APITimeoutError,
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
    audio_format: AudioFormatType
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
        audio_format: AudioFormatType = "mp3",
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
            audio_format (str, optional): Format of generated sound. Options: "mp3", "pcm", "flac". Defaults to "mp3".
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
            audio_format=audio_format,
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
    """A stream that processes text incrementally as it arrives using WebSocket."""

    def __init__(
        self,
        *,
        tts: TTS,
        opts: _TTSOptions,
        session: aiohttp.ClientSession,
    ):
        super().__init__(tts=tts)
        self._tts = tts
        self._opts = opts
        self._session = session
        self._task: Optional[asyncio.Task] = None
        self._input_queue = asyncio.Queue[str]()
        self._stopping = False
        self._ws = None
        self._audio_bytes = bytearray()
        self._audio_event = asyncio.Event()
        self._completion_event = asyncio.Event()
        self._error_msg: Optional[str] = None

    async def _run(self) -> None:
        try:
            # Connect to WebSocket
            url = self._opts.get_ws_url(f"/ws/v1/t2a_v2")
            headers = {API_KEY_HEADER: self._opts.api_key}
            
            self._ws = await aiohttp.ClientSession().ws_connect(
                url,
                headers=headers,
                heartbeat=30.0
            )
            
            # Wait for connected_success
            async for msg in self._ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    data = json.loads(msg.data)
                    if data.get("event") == "connected_success":
                        logger.info("WebSocket connection established")
                        break
                elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    raise APIConnectionError("WebSocket connection failed")
            
            # Send task_start
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
                    "format": self._opts.audio_format,
                    "channel": self._opts.channels
                }
            }
            
            await self._ws.send_json(start_msg)
            
            # Process task_started response
            async for msg in self._ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    data = json.loads(msg.data)
                    if data.get("event") == "task_started":
                        logger.info("TTS task started")
                        break
                    elif data.get("event") == "error":
                        raise APIStatusError(
                            f"Failed to start TTS task: {data.get('message', 'Unknown error')}",
                            status_code=400,
                        )
                elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    raise APIConnectionError("WebSocket connection closed unexpectedly")
            
            # Process input queue
            while not self._stopping:
                try:
                    # Wait for input with timeout
                    text = await asyncio.wait_for(self._input_queue.get(), timeout=0.1)
                    
                    if text:
                        # Send continue request
                        await self._ws.send_json({
                            "event": "task_continue",
                            "text": text
                        })
                        
                        # Collect audio chunks
                        while True:
                            msg = await self._ws.receive()
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                data = json.loads(msg.data)
                                if "data" in data and "audio" in data["data"]:
                                    # Decode hex audio data
                                    audio_hex = data["data"]["audio"]
                                    audio_data = bytes.fromhex(audio_hex)
                                    
                                    # Add to buffer
                                    self._audio_bytes.extend(audio_data)
                                    self._audio_event.set()
                                
                                if data.get("is_final"):
                                    break
                            elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                                raise APIConnectionError("WebSocket connection closed unexpectedly")
                    
                    # Mark the task as done
                    self._input_queue.task_done()
                except asyncio.TimeoutError:
                    # Timeout just means no input is available yet
                    continue
                except asyncio.CancelledError:
                    # Send task_finish if possible
                    if self._ws and not self._ws.closed:
                        await self._ws.send_json({"event": "task_finish"})
                    return
        except Exception as e:
            logger.error(f"Error in TTS synthesize stream: {e}")
            self._error_msg = str(e)
        finally:
            # Close WebSocket connection
            if self._ws and not self._ws.closed:
                try:
                    await self._ws.send_json({"event": "task_finish"})
                    await self._ws.close()
                except:
                    pass
            
            # Mark completion
            self._completion_event.set()

    async def read(self, n: int = -1) -> bytes:
        """Read audio data from the stream."""
        if self._error_msg:
            raise RuntimeError(self._error_msg)

        # Ensure stream is started
        if self._task is None:
            await self.start()

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

    async def start(self) -> None:
        """Start the synthesize stream."""
        if self._task is None:
            self._task = asyncio.create_task(self._run())

    async def write(self, text: str) -> None:
        """
        Write text to the stream for synthesis.

        Args:
            text: The text to synthesize.
        """
        if self._task is None:
            await self.start()

        await self._input_queue.put(text)

    async def aclose(self) -> None:
        """Close the stream and cancel any running tasks."""
        self._stopping = True
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            finally:
                self._task = None


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