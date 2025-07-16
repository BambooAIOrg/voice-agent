from dotenv import load_dotenv
from plugins.tokenizer.mixedLanguageTokenizer import install_mixed_language_tokenize
from bamboo_shared.nacos import get_nacos_client
from bamboo_shared.logger import get_logger
import os

load_dotenv(dotenv_path=".env.local")
logger = get_logger(__name__)
install_mixed_language_tokenize()

from collections import deque
import json
import os
import psutil

from livekit.agents import (
    JobProcess,
    WorkerOptions,
    cli,
)
from livekit.agents.job import JobRequest
from livekit.plugins import silero

from agents.entry import entrypoint



def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()


async def request_fnc(request: JobRequest):
    logger.info(f"ENV: {os.getenv('ENV')}")
    logger.info(f"Metadata: {request.job.metadata}")
    if not request.job.metadata:
        logger.warning("Rejecting request: No metadata provided")
        await request.reject()
        return

    try:
        metadata = json.loads(request.job.metadata)
    except json.JSONDecodeError as e:
        logger.error(f"Rejecting request: Invalid JSON metadata - {e}")
        await request.reject()
        return
    
    # Validate required fields
    required_fields = ["env", "room_type", "user_id"]
    missing_fields = [field for field in required_fields if field not in metadata]
    if missing_fields:
        logger.error(f"Rejecting request: Missing required fields - {missing_fields}")
        await request.reject()
        return
    
    if metadata.get("env") == os.getenv("ENV"):
        logger.info(f"Accepting request for room_type: {metadata.get('room_type')}, user_id: {metadata.get('user_id')}")
        await request.accept(attributes=metadata)
    else:
        logger.info(f"Rejecting request: Environment mismatch - expected {os.getenv('ENV')}, got {metadata.get('env')}")
        await request.reject()

def load_fnc(*args, window_size=120, interval=0.5):
    """
    custom load function, collect sliding average of one minute
    
    window_size=120: keep 120 samples, 0.5 second interval approximately one minute
    interval=0.5: sample interval 0.5 second
    """
    if not hasattr(load_fnc, "samples"):
        load_fnc.samples = deque(maxlen=window_size)
        load_fnc._initialized = False

    if not load_fnc._initialized:
        psutil.cpu_percent(interval=None)  # initialize, discard first sample
        load_fnc._initialized = True
        return 0.0

    value = psutil.cpu_percent(interval=interval) / 100.0
    load_fnc.samples.append(value)

    if len(load_fnc.samples) == 0:
        return 0.0
    
    load = sum(load_fnc.samples) / len(load_fnc.samples)
    
    # only print when load is high, reduce log volume
    if load > 0.5:
        logger.info(f"load: {load:.4f}, current: {value:.4f}, samples: {len(load_fnc.samples)}")
    
    return load

if __name__ == "__main__":
    # Register service with Nacos
    nacos_client_instance = get_nacos_client()
    service_name = nacos_client_instance._config.get('app', {}).get('service_name')
    logger.info(f"service_name: {service_name}")
    if nacos_client_instance._nacos_client and service_name:
        logger.info(f"Registering service {service_name} with Nacos")
        nacos_client_instance._register_service(
            nacos_client_instance._nacos_client,
            service_name,
            service_port=nacos_client_instance._config.get('app', {}).get('service_port', 8000)
        )
    
    cli.run_app(WorkerOptions(
        entrypoint_fnc=entrypoint,
        prewarm_fnc=prewarm,
        request_fnc=request_fnc,
        load_fnc=load_fnc,
        agent_name="vocab-agent",
    ))
