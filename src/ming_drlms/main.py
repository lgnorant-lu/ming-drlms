from .utils.startup_debug import log_time
from .cli import app

log_time("Imports started")
log_time("CLI app imported")


def main():
    log_time("Entering main")
    app()


if __name__ == "__main__":
    main()
