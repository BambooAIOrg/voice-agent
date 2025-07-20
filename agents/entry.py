import json
from livekit.agents import JobContext
from bamboo_shared.logger import get_logger

logger = get_logger(__name__)


class AgentRoutingError(Exception):
    """Base exception for agent routing errors"""
    pass


class InvalidMetadataError(AgentRoutingError):
    """Raised when metadata is invalid or missing required fields"""
    pass


class UnsupportedRoomTypeError(AgentRoutingError):
    """Raised when room type is not supported"""
    pass

def _validate_metadata(metadata_dict: dict) -> None:
    """Validate metadata contains required fields"""
    required_fields = ["room_type"]
    missing_fields = [field for field in required_fields if field not in metadata_dict]
    
    if missing_fields:
        raise InvalidMetadataError(f"Missing required fields: {missing_fields}")
    

async def entrypoint(ctx: JobContext):
    """Main entrypoint that routes to different agents based on metadata.type"""
    try:
        metadata = json.loads(ctx.job.metadata)
        await ctx.connect()
        _validate_metadata(metadata)
        
        room_type = metadata["room_type"].lower()
        logger.info(f"Routing to agent type: {room_type}")
        
        if room_type == "vocabulary":
            from agents.vocab import vocab_entrypoint
            await vocab_entrypoint(ctx, metadata)
        
        elif room_type == "onboarding":
            from agents.onboarding import onboarding_entrypoint
            await onboarding_entrypoint(ctx, metadata)
        
        elif room_type == "official_website":
            from agents.official_website import official_website_entrypoint
            await official_website_entrypoint(ctx, metadata)
        else:
            raise UnsupportedRoomTypeError(f"Unsupported room type: {room_type}")
    
    except (InvalidMetadataError, UnsupportedRoomTypeError) as e:
        logger.error(f"Agent routing error: {e}")
        ctx.shutdown()
        return
    
    except Exception as e:
        logger.error(f"Unexpected error in agent routing: {e}")
        ctx.shutdown()
        return