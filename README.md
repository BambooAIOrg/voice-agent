# Vocab Agent

A multi-agent system using [LiveKit Agents](https://github.com/livekit/agents) designed as an interactive English vocabulary tutor for Chinese-speaking students.

## Overview

This project implements a sequence of specialized agents that guide a user through learning an English word. The agents handle different stages:

1.  **GreetingAgent:** Welcomes the student and introduces the target word.
2.  **EtymologyAgent:** Interactively explores the word's origins and roots.
3.  **SynonymAgent:** Discusses synonyms and nuances.
4.  **CooccurrenceAgent:** Explains common word pairings and usage patterns.
5.  **SentencePracticeAgent:** Provides scenarios for the student to practice using the word in sentences.

The agents primarily communicate instructions and explanations in **Chinese**, while using English for the target vocabulary and examples. It utilizes various services for LLM (OpenAI), STT (Aliyun), and TTS (Minimax).

## Project Structure

-   `main.py`: Main application entry point, defines the agent sequence and initializes the LiveKit Agent worker.
-   `models/`: Contains data structures (e.g., `WordLearningData`). (Further details depend on content).
-   `plugins/`: Contains custom plugin integrations, such as `aliyun/stt.py` and `minimax/tts.py`.
-   `logger.py`: Sets up custom logging for the application.
-   `pyproject.toml` / `poetry.lock`: Defines project dependencies managed by Poetry.
-   `.env.local`: Stores required API keys and configuration (copy from `.env.example`).
-   `build.sh` / `deploy.sh`: Scripts for building and deploying the agent (likely as a container).
-   `taskfile.yaml`: Defines tasks runnable with `task`.

## Setup

1.  **Clone the repository:**
    ```bash
    git clone <repository_url>
    cd vocab-agent
    ```

2.  **Install dependencies using Poetry:**
    Make sure you have [Poetry](https://python-poetry.org/docs/#installation) installed.
    ```bash
    poetry install
    ```

3.  **Set up environment variables:**
    Copy the example environment file and fill in the required credentials:
    ```bash
    cp .env.example .env.local
    # Edit .env.local with your API keys and LiveKit details
    ```
    You will likely need:
    *   `LIVEKIT_URL`
    *   `LIVEKIT_API_KEY`
    *   `LIVEKIT_API_SECRET`
    *   `OPENAI_API_KEY`
    *   Aliyun NLS credentials (`ALIYUN_ACCESS_KEY_ID`, `ALIYUN_ACCESS_KEY_SECRET`, `ALIYUN_APP_KEY`) - *Verify exact names needed from `plugins/aliyun/stt.py`*
    *   Minimax credentials (`MINIMAX_GROUP_ID`, `MINIMAX_API_KEY`) - *Verify exact names needed from `plugins/minimax/tts.py`*
    *   *(Add any other required variables, e.g., for logging, database, Azure)*

## Running the Agent

Activate the virtual environment managed by Poetry and run the main script:

```bash
poetry run python main.py dev
```

This will start the LiveKit agent worker. You will need a frontend application (like those in [livekit-examples](https://github.com/livekit-examples) or a custom one) to connect to the LiveKit room and interact with the agent.

## Building and Deployment

Use the provided scripts for building and deploying:

```bash
# Example: Build a Docker image (check script content for details)
./build.sh

# Example: Deploy the agent (check script content for details)
./deploy.sh
```
Refer to the contents of `build.sh` and `deploy.sh` for specific instructions and requirements (e.g., Docker, target deployment environment).

## License

This project is licensed under the terms of the LICENSE file.
