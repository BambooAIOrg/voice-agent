from __future__ import annotations

import asyncio
import dataclasses
import json
import io
import wave
from dataclasses import dataclass
from typing import Optional, List

import nls
from livekit.agents import stt, utils
from livekit.agents.utils import AudioBuffer, merge_frames
import numpy as np
from scipy import signal
from livekit.agents.log import logger
from livekit import rtc
from livekit.agents.types import APIConnectOptions
import time

# Use local token helper
from .ali_token import ali_token

@dataclass
class STTOptions:
    """Ali Cloud STT configuration options"""
    url: str
    appkey: str
    language: str
    enable_intermediate_result: bool
    enable_punctuation_prediction: bool
    enable_inverse_text_normalization: bool
    interim_results: bool
    sample_rate: int
    num_channels: int
    timeout: float

class STTError(Exception):
    """Base exception for Ali Cloud STT errors"""
    pass

class AliSTT(stt.STT):
    """Ali Cloud Speech-to-Text implementation."""

    def __init__(
        self,
        *,
        url: str = "wss://nls-gateway-cn-shanghai.aliyuncs.com/ws/v1",
        appkey: str = "uOEo4DusjYLg1AZo",
        language: str = "zh-CN",
        enable_intermediate_result: bool = False,
        enable_punctuation_prediction: bool = True,
        enable_inverse_text_normalization: bool = True,
        interim_results: bool = True,
        timeout: float = 30.0,
    ):
        super().__init__(
            capabilities=stt.STTCapabilities(
                streaming=True,
                interim_results=interim_results,
            )
        )

        
        self._opts = STTOptions(
            url=url,
            appkey=appkey,
            language=language,
            enable_intermediate_result=enable_intermediate_result,
            enable_punctuation_prediction=enable_punctuation_prediction,
            enable_inverse_text_normalization=enable_inverse_text_normalization,
            interim_results=interim_results,
            sample_rate=16000,
            num_channels=1,
            timeout=timeout,
        )

    async def _resample_audio(self, buffer: AudioBuffer) -> AudioBuffer:
        """Resample audio to 16kHz"""
        audio_data = np.frombuffer(buffer.data, dtype=np.int16) # type: ignore
        new_length = int(len(audio_data) * 16000 / buffer.sample_rate) # type: ignore
        # Ensure resampled is a numpy array
        resampled = np.array(signal.resample(audio_data, new_length))
        
        return merge_frames([
            rtc.AudioFrame(
                data=resampled.astype(np.int16).tobytes(),
                sample_rate=16000,
                num_channels=buffer.num_channels, # type: ignore
                samples_per_channel=new_length // buffer.num_channels # type: ignore
            )
        ])

    async def _recognize_impl(
        self, buffer: AudioBuffer, *, language: str | None = None
    ) -> stt.SpeechEvent:
        raise NotImplementedError("This STT implementation only supports streaming recognition. Please use the stream() method instead")

    def stream(self, *, language: str | None = None) -> SpeechStream:
        logger.info('stream stt')
        """Create a streaming recognition session"""
        config = dataclasses.replace(self._opts)
        if language:
            config.language = language
        return SpeechStream(config, stt=self)

class SpeechStream(stt.SpeechStream):
    """Streaming speech recognition implementation"""
    
    def __init__(self, opts: STTOptions, stt: AliSTT, max_retry: int = 32) -> None:
        super().__init__(stt=stt, conn_options=APIConnectOptions())
        self._opts = opts
        self._transcriber = None
        self._is_running = False
        self._speaking = False
        self._max_retry = max_retry
    
    @utils.log_exceptions(logger=logger)
    async def _main_task(self) -> None:
        await self._run(self._max_retry)

    async def _run_transcriber(self) -> None:
        try:
            token = ali_token.get_token()
            self._transcriber = nls.NlsSpeechTranscriber(
                url=self._opts.url,
                token=token,
                appkey=self._opts.appkey,
                on_start=self._on_start,
                on_sentence_end=self._on_sentence_end,
                on_result_changed=self._on_result_changed,
                on_completed=self._on_completed,
                on_error=self._on_error,
                on_close=self._on_close
            )
            
            self._transcriber.start(
                aformat="pcm",
                sample_rate=self._opts.sample_rate,
                enable_intermediate_result=self._opts.enable_intermediate_result,
                enable_punctuation_prediction=self._opts.enable_punctuation_prediction,
                enable_inverse_text_normalization=self._opts.enable_inverse_text_normalization,
            )
            
            self._is_running = True
            
            async for data in self._input_ch:
                if isinstance(data, self._FlushSentinel):
                    logger.debug("Received flush sentinel, stopping transcription")
                    break
                    
                if data.sample_rate != self._opts.sample_rate:
                    data = await self._resample_audio(data)
                    
                audio_data = np.frombuffer(data.data, dtype=np.int16) # type: ignore
                self._transcriber.send_audio(audio_data.tobytes())
                    
        except asyncio.CancelledError:
            logger.debug("Transcription task cancelled")
        except Exception as e:
            logger.error(f"Error in transcription: {e}")
            raise
        finally:
            self._is_running = False
            if self._transcriber:
                try:
                    self._transcriber.send_audio(None)
                    self._transcriber.stop()
                except Exception as e:
                    logger.error(f"Error stopping transcriber: {e}")
                self._transcriber = None

    async def _run(self, max_retry: int = 3) -> None:
        retry_count = 0
        while self._input_ch.qsize() or not self._input_ch.closed:
            try:
                await self._run_transcriber()
                # 如果正常退出，跳出重试循环
                break
            except Exception as e:
                retry_count += 1
                if retry_count >= max_retry:
                    logger.error(f"Max retries ({max_retry}) reached, stopping")
                    break
                    
                logger.warning(f"Connection failed, retrying in {retry_count}s (attempt {retry_count}/{max_retry})")
                await asyncio.sleep(retry_count)  # 简单的退避策略

    def _on_start(self, message, *args):
        """转录开始回调"""
        logger.debug(f"Transcription started: {message}")
        if not self._speaking:
            self._speaking = True
            start_event = stt.SpeechEvent(type=stt.SpeechEventType.START_OF_SPEECH)
            self._event_ch.send_nowait(start_event)

    def _on_sentence_end(self, message, *args):
        """句子结束回调 - 只发送最终转写结果"""
        try:
            data = json.loads(message)
            if text := data.get("payload", {}).get("result"):
                # 只发送最终转写结果
                event = stt.SpeechEvent(
                    type=stt.SpeechEventType.FINAL_TRANSCRIPT,
                    alternatives=[
                        stt.SpeechData(
                            text=text,
                            language=self._opts.language,
                            confidence=1.0,
                        )
                    ],
                )
                self._event_ch.send_nowait(event)
        except Exception as e:
            logger.error(f"Error in sentence end handler: {e}")

    def _on_completed(self, message, *args):
        """转录完成回调 - 发送结束事件"""
        logger.debug(f"Transcription completed: {message}")
        if self._speaking:
            self._speaking = False
            end_event = stt.SpeechEvent(type=stt.SpeechEventType.END_OF_SPEECH)
            self._event_ch.send_nowait(end_event)

    def _on_result_changed(self, message, *args):
        """中间结果回调"""
        try:
            data = json.loads(message)
            if text := data.get("payload", {}).get("result"):
                event = stt.SpeechEvent(
                    type=stt.SpeechEventType.INTERIM_TRANSCRIPT,
                    alternatives=[
                        stt.SpeechData(
                            text=text,
                            language=self._opts.language,
                            confidence=1.0,
                        )
                    ],
                )
                self._event_ch.send_nowait(event)
        except Exception as e:
            logger.error(f"Error in result changed handler: {e}")

    def _on_error(self, message, *args):
        """转录错误回调"""
        logger.error(f"Transcription error: {message}")

    def _on_close(self, *args):
        """转录关闭回调"""
        logger.debug("Transcription closed")

    async def _resample_audio(self, buffer: AudioBuffer) -> AudioBuffer:
        """Resample audio to target sample rate"""
        audio_data = np.frombuffer(buffer.data, dtype=np.int16) # type: ignore
        new_length = int(len(audio_data) * self._opts.sample_rate / buffer.sample_rate) # type: ignore
        # Ensure resampled is a numpy array
        resampled = np.array(signal.resample(audio_data, new_length))
        
        return merge_frames([
            rtc.AudioFrame(
                data=resampled.astype(np.int16).tobytes(),
                sample_rate=self._opts.sample_rate,
                num_channels=buffer.num_channels, # type: ignore
                samples_per_channel=new_length // buffer.num_channels # type: ignore
            )
        ])