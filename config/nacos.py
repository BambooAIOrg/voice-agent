import yaml
import nacos
import json
import socket
from functools import lru_cache
from pathlib import Path
from typing import Dict, Any, Optional, Callable

from logger import get_logger

logger = get_logger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent

def get_host_ip():
    """Get the host IP address"""
    try:
        return socket.gethostbyname(socket.gethostname())
    except Exception as e:
        logger.error(f"Failed to get host IP: {e}")
        return "127.0.0.1"

class NacosClient:
    def __init__(self, config_path: str = "config.yaml"):
        self.config_path = BASE_DIR / config_path
        self._config = self._load_yaml()
        self._nacos_client = self._setup_nacos_client()
        self._config_watchers = {}

    def _load_yaml(self):
        if not self.config_path.exists():
            return {}
        
        try:
            with open(self.config_path, 'r') as f:
                raw_content = f.read()
                parsed_data = yaml.safe_load(raw_content) 
                return parsed_data

        except yaml.YAMLError as e:
            logger.error(f"[LOAD_YAML_DEBUG] Error loading YAML configuration from {self.config_path}: {e}")
            return {}
        except Exception as e:
            logger.error(f"[LOAD_YAML_DEBUG] Unexpected error reading {self.config_path}: {e}")
            return {}

    def _setup_nacos_client(self):
        nacos_config = self._config.get('nacos', {})
        if not nacos_config.get('enabled', False):
            logger.info("Nacos client is disabled in configuration.")
            return None

        server_addresses = nacos_config.get('server_addresses')
        namespace = nacos_config.get('namespace')
        username = nacos_config.get('username')
        password = nacos_config.get('password')

        if not server_addresses or not namespace:
            logger.warning("Nacos server_addresses or namespace not configured. Nacos client disabled.")
            return None

        try:
            client = nacos.NacosClient(
                server_addresses=server_addresses,
                namespace=namespace,
                username=username,
                password=password
            )
            logger.info(f"Nacos client initialized for namespace: {namespace}")
            return client
        except Exception as e:
            logger.error(f"Failed to initialize Nacos client: {e}")
            return None

    def _register_service(self, client, service_name, service_port=8000, service_group="DEFAULT_GROUP"):
        """Register this service to Nacos service discovery"""
        try:
            service_ip = get_host_ip()
            client.add_naming_instance(
                service_name=service_name,
                ip=service_ip,
                port=service_port,
                group_name=service_group
            )
            logger.info(f"Registered service {service_name} at {service_ip}:{service_port}")
        except Exception as e:
            logger.error(f"Failed to register service with Nacos: {e}")

    async def send_heartbeat(self, service_name, service_port=8000):
        """Send heartbeat for service health check"""
        if not self._nacos_client:
            return

        try:
            service_ip = get_host_ip()
            self._nacos_client.send_heartbeat(
                service_name=service_name,
                ip=service_ip,
                port=service_port
            )
            logger.debug(f"Sent heartbeat for {service_name} at {service_ip}:{service_port}")
        except Exception as e:
            logger.error(f"Failed to send heartbeat to Nacos: {e}")

    def add_config_watcher(self, data_id: str, group: str, callback: Callable):
        """
        Add a watcher for a Nacos configuration with callback 
        when the configuration changes
        """
        if not self._nacos_client:
            logger.warning("Cannot add watcher: Nacos client is not initialized")
            return False
            
        try:
            # Store watcher info to avoid garbage collection
            watcher_key = f"{data_id}:{group}"
            self._config_watchers[watcher_key] = callback
            
            # Register the callback wrapper that processes raw content
            def config_change_callback(args):
                try:
                    raw_content = args.get('raw_content')
                    if not raw_content:
                        logger.warning(f"Received empty content from Nacos for {data_id}")
                        return
                        
                    # Execute the user's callback with the content
                    callback(raw_content)
                    logger.info(f"Config updated for {data_id} in group {group}")
                except Exception as e:
                    logger.error(f"Error in config watcher callback for {data_id}: {e}")
            
            self._nacos_client.add_config_watcher(
                data_id=data_id,
                group=group,
                cb=config_change_callback
            )
            return True
            
        except Exception as e:
            logger.error(f"Failed to add config watcher for {data_id}: {e}")
            return False

    def get_config_value(self, key: str, default=None):
        """
        Retrieves a configuration value.
        For keys matching Nacos data_id format (e.g., app.impersonation.whitelist),
        it attempts to fetch from Nacos first if enabled.
        Otherwise, it falls back to the YAML configuration.

        Example: get_config_value("app.impersonation.whitelist")
                 get_config_value("nacos.server_addresses")
        """
        keys = key.split('.')
        
        # Try fetching from Nacos if it's enabled and looks like a Nacos config item
        nacos_config_info = self._get_nested_value(self._config, keys)
        
        if self._nacos_client and isinstance(nacos_config_info, dict) and 'data_id' in nacos_config_info and 'group' in nacos_config_info:
            data_id = nacos_config_info['data_id']
            group = nacos_config_info['group']
            config_type = nacos_config_info.get('type', 'JSON')  
            
            try:
                nacos_value_str = self._nacos_client.get_config(data_id, group)
                if nacos_value_str:
                    # Parse based on the specified type
                    if config_type.upper() == "JSON":
                        try:
                            return json.loads(nacos_value_str)
                        except json.JSONDecodeError as e:
                            logger.error(f"Failed to parse JSON from Nacos for {data_id}: {e}")
                    elif config_type.upper() == "YAML":
                        try:
                            return yaml.safe_load(nacos_value_str)
                        except yaml.YAMLError as e:
                            logger.error(f"Failed to parse YAML from Nacos for {data_id}: {e}")
                    else:
                        # For TEXT, Properties, HTML, XML, etc. return as string
                        return nacos_value_str
                else:
                     logger.warning(f"Received empty content for Nacos config: data_id={data_id}, group={group}")

            except Exception as e:
                logger.error(f"Failed to fetch config from Nacos (data_id={data_id}, group={group}): {e}")
            
            # Fallback to default content from YAML if defined
            if 'default_content' in nacos_config_info:
                 logger.warning(f"Falling back to default_content for {key}")
                 default_content = nacos_config_info['default_content']
                 
                 # If default content is a string that needs parsing
                 if isinstance(default_content, str):
                     if config_type.upper() == "JSON":
                         try:
                             return json.loads(default_content)
                         except json.JSONDecodeError:
                             return default_content
                     elif config_type.upper() == "YAML":
                         try:
                             return yaml.safe_load(default_content)
                         except yaml.YAMLError:
                             return default_content
                 
                 return default_content

        return default

    def get_raw_config(self, data_id: str, group: str) -> Optional[str]:
        """
        Get raw configuration content from Nacos without any parsing
        """
        if not self._nacos_client:
            return None
            
        try:
            return self._nacos_client.get_config(data_id=data_id, group=group, no_snapshot=True)
        except Exception as e:
            logger.error(f"Failed to get raw config from Nacos (data_id={data_id}, group={group}): {e}")
            return None

    def _get_nested_value(self, config_dict, keys):
        value = config_dict
        try:
            for k in keys:
                value = value[k]
            return value
        except (KeyError, TypeError):
            return None


