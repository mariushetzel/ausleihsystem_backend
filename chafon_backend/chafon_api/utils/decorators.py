"""
Decorator für Authentifizierung und Autorisierung.
"""
from functools import wraps
import jwt
from rest_framework.response import Response
from .. import jwt_utils


def get_auth_header(request):
    """Extrahiert das Bearer Token aus dem Authorization Header."""
    auth_header = request.headers.get('Authorization', '')
    if auth_header.startswith('Bearer '):
        return auth_header[7:]
    return None


def jwt_required(view_func):
    """Decorator: Prüft JWT-Token und fügt request.user hinzu."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        token = get_auth_header(request)
        if not token:
            return Response({'error': 'Authorization Header fehlt'}, status=401)
        
        try:
            payload = jwt_utils.verify_access_token(token)
            request.user_id = payload.get('sub')
            request.user_role = payload.get('rolle')
            request.user_payload = payload
            return view_func(request, *args, **kwargs)
        except jwt.ExpiredSignatureError:
            return Response({'error': 'Token abgelaufen'}, status=401)
        except jwt.InvalidTokenError as e:
            return Response({'error': f'Ungültiger Token: {str(e)}'}, status=401)
        except ValueError as e:
            return Response({'error': str(e)}, status=401)
    return wrapper


def require_role(roles):
    """Decorator: Prüft ob Benutzer eine der erforderlichen Rollen hat."""
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if not hasattr(request, 'user_role'):
                return Response({'error': 'Authentifizierung erforderlich'}, status=401)
            
            if request.user_role not in roles:
                return Response(
                    {'error': f'Rolle "{request.user_role}" nicht berechtigt. Benötigt: {roles}'},
                    status=403
                )
            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator
