# Gunicorn config for HACRI-E + Orientation integrated app
# uvicorn workers for FastAPI (async)
worker_class = "uvicorn.workers.UvicornWorker"
workers = 2
bind = "0.0.0.0:8000"
timeout = 120
keepalive = 5
accesslog = "-"
errorlog = "-"
loglevel = "info"
