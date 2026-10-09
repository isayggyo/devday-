import logging
import re


class PrivateQueryFilter(logging.Filter):
    def filter(self, record):
        def redact(value):
            return re.sub(r'(token|ticket)=([^&\s"]+)', r'\1=[REDACTED]', value) if isinstance(value, str) else value
        # Uvicorn's AccessFormatter requires the original five structured args.
        record.msg = redact(record.msg)
        if isinstance(record.args, tuple): record.args = tuple(redact(value) for value in record.args)
        elif isinstance(record.args, dict): record.args = {key: redact(value) for key, value in record.args.items()}
        return True


logging.getLogger('uvicorn.access').addFilter(PrivateQueryFilter())
