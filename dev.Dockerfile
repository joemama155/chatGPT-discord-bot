FROM python:3.8

RUN mkdir -p /DiscordBot
WORKDIR /DiscordBot

COPY ./Pipfile ./Pipfile.lock ./

RUN pip install pipenv
RUN pipenv install --dev

CMD ["pipenv", "run", "watchmedo", "auto-restart", "--recursive", "python", "main.py"]
