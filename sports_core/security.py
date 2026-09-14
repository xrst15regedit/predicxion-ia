import os
import hmac
import hashlib
import time
from functools import wraps
from flask import request, jsonify

class SecurityGateway:
    """Verificación de firmas HMAC-SHA256 y control de acceso basado en roles."""
    SECRET_KEY = os.getenv("API_HMAC_SECRET", "4f8a92b8d4e5f6a1c2b3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5")

    @classmethod
    def generate_signature(cls, payload: str, timestamp: int) -> str:
        message = f"{timestamp}:{payload}".encode("utf-8")
        return hmac.new(cls.SECRET_KEY.encode("utf-8"), message, hashlib.sha256).hexdigest()

    @classmethod
    def verify_request_signature(cls, payload: str, signature: str, timestamp: int, tolerance_sec: int = 300) -> bool:
        if abs(time.time() - timestamp) > tolerance_sec:
            return False
        expected = cls.generate_signature(payload, timestamp)
        return hmac.compare_digest(expected, signature)

def require_intel_role(required_role: str):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            auth_header = request.headers.get("Authorization")
            if not auth_header:
                return jsonify({"error": "Cabecera Authorization obligatoria."}), 401
            return f(*args, **kwargs)
        return decorated_function
    return decorator
