"""Entry point for `python -m inference_server` (the documented run command).

Without this, the package has no `__main__` and the documented invocation fails
with "'inference_server' is a package and cannot be directly executed" — the
runnable block lives in `main.py`, which would otherwise need
`python -m inference_server.main`.
"""
import uvicorn

from .config import settings

if __name__ == "__main__":
    uvicorn.run(
        "inference_server.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=False,
    )
