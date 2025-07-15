# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

### Environment Setup
```bash
# Install dependencies with Poetry
poetry install

# Run the agent in development mode
poetry run python main.py dev

# Alternative with Task runner
task install  # Bootstrap development environment
task dev     # Run in development mode
```

### Running the Application
```bash
# Main command to start the voice agent
poetry run python main.py dev

# The agent expects room metadata with:
# - room_type: "vocabulary" or "onboarding"
# - user_id: integer
# - chat_id: string
# - word_id: integer (for vocabulary agents)
```

### Environment Configuration
- Copy `.env.example` to `.env.local` and configure required API keys
- Required environment variables:
  - `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`
  - `OPENAI_API_KEY`
  - `ALIYUN_ACCESS_KEY_ID`, `ALIYUN_ACCESS_KEY_SECRET`, `ALIYUN_APP_KEY`
  - `MINIMAX_GROUP_ID`, `MINIMAX_API_KEY`
  - `ENV` (environment identifier for request filtering)

## Code Architecture

### Agent System Architecture
The system uses a multi-agent architecture built on LiveKit Agents framework:

1. **Main Entry Point** (`main.py`): Handles LiveKit worker initialization, service registration with Nacos, and request routing
2. **Agent Router** (`agents/entry.py`): Routes requests to appropriate agent types based on `room_type` metadata
3. **Vocabulary Learning Flow** (`agents/vocab/entry.py`): Implements sequential learning phases for vocabulary acquisition

### Vocabulary Agent Flow
The vocabulary learning system follows these phases (defined in `VocabularyPhase` enum):
- `ANALYSIS_ROUTE` → `RouteAnalysisAgent`
- `WORD_CREATION_LOGIC` → `WordCreationAnalysisAgent`  
- `SYNONYM_DIFFERENTIATION` → `SynonymAgent`
- `CO_OCCURRENCE` → `CooccurrenceAgent`
- `QUESTION_ANSWER` → `SentencePracticeAgent`

### Context Management
- `AgentContext` (in `agents/vocab/context.py`): Manages user state, word data, learning progress, and database interactions
- Initializes user info, chat context, word references, and web content asynchronously
- Handles progression between learning phases and words

### Plugin System
- **STT**: Aliyun Speech-to-Text (`plugins/aliyun/stt.py`)
- **TTS**: Minimax Text-to-Speech (`plugins/minimax/tts.py`)
- **Tokenizer**: Mixed language tokenization (`plugins/tokenizer/mixedLanguangeTokenizer.py`)

### Database Integration
- Uses `bamboo-shared` library for database models and repositories
- Repositories handle: Users, Vocabulary, Chats, Chat References, Web Content
- Async database operations with SQLAlchemy

### Key Components
- **Agent Sessions**: Each agent runs in a LiveKit session with configured LLM, STT, and TTS
- **Message Service**: Handles chat context and communication timing
- **Usage Metrics**: Collects and logs usage statistics for monitoring
- **Nacos Integration**: Service discovery and registration

### Agent Development Pattern
When creating new agents:
1. Extend base agent class with context parameter
2. Implement in appropriate phase-specific file under `agents/vocab/agents/`
3. Register in the phase routing switch in `vocab_entrypoint`
4. Each agent receives `AgentContext` with user state and word data

### Development Notes
- All agents communicate primarily in Chinese with English vocabulary examples
- Context switching between agents maintains conversation continuity
- Agents handle returning users with warm greetings based on last communication time
- The system supports progression through daily word learning tasks