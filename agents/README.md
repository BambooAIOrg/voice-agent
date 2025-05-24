# Multi-Agent System Architecture

This directory contains the multi-agent system that routes different types of agents based on metadata.

## How it works

1. The main entrypoint in `entry.py` receives a request with metadata
2. Based on `metadata.type`, it routes to the appropriate agent type
3. Each agent type has its own subdirectory with its specific implementation

## Current Agent Types

### Vocabulary Learning Agent (`type: "vocab"`)
Location: `vocab/`

This agent helps students learn English vocabulary through multiple sub-agents:
- **GreetingAgent**: Welcomes the student and introduces the word
- **EtymologyAgent**: Explores the word's origin and roots
- **SynonymAgent**: Discusses synonyms and differences
- **CooccurrenceAgent**: Explains common word combinations
- **SentencePracticeAgent**: Provides practice scenarios

Usage in metadata:
```json
{
  "type": "vocab",
  "target_word": "extraordinary"
}
```

## Adding New Agent Types

To add a new agent type:

1. Create a new directory under `agents/` (e.g., `agents/grammar/`)
2. Create an entrypoint function in `agents/grammar/entry.py`:
   ```python
   async def grammar_entrypoint(ctx: JobContext, metadata: dict):
       # Your agent implementation
   ```
3. Export it in `agents/grammar/__init__.py`:
   ```python
   from .entry import grammar_entrypoint
   __all__ = ["grammar_entrypoint"]
   ```
4. Add the routing logic in `agents/entry.py`:
   ```python
   elif agent_type == "grammar":
       from agents.grammar import grammar_entrypoint
       await grammar_entrypoint(ctx, metadata)
   ```

## Metadata Structure

The metadata should always include a `type` field:
```json
{
  "type": "agent_type",
  "env": "production",
  // ... other agent-specific fields
}
``` 