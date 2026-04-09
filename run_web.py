import os

import uvicorn


def main() -> None:
    host = os.getenv("STRATOS_HOST", "127.0.0.1")
    port = int(os.getenv("STRATOS_PORT", "8000"))
    uvicorn.run("webapp:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
