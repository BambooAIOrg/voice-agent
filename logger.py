import sys
from loguru import logger
from aliyun.log import LogClient, PutLogsRequest, LogItem
import os
import json
import logging
from contextvars import ContextVar
from queue import Queue, Empty
from threading import Thread
import time


# Aliyun Log Service Configuration
accessKeyId = os.environ.get("ALIYUN_LOG_ACCESSKEY_ID", "")
accessKey = os.environ.get("ALIYUN_LOG_ACCESSKEY_SECRET", "")
endpoint = os.environ.get("ALIYUN_LOG_ENDPOINT", "")
project_name = os.environ.get("ALIYUN_LOG_PROJECT", "")
logstore_name = os.environ.get("ALIYUN_LOG_STORE", "")

client = LogClient(endpoint, accessKeyId, accessKey)

import logging

# Set the log level for uvicorn and websockets
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
logging.getLogger("websockets.server").setLevel(logging.WARNING)
logging.getLogger("websockets.protocol").setLevel(logging.WARNING)
logging.getLogger("engineio.server").setLevel(logging.WARNING)
logging.getLogger("socketio.server").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)

# Create context variables
user_id_var = ContextVar('user_id', default='')
request_id_var = ContextVar('request_id', default='')

class SLSHandler:
    def __init__(self, client, project, logstore):
        self.client = client
        self.project = project
        self.logstore = logstore
        self.queue = Queue()
        self.batch_size = 100  # 批量发送的大小
        self.flush_interval = 5  # 定时刷新间隔(秒)
        self.running = True
        
        # 启动工作线程
        self.worker = Thread(target=self._worker_thread, daemon=True)
        self.worker.start()

    def emit(self, record):
        try:
            record_dict = json.loads(record)["record"]
            log_item = LogItem()
            log_item.set_time(int(record_dict["time"]["timestamp"]))
            
            user_id = user_id_var.get()
            request_id = request_id_var.get()
            
            # 构建日志项
            log_item.set_contents([
                ("level", record_dict["level"]["name"]),
                ("logger", record_dict["name"]),
                ("message", record_dict["message"]),
                ("env", os.environ.get("ENV", "")),
                ("user_id", str(user_id)),
                ("request_id", str(request_id)),
            ])
            
            # 将日志放入队列
            self.queue.put(log_item)
            
        except Exception as e:
            print(f"Failed to process log: {e}", file=sys.stderr)

    def _worker_thread(self):
        batch = []
        last_flush = time.time()

        while self.running:
            try:
                # 尝试从队列获取一个日志项,最多等待1秒
                try:
                    log_item = self.queue.get(timeout=1)
                    batch.append(log_item)
                except Empty:
                    pass

                current_time = time.time()
                
                # 当批次达到大小或者超过刷新间隔时发送
                if (len(batch) >= self.batch_size or 
                    (batch and current_time - last_flush >= self.flush_interval)):
                    if batch:
                        request = PutLogsRequest(self.project, self.logstore, "", "", batch)
                        self.client.put_logs(request)
                        batch = []
                        last_flush = current_time

            except Exception as e:
                print(f"Failed to send logs to SLS: {e}", file=sys.stderr)
                time.sleep(1)  # 发生错误时等待一下再继续

    def close(self):
        """关闭处理器,确保所有日志都被发送"""
        self.running = False
        self.worker.join()
        
        # 发送剩余的日志
        while not self.queue.empty():
            batch = []
            while not self.queue.empty() and len(batch) < self.batch_size:
                batch.append(self.queue.get())
            if batch:
                try:
                    request = PutLogsRequest(self.project, self.logstore, "", "", batch)
                    self.client.put_logs(request)
                except Exception as e:
                    print(f"Failed to send final logs to SLS: {e}", file=sys.stderr)


def setup_logger():
    # Remove default handlers
    logger.remove()

    # Configure log format
    log_format = "{time:YYYY-MM-DD HH:mm:ss} - {name} - {level} - {file}:{line} - {message}"

    print(f"ENV: {os.environ.get('ENV')}")
    if os.environ.get('ENV') == 'dev':
        # Output to console
        logger.add(sys.stdout, format=log_format, level="INFO", enqueue=False)
        # Output to file
        logger.add("logs/app.log", format=log_format, level="INFO", rotation="1 day", retention="7 days", compression="zip")
    else:
        # Add SLS handler
        sls_handler = SLSHandler(client, project_name, logstore_name)
        logger.add(
            sls_handler.emit, 
            format=log_format, 
            level="INFO", 
            enqueue=False, 
            serialize=True
        )

    return logger


# Global logger instance
app_logger = setup_logger()

def get_logger(name):
    return logger.bind(name=name)
