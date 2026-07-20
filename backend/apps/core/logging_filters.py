import logging
import re

# Nunca logar dados sensiveis (cartao, documento, senha, CPF completo).
_PATTERNS = (
    re.compile(r"\b\d{16}\b"),  # numero de cartao
    re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b"),  # CPF
    re.compile(r'"password"\s*:\s*".*?"', re.IGNORECASE),
    re.compile(r'"token"\s*:\s*".*?"', re.IGNORECASE),
)


class RedactSensitiveDataFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            msg = record.msg
            for pattern in _PATTERNS:
                msg = pattern.sub("[REDACTED]", msg)
            record.msg = msg
        return True
