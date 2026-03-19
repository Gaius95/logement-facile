"""
Configuration Gunicorn pour production (Render, VPS, etc.).
Ajuste WEB_CONCURRENCY selon la RAM : ~150–200 Mo par worker typique.
"""
import multiprocessing
import os

bind = f"0.0.0.0:{os.environ.get('PORT', '5000')}"

# Capacité : workers × threads = requêtes concurrentes approximatives (I/O bound)
_workers = int(os.environ.get("WEB_CONCURRENCY", "0"))
if _workers <= 0:
    _workers = min(max(multiprocessing.cpu_count() * 2 + 1, 2), 4)

workers = _workers
worker_class = "gthread"
threads = int(os.environ.get("GUNICORN_THREADS", "4"))
timeout = int(os.environ.get("GUNICORN_TIMEOUT", "120"))
graceful_timeout = int(os.environ.get("GUNICORN_GRACEFUL_TIMEOUT", "30"))
keepalive = int(os.environ.get("GUNICORN_KEEPALIVE", "5"))

# Recycler les workers pour limiter les fuites mémoire sur longue durée
max_requests = int(os.environ.get("GUNICORN_MAX_REQUESTS", "1000"))
max_requests_jitter = int(os.environ.get("GUNICORN_MAX_REQUESTS_JITTER", "100"))

accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("GUNICORN_LOG_LEVEL", "info")
capture_output = True
