import os
import json
from aliyunsdkcore.client import AcsClient
from aliyunsdkcore.request import CommonRequest
from datetime import datetime, timedelta
# Use the standard livekit agents logger
from livekit.agents.log import logger

# logger = get_logger(__name__) # Removed local logger usage

class AliToken:
    def __init__(self):
        self.access_key_id = os.getenv('ALIYUN_COMMON_ID')
        self.access_key_secret = os.getenv('ALIYUN_COMMON_SECRET')
        self.client = AcsClient(
            self.access_key_id,
            self.access_key_secret,
            "cn-shanghai"
        )
        self.token = None
        self.expiry_time = None

    def get_token(self):
        """Get a valid token, refreshing if necessary"""
        if not self._is_token_valid():
            self._refresh_token()
        return self.token

    def _is_token_valid(self):
        """Check if current token is valid"""
        if not self.token or not self.expiry_time:
            return False
        # Consider token expired if less than 5 minutes remaining
        return datetime.now() + timedelta(minutes=5) < self.expiry_time

    def _refresh_token(self):
        """Refresh the access token"""
        try:
            # Validate credentials first
            if not self.access_key_id or not self.access_key_secret:
                raise Exception("Missing Aliyun credentials")

            request = CommonRequest()
            request.set_method('POST')
            request.set_domain('nls-meta.cn-shanghai.aliyuncs.com')
            request.set_version('2019-02-28')
            request.set_action_name('CreateToken')

            response = self.client.do_action_with_exception(request)
            data = json.loads(response)
            
            # Log the response for debugging
            logger.debug(f"Aliyun API response: {data}")

            if not isinstance(data, dict):
                raise Exception(f"Unexpected response type: {type(data)}")
            
            if 'Token' not in data:
                raise Exception(f"Missing 'Token' in response. Response: {data}")
            
            if 'Id' not in data.get('Token', {}):
                raise Exception(f"Missing 'Id' in Token. Token data: {data.get('Token')}")

            self.token = data['Token']['Id']
            self.expiry_time = datetime.fromtimestamp(int(data['Token']['ExpireTime']))
            logger.info(f"Token refreshed, expires at {self.expiry_time}")

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse API response: {response}")
            raise Exception(f"Invalid JSON response from Aliyun API: {str(e)}")
        except Exception as e:
            logger.error(f"Error refreshing Ali token: {str(e)}")
            raise

# Singleton instance
ali_token = AliToken() 