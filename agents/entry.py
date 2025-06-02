import json
from livekit.agents import JobContext
from bamboo_shared.logger import get_logger

logger = get_logger(__name__)

async def entrypoint(ctx: JobContext):
    """Main entrypoint that routes to different agents based on metadata.type"""
    await ctx.connect()

    metadata = ctx.room.metadata
    logger.info(f"metadata: {metadata}")
    if not metadata:
        logger.error("No metadata found in room")
        ctx.shutdown()
        return
    
    try:
        metadata = json.loads(metadata)
    except json.JSONDecodeError:
        logger.error("Invalid metadata format")
        ctx.shutdown()
        return

    # Route based on metadata.type
    room_type = metadata.get("room_type", "").lower()
    logger.info(f"Routing to agent type: {room_type}")

    if room_type == "vocabulary":
        # Import and call vocab entrypoint
        from agents.vocab import vocab_entrypoint
        await vocab_entrypoint(ctx, metadata)
    
    # Add more agent types here as you develop them
    elif room_type == "onboarding":
        from agents.onboarding import onboarding_entrypoint
        await onboarding_entrypoint(ctx, metadata)
    # elif agent_type == "grammar":
    #     from agents.grammar import grammar_entrypoint
    #     await grammar_entrypoint(ctx, metadata)
    
    else:
        logger.error(f"Unknown room type: {room_type}")
        ctx.shutdown()
        return