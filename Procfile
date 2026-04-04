monitor: python -m monitor.poller
bot: python -m bot.bot
redirect: uvicorn redirect.app:app --host 0.0.0.0 --port $PORT
dashboard: uvicorn dashboard.app:app --host 0.0.0.0 --port $PORT
