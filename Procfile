# For a host that reads a Procfile (Fly, Heroku-likes) rather than render.yaml.
# ONE worker: see the comment in render.yaml. The queue that serialises runs
# against a single SQLite checkpoint file lives in one process.
web: python -m uvicorn web.app:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1
