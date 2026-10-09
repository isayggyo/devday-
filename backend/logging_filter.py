import logging
import re


class PrivateQueryFilter(logging.Filter):
    def filter(self, record):
        record.msg = re.sub(r'(token|ticket)=([^&\s"]+)', r'\1=[REDACTED]', record.getMessage())
        record.args = ()
        return True


logging.getLogger('uvicorn.access').addFilter(PrivateQueryFilter())
