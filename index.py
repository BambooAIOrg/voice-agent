import json
import logging
import os
import sys
from livekit.agents import cli
# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("vocab-agent-fc")

# Add the current directory to sys.path to ensure modules can be imported
sys.path.append(os.getcwd())

# Import directly from main
from main import WorkerOptions, entrypoint, prewarm, request_fnc
from dotenv import load_dotenv

# Load environment variables
load_dotenv(dotenv_path=".env.local")

def handler(event, context):
    """
    Alibaba Cloud Function Compute的入口点。
    
    这个handler函数会启动LiveKit Agents的worker应用，处理来自LiveKit服务的请求。
    函数计算作为长期运行的服务，会等待并处理LiveKit的请求。
    
    Args:
        event: 函数计算事件数据
        context: 函数计算上下文对象
    
    Returns:
        处理结果
    """
    try:
        # 记录事件信息，可以帮助调试
        logger.info(f"Function Compute event received: {event}")
        
        # 直接运行agent worker应用
        # worker会监听并处理来自LiveKit的请求
        cli.run_app(WorkerOptions(
            entrypoint_fnc=entrypoint,
            prewarm_fnc=prewarm,
            request_fnc=request_fnc
        ))
        
        # 注意：一般情况下，run_app是阻塞的，不会执行到这里
        # 但如果因为某些原因返回了，我们提供一个成功响应
        return {
            'statusCode': 200,
            'body': json.dumps({
                'status': 'success',
                'message': 'Agent service started'
            })
        }
    except Exception as e:
        logger.exception(f"Error starting agent service: {str(e)}")
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': f'Failed to start agent service: {str(e)}'
            })
        } 