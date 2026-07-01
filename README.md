# seravops
custom Open Service Broker

## Development

Requires Python 3.10 or newer.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
uvicorn app.main:app --reload --port 7372
```

The API is available at <http://localhost:7372>, with interactive documentation at
<http://localhost:7372/docs> and a health check at <http://localhost:7372/health>.

Run checks with:

```bash
ruff check .
pytest
```

Alternatively, start the development server with Docker:

```bash
docker compose up --build
```
