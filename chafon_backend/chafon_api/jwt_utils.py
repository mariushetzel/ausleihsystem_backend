"""
JWT-Utilities für das Ausleihsystem.
Erstellt und validiert JWT-Tokens mit Rotation.
"""

import jwt
import uuid
import bcrypt
from datetime import datetime, timedelta
from django.conf import settings
from django.utils import timezone
from .models import Benutzer, TokenPair


def hash_refresh_token(token_str: str) -> str:
    """Hasht einen Refresh Token mit bcrypt (max 72 Bytes)."""
    # bcrypt hat ein 72-Byte-Limit
    token_bytes = token_str.encode()
    if len(token_bytes) > 72:
        import hashlib
        # SHA-256 Hash verwenden um auf 32 Bytes zu kommen
        token_bytes = hashlib.sha256(token_bytes).digest()
    return bcrypt.hashpw(token_bytes, bcrypt.gensalt()).decode()


def verify_refresh_token(token_str: str, hashed: str) -> bool:
    """Prüft ob ein Refresh Token zum Hash passt."""
    token_bytes = token_str.encode()
    if len(token_bytes) > 72:
        import hashlib
        token_bytes = hashlib.sha256(token_bytes).digest()
    return bcrypt.checkpw(token_bytes, hashed.encode())


def create_token_pair(benutzer: Benutzer, device_info: str = '', ip_address: str = '') -> dict:
    """
    Erstellt ein neues Token-Paar (Access + Refresh) für einen Benutzer.
    
    Returns:
        dict: {
            'access_token': str,
            'refresh_token': str,
            'expires_in': int (Sekunden)
        }
    """
    now = timezone.now()
    
    # Token IDs (für Widerruf)
    access_jti = str(uuid.uuid4())
    refresh_jti = str(uuid.uuid4())
    family_id = str(uuid.uuid4())
    pair_id = str(uuid.uuid4())
    
    # Ablaufzeiten
    access_expires = now + timedelta(minutes=settings.JWT_ACCESS_TOKEN_LIFETIME)
    refresh_expires = now + timedelta(days=settings.JWT_REFRESH_TOKEN_LIFETIME)
    
    # Access Token Payload
    access_payload = {
        'sub': str(benutzer.id),  # Subject = User ID
        'email': benutzer.email,
        'vorname': benutzer.vorname,
        'nachname': benutzer.nachname,
        'rolle': benutzer.rolle,
        'jti': access_jti,  # JWT ID (eindeutig)
        'iat': now,  # Issued at
        'exp': access_expires,
        'type': 'access'
    }
    
    # Refresh Token Payload (minimale Information)
    refresh_payload = {
        'sub': str(benutzer.id),
        'jti': refresh_jti,
        'family_id': family_id,
        'iat': now,
        'exp': refresh_expires,
        'type': 'refresh'
    }
    
    # Tokens erstellen
    access_token = jwt.encode(
        access_payload, 
        settings.JWT_SECRET_KEY, 
        algorithm=settings.JWT_ALGORITHM
    )
    
    refresh_token = jwt.encode(
        refresh_payload,
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM
    )
    
    # Refresh Token hashen (nur der Hash wird gespeichert!)
    refresh_hash = hash_refresh_token(refresh_token)
    
    # In Datenbank speichern
    TokenPair.objects.create(
        benutzer=benutzer,
        family_id=family_id,
        pair_id=pair_id,
        access_token_jti=access_jti,
        access_token_expires=access_expires,
        refresh_token_jti=refresh_jti,
        refresh_token_hash=refresh_hash,
        refresh_token_expires=refresh_expires,
        device_info=device_info,
        ip_address=ip_address
    )
    
    # Letzten Login aktualisieren
    benutzer.letzter_login = now
    benutzer.save(update_fields=['letzter_login'])
    
    return {
        'access_token': access_token,
        'refresh_token': refresh_token,
        'expires_in': settings.JWT_ACCESS_TOKEN_LIFETIME * 60,  # Sekunden
        'token_type': 'Bearer'
    }


def verify_access_token(token_str: str) -> dict:
    """
    Verifiziert einen Access Token.
    
    Returns:
        dict: Token Payload
        
    Raises:
        jwt.ExpiredSignatureError: Token abgelaufen
        jwt.InvalidTokenError: Ungültiger Token
        ValueError: Token wurde widerrufen
    """
    try:
        payload = jwt.decode(
            token_str,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM]
        )
        
        # Prüfen ob es ein Access Token ist
        if payload.get('type') != 'access':
            raise jwt.InvalidTokenError('Kein Access Token')
        
        # Prüfen ob Token widerrufen wurde
        jti = payload.get('jti')
        if jti:
            token_revoked = TokenPair.objects.filter(
                access_token_jti=jti,
                revoked=True
            ).exists()
            if token_revoked:
                raise ValueError('Token wurde widerrufen')
        
        return payload
        
    except jwt.ExpiredSignatureError:
        raise
    except jwt.InvalidTokenError:
        raise


