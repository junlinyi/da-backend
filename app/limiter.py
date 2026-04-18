# app/limiter.py
# Single shared slowapi limiter — import this everywhere instead of
# creating a new Limiter() per router. All @limiter.limit() decorators
# must reference the same object that is attached to app.state.limiter.

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
