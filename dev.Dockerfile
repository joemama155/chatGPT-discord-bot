FROM python:3.8

RUN mkdir -p /DiscordBot
WORKDIR /DiscordBot

RUN pip install pipenv
RUN pipenv install

CMD ["pipenv", "run", "main.py"]