def refresh_access_token(refresh_token_str: str, device_info: str = '', ip_address: str = '') -> dict:
    """
    Erstellt ein neues Token-Paar mit einem Refresh Token (Token Rotation).
    Der alte Refresh Token wird invalidiert.
    
    Returns:
        dict: Neues Token-Paar
        
    Raises:
        jwt.ExpiredSignatureError: Refresh Token abgelaufen
        jwt.InvalidTokenError: Ungültiger Refresh Token
        ValueError: Token wurde widerrufen oder bereits verwendet
    """
    try:
        # Refresh Token decodieren
        payload = jwt.decode(
            refresh_token_str,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM]
        )
        
        if payload.get('type') != 'refresh':
            raise jwt.InvalidTokenError('Kein Refresh Token')
        
        jti = payload.get('jti')
        user_id = payload.get('sub')
        family_id = payload.get('family_id')
        
        # Zugehöriges TokenPair finden
        try:
            token_pair = TokenPair.objects.get(
                refresh_token_jti=jti,
                revoked=False
            )
        except TokenPair.DoesNotExist:
            raise ValueError('Token nicht gefunden oder bereits verwendet')
        
        # Hash verifizieren
        if not verify_refresh_token(refresh_token_str, token_pair.refresh_token_hash):
            raise ValueError('Token Hash stimmt nicht überein')
        
        # Altes Token-Paar widerrufen (Rotation!)
        token_pair.revoked = True
        token_pair.revoked_at = timezone.now()
        token_pair.revoked_reason = 'refreshed'
        token_pair.save()
        
        # Benutzer laden
        try:
            benutzer = Benutzer.objects.get(id=user_id, aktiv=True)
        except Benutzer.DoesNotExist:
            raise ValueError('Benutzer nicht gefunden oder inaktiv')
        
        # Neues Token-Paar erstellen (gleiche Family)
        now = timezone.now()
        access_jti = str(uuid.uuid4())
        refresh_jti = str(uuid.uuid4())
        pair_id = str(uuid.uuid4())
        
        access_expires = now + timedelta(minutes=settings.JWT_ACCESS_TOKEN_LIFETIME)
        refresh_expires = now + timedelta(days=settings.JWT_REFRESH_TOKEN_LIFETIME)
        
        # Neue Tokens
        access_token = jwt.encode(
            {
                'sub': str(benutzer.id),
                'email': benutzer.email,
                'vorname': benutzer.vorname,
                'nachname': benutzer.nachname,
                'rolle': benutzer.rolle,
                'jti': access_jti,
                'iat': now,
                'exp': access_expires,
                'type': 'access'
            },
            settings.JWT_SECRET_KEY,
            algorithm=settings.JWT_ALGORITHM
        )
        
        new_refresh_token = jwt.encode(
            {
                'sub': str(benutzer.id),
                'jti': refresh_jti,
                'family_id': family_id,  # Gleiche Family!
                'iat': now,
                'exp': refresh_expires,
                'type': 'refresh'
            },
            settings.JWT_SECRET_KEY,
            algorithm=settings.JWT_ALGORITHM
        )
        
        # Speichern
        TokenPair.objects.create(
            benutzer=benutzer,
            family_id=family_id,  # Gleiche Family wie vorher
            pair_id=pair_id,
            access_token_jti=access_jti,
            access_token_expires=access_expires,
            refresh_token_jti=refresh_jti,
            refresh_token_hash=hash_refresh_token(new_refresh_token),
            refresh_token_expires=refresh_expires,
            device_info=device_info,
            ip_address=ip_address
        )
        
        return {
            'access_token': access_token,
            'refresh_token': new_refresh_token,
            'expires_in': settings.JWT_ACCESS_TOKEN_LIFETIME * 60,
            'token_type': 'Bearer'
        }
        
    except jwt.ExpiredSignatureError:
        raise
    except jwt.InvalidTokenError:
        raise


def revoke_token_family(family_id: str, reason: str = 'logout'):
    """Widerruft alle Tokens einer Familie (z.B. bei Logout alle Geräte)."""
    TokenPair.objects.filter(
        family_id=family_id,
        revoked=False
    ).update(
        revoked=True,
        revoked_at=timezone.now(),
        revoked_reason=reason
    )


def revoke_all_user_tokens(benutzer_id: str, reason: str = 'logout'):
    """Widerruft alle aktiven Tokens eines Benutzers."""
    TokenPair.objects.filter(
        benutzer_id=benutzer_id,
        revoked=False
    ).update(
        revoked=True,
        revoked_at=timezone.now(),
        revoked_reason=reason
    )


def get_current_user_from_token(token_str: str) -> Benutzer:
    """Holt den Benutzer aus einem validen Access Token."""
    payload = verify_access_token(token_str)
    user_id = payload.get('sub')
    return Benutzer.objects.get(id=user_id, aktiv=True)
