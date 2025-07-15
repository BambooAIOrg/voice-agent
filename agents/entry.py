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
    required_fields = ["room_type", "user_id"]
    missing_fields = [field for field in required_fields if field not in metadata_dict]
    
    if missing_fields:
        raise InvalidMetadataError(f"Missing required fields: {missing_fields}")
    

async def entrypoint(ctx: JobContext):
    """Main entrypoint that routes to different agents based on metadata.type"""
    try:
        await ctx.connect()
        
        metadata_str = ctx.room.metadata
        logger.info(f"Processing request with metadata length: {len(metadata_str) if metadata_str else 0}")
        
        if not metadata_str:
            raise InvalidMetadataError("No metadata found in room")
        
        try:
            metadata = json.loads(metadata_str)
            logger.info(f"Metadata: {metadata}")
        except json.JSONDecodeError as e:
            raise InvalidMetadataError(f"Invalid JSON format: {e}")
        
        # Validate metadata structure
        _validate_metadata(metadata)
        
        # Route based on metadata.room_type
        room_type = metadata["room_type"].lower()
        logger.info(f"Routing to agent type: {room_type}")
        
        if room_type == "vocabulary":
            # Additional validation for vocabulary agents
            if "word_id" not in metadata:
                raise InvalidMetadataError("word_id is required for vocabulary agents")
            
            from agents.vocab import vocab_entrypoint
            await vocab_entrypoint(ctx, metadata)
        
        elif room_type == "onboarding":
            from agents.onboarding import onboarding_entrypoint
            await onboarding_entrypoint(ctx, metadata)
        
        # elif room_type == "grammar":
        #     from agents.grammar import grammar_entrypoint
        #     await grammar_entrypoint(ctx, metadata)
        
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