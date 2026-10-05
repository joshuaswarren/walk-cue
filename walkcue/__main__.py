import uvicorn

from walkcue.config import Settings


def main() -> None:
    settings = Settings.from_env()
    uvicorn.run("walkcue.main:app", host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
