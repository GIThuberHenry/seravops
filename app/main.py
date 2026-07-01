from fastapi import FastAPI


def create_app() -> FastAPI:
    application = FastAPI(
        title="Seravops",
        description="Custom Open Service Broker API",
        version="0.1.0",
    )

    @application.get("/health", tags=["health"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return application


app = create_app()

