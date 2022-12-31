# Chat GPT Discord Bot
Provides access to OpenAI models via a Discord bot.

# Table Of Contents
- [Overview](#overview)
- [Setup](#setup)
- [Development](#development)

# Overview
A Python Discord bot which provides access to OpenAI's GPT3. Fork of [@Zero6992's chatGPT-discord-bot repository](https://github.com/Zero6992/chatGPT-discord-bot). Provides the modifications:

- Provides a conversation transcript to GPT3 as part of the prompt so the model appears to "remember" a portion of the conversation
- Code refactored to bit (Env vars for config, Python virtual environments, and more)

# Setup
## Configuration
Configuration values are set via the following environment variables:
- `OPENAI_API_KEY`: Your OpenAPI API key
- `REDIS_HOST`: Hostname of Redis server (Default: `redis`)
- `REDIS_PORT`: Port number of Redis server (Default: `6379`)
- `REDIS_DB`: Database number of Redis server (Default: `0`)

## Install & Run
Pipenv is used to manage a Python virtual environment. Install dependencies and then activate the environment:

```
pipenv install
pipenv shell
```

Then run the bot:

```
./main.py
```

The [`Dockerfile`](./Dockerfile) in the repository root performs these steps automatically.

# Development
The [`docker-compose.yaml`](./docker-compose.yaml) and [`dev.Dockerfile`](./dev.Dockerfile) files provide a development environment which is pre-setup. To use:

1. Make a copy of `.env-dev.example` named `.env-dev` and fill in your own values
2. Launch the Docker Compose stack:
   ```
   docker compose up -d --build
   ```
