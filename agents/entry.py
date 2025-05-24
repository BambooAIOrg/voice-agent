import json
from livekit.agents import JobContext
from logger import get_logger

logger = get_logger(__name__)

async def entrypoint(ctx: JobContext):
    """Main entrypoint that routes to different agents based on metadata.type"""
    await ctx.connect()

    metadata = ctx.room.metadata
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
    agent_type = metadata.get("type", "").lower()
    logger.info(f"Routing to agent type: {agent_type}")

    if agent_type == "vocab":
        # Import and call vocab entrypoint
        from agents.vocab import vocab_entrypoint
        await vocab_entrypoint(ctx, metadata)
    
    # Add more agent types here as you develop them
    elif agent_type == "onboarding":
        from agents.onboarding import onboarding_entrypoint
        await onboarding_entrypoint(ctx, metadata)
    # elif agent_type == "grammar":
    #     from agents.grammar import grammar_entrypoint
    #     await grammar_entrypoint(ctx, metadata)
    
    else:
        logger.error(f"Unknown agent type: {agent_type}")
        ctx.shutdown()
        return