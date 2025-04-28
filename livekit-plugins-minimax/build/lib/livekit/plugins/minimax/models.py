from typing import Literal

TTSEncoding = Literal["pcm_s16le", "mp3"]

TTSModels = Literal["speech-01", "speech-01-hd", "speech-01-turbo", "speech-01-pro"]
TTSLanguages = Literal["zh", "en", "ja", "ko"]

TTSVoiceSpeed = Literal["0.5", "0.75", "1.0", "1.25", "1.5", "1.75", "2.0"]
TTSVoiceEmotion = Literal[
    "neutral",
    "happy",
    "angry",
    "sad",
    "fear",
    "disgust",
    "surprise"
]

# Common voice IDs
TTSVoiceMale = "male-qn-qingse"
TTSVoiceFemale = "female-shaoning"
TTSVoiceDefault = TTSVoiceFemale 