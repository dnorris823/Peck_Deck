FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy into a `backend` package directory rather than flattening into /app.
# main.py imports its siblings relatively (`from .auth.guards import ...`), so it
# has to be imported as `backend.main` — importing it as a top-level `main`
# fails with "attempted relative import with no known parent package".
COPY . ./backend

EXPOSE 8000

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
