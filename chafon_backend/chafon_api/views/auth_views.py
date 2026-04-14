"""
Auth Views für Authentifizierungs-Endpunkte.
"""
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from ..services import AuthService
from ..utils.decorators import jwt_required
from ..utils.helpers import validate_email_domain


@api_view(['POST'])
@permission_classes([AllowAny])
def register(request):
    """
    Öffentliche Registrierung für neue Benutzer.
    """
    data = request.data
    
    # E-Mail Validierung
    is_valid, error_msg = validate_email_domain(data.get('email'))
    if not is_valid:
        return Response({'error': error_msg}, status=400)
    
    success, result = AuthService.register_user(
        email=data['email'],
        passwort=data['passwort'],
        vorname=data['vorname'],
        nachname=data['nachname'],
        rfid_karte=data.get('rfid_karte')
    )
    
    if not success:
        return Response(result, status=400)
    
    return Response(result, status=201)


@api_view(['POST'])
@permission_classes([AllowAny])
def login(request):
    """
    Login mit RFID-Karte oder E-Mail/Passwort.
    """
    data = request.data
    
    success, result = AuthService.login(
        request=request,
        email=data.get('email'),
        passwort=data.get('passwort'),
        rfid_karte=data.get('rfid_karte')
    )
    
    if not success:
        return Response(result, status=401)
    
    return Response(result)


@api_view(['POST'])
@jwt_required
def logout(request):
    """
    Logout: Widerruft das aktuelle Token-Paar.
    """
    result = AuthService.logout(request)
    return Response(result)


@api_view(['POST'])
@permission_classes([AllowAny])
def refresh_token(request):
    """
    Erstellt neues Token-Paar mit Refresh Token.
    """
    refresh_token_str = request.data.get('refresh_token')
    if not refresh_token_str:
        return Response({'error': 'Refresh Token fehlt'}, status=400)
    
    success, result = AuthService.refresh_token(refresh_token_str, request)
    
    if not success:
        return Response(result, status=401)
    
    return Response(result)


@api_view(['GET'])
@jwt_required
def me(request):
    """
    Gibt aktuellen Benutzer zurück.
    """
    user_data = AuthService.get_current_user(request.user_id)
    
    if not user_data:
        return Response({'error': 'Benutzer nicht gefunden'}, status=404)
    
    return Response(user_data)
