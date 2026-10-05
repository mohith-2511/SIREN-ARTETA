import logging


def setup_logging(debug: bool = False):
    logging.basicConfig(level=logging.DEBUG if debug else logging.INFO,
                        format="%(asctime)s %(levelname)-5s %(message)s", datefmt="%Y-%m-%d %H:%M:%S", force=True)
    for n in ("httpx", "httpcore", "sqlalchemy.engine", "paho"):
        logging.getLogger(n).setLevel(logging.WARNING)
