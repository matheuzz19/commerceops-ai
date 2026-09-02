import time


def main() -> None:
    """Keep the MCP service container alive until the real M3 server is added."""
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
