import sys
from loguru import logger
import os
import logging

# Set the log level for uvicorn and websockets
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
logging.getLogger("websockets.server").setLevel(logging.WARNING)
logging.getLogger("websockets.protocol").setLevel(logging.WARNING)
logging.getLogger("engineio.server").setLevel(logging.WARNING)
logging.getLogger("socketio.server").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)
logging.getLogger("livekit.plugins.cartesia").setLevel(logging.WARNING)

def setup_logger():
    # Remove default handlers
    logger.remove()

    # Configure log format
    log_format = "{time:YYYY-MM-DD HH:mm:ss} - {name} - {level} - {file}:{line} - {message}"

    print(f"ENV: {os.environ.get('ENV')}")
    if os.environ.get('ENV') == 'dev':
        logger.add(sys.stdout, format=log_format, level="INFO", enqueue=False)
        # Output to file
        logger.add("logs/app.log", format=log_format, level="INFO", rotation="1 day", retention="7 days", compression="zip")

    return logger

# Global logger instance
app_logger = setup_logger()

def get_logger(name):
    return logger.bind(name=name)
