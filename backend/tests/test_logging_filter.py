import logging
from uvicorn.logging import AccessFormatter
from backend.logging_filter import PrivateQueryFilter


def test_access_formatter_preserves_fields_and_redacts_ticket():
    record = logging.LogRecord('uvicorn.access', logging.INFO, '', 0, '%s - "%s %s HTTP/%s" %d',
        ('127.0.0.1:1', 'GET', '/stream?token=unit-secret&other=value', '1.1', 200), None)
    assert PrivateQueryFilter().filter(record)
    output = AccessFormatter('%(request_line)s %(status_code)s').format(record)
    assert 'unit-secret' not in output and '[REDACTED]' in output and '200' in output