# Singleton instance - Define before ConfigValue uses it
@lru_cache()
def get_nacos_client() -> NacosClient:
    return NacosClient()


class ConfigValue:
    """A descriptor to dynamically fetch configuration values.""" 
    def __init__(self, key: str, default=None):
        self.key = key
        self.default = default

    def __get__(self, instance, owner):
        if instance is None:
            # Accessed via class, return the descriptor itself
            return self
        
        # Accessed via instance
        nacos_client = get_nacos_client()
        value = nacos_client.get_config_value(self.key, default=self.default)
        
        return value # Return the raw value fetched

def get_config_value(key: str, default=None):
    nacos_client = get_nacos_client()
    return nacos_client.get_config_value(key, default=default)

def register_config_watcher(data_id: str, group: str, callback: Callable) -> bool:
    """Helper function to register a configuration watcher"""
    nacos_client = get_nacos_client()
    return nacos_client.add_config_watcher(data_id, group, callback)

def register_all_config_watchers(callback: Optional[Callable] = None) -> int:
    """
    Automatically register watchers for all Nacos configuration items defined in the config.
    
    Args:
        callback: Optional callback function to use for all configurations.
                 If None, a default callback that logs updates will be used.
    
    Returns:
        int: Number of watchers registered
    """
    nacos_client = get_nacos_client()
    registered = 0
    
    if not nacos_client._nacos_client:
        logger.warning("Cannot register watchers: Nacos client is not initialized")
        return 0
    
    # Default callback function if none provided
    def default_callback(content):
        try:
            if content.startswith('{'):
                # Try to parse as JSON to make log more readable
                config = json.loads(content)
                logger.info(f"Configuration updated: {list(config.keys() if isinstance(config, dict) else ['...'])}")
            else:
                # For non-JSON content, show a preview
                logger.info(f"Configuration updated: {content[:50]}...")
        except Exception:
            logger.info(f"Configuration updated: {content[:50]}...")
    
    cb = callback or default_callback
    
    def traverse_config(config, path=None):
        """Recursively traverse config and register watchers for Nacos items"""
        nonlocal registered
        path = path or []
        
        if isinstance(config, dict):
            # Check if this dict represents a Nacos config item
            if 'data_id' in config and 'group' in config:
                data_id = config['data_id']
                group = config['group']
                config_path = '.'.join(path) if path else "root"
                
                logger.info(f"Registering watcher for {config_path} (data_id={data_id}, group={group})")
                if register_config_watcher(data_id, group, cb):
                    registered += 1
            
            # Continue traversing child items
            for key, value in config.items():
                if isinstance(value, (dict, list)):
                    traverse_config(value, path + [key])
        
        elif isinstance(config, list):
            # Handle list items (though unlikely to contain Nacos configs)
            for i, item in enumerate(config):
                if isinstance(item, (dict, list)):
                    traverse_config(item, path + [f"[{i}]"])
    
    # Start traversal from the app section of the config
    app_config = nacos_client._config.get('app', {})
    traverse_config(app_config, ['app'])
    
    logger.info(f"Registered {registered} Nacos configuration watchers")
    return registered