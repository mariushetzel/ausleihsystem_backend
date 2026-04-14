"""
Auth Service für Authentifizierungs-Logik.
"""
import bcrypt
import jwt
from typing import Optional, Tuple
from django.utils import timezone
from .. import jwt_utils
from ..models import Benutzer, TokenPair
from ..repositories import BenutzerRepository
from ..utils.helpers import get_client_info, log_action


class AuthService:
    """Service für Authentifizierungs-Operationen."""
    
    @staticmethod
    def register_user(
        email: str,
        passwort: str,
        vorname: str,
        nachname: str,
        rfid_karte: str = None
    ) -> Tuple[bool, dict]:
        """
        Registriert einen neuen Benutzer.
        Gibt (success, result) zurück.
        """
        email = email.lower().strip()
        
        # Prüfen ob E-Mail bereits existiert
        if BenutzerRepository.get_by_email(email):
            return False, {'error': 'E-Mail bereits registriert'}
        
        # Prüfen ob RFID-Karte bereits vergeben ist
        if rfid_karte and BenutzerRepository.check_rfid_exists(rfid_karte):
            return False, {'error': 'Diese Karte ist bereits einem anderen Benutzer zugeordnet'}
        
        # Passwort hashen
        passwort_hash = bcrypt.hashpw(passwort.encode(), bcrypt.gensalt()).decode()
        
        # Benutzer erstellen
        benutzer = BenutzerRepository.create(
            email=email,
            passwort_hash=passwort_hash,
            vorname=vorname,
            nachname=nachname,
            rolle='Student',  # Immer Student für öffentliche Registrierung
            rfid_karte=rfid_karte
        )
        
        return True, {
            'success': True,
            'id': str(benutzer.id),
            'message': 'Registrierung erfolgreich'
        }
    
    @staticmethod
    def authenticate(
        email: str = None,
        passwort: str = None,
        rfid_karte: str = None
    ) -> Tuple[bool, Optional[Benutzer], str]:
        """
        Authentifiziert einen Benutzer.
        Gibt (success, benutzer, error_message) zurück.
        """
        try:
            if rfid_karte:
                benutzer = BenutzerRepository.get_by_rfid(rfid_karte)
                if not benutzer:
                    return False, None, 'Benutzer nicht gefunden'
            elif email and passwort:
                benutzer = BenutzerRepository.get_by_email(email)
                if not benutzer:
                    return False, None, 'Benutzer nicht gefunden'
                
                # Prüfen ob User nur per Karte angelegt wurde
                if benutzer.passwort_hash and '__KARTEN_LOGIN_ONLY__' in benutzer.passwort_hash:
                    return False, None, 'Bitte melden Sie sich mit Ihrer Karte an und setzen Sie ein Passwort im Profil'
                
                # Passwort prüfen
                if not bcrypt.checkpw(passwort.encode(), benutzer.passwort_hash.encode()):
                    return False, None, 'Ungültige Anmeldedaten'
            else:
                return False, None, 'RFID-Karte oder E-Mail/Passwort erforderlich'
            
            return True, benutzer, None
            
        except Exception as e:
            return False, None, str(e)
    
    @staticmethod
    def login(
        request,
        email: str = None,
        passwort: str = None,
        rfid_karte: str = None
    ) -> Tuple[bool, dict]:
        """
        Führt einen Login durch und gibt Tokens zurück.
        """
        success, benutzer, error = AuthService.authenticate(email, passwort, rfid_karte)
        
        if not success:
            return False, {'error': error}
        
        # Token-Paar erstellen
        client_info = get_client_info(request)
        tokens = jwt_utils.create_token_pair(benutzer, **client_info)
        
        # Login loggen
        log_action(request, 'login', details={'methode': 'rfid' if rfid_karte else 'password'})
        
        return True, {
            'success': True,
            'user': {
                'id': str(benutzer.id),
                'vorname': benutzer.vorname,
                'nachname': benutzer.nachname,
                'email': benutzer.email,
                'rolle': benutzer.rolle,
            },
            **tokens
        }
    
    @staticmethod
    def logout(request) -> dict:
        """
        Führt einen Logout durch (widerruft Token).
        """
        from ..utils.decorators import get_auth_header
        
        token = get_auth_header(request)
        if token:
            try:
                payload = jwt.decode(token, options={"verify_signature": False})
                jti = payload.get('jti')
                if jti:
                    TokenPair.objects.filter(access_token_jti=jti).update(
                        revoked=True,
                        revoked_at=timezone.now(),
                        revoked_reason='logout'
                    )
            except:
                pass
        
        return {'success': True, 'message': 'Ausgeloggt'}
    
    @staticmethod
    def refresh_token(refresh_token_str: str, request) -> Tuple[bool, dict]:
        """
        Erstellt neues Token-Paar mit Refresh Token.
        """
        try:
            client_info = get_client_info(request)
            tokens = jwt_utils.refresh_access_token(refresh_token_str, **client_info)
            return True, {'success': True, **tokens}
        except jwt.ExpiredSignatureError:
            return False, {'error': 'Refresh Token abgelaufen'}
        except (jwt.InvalidTokenError, ValueError) as e:
            return False, {'error': str(e)}
    
    @staticmethod
    def get_current_user(user_id: str) -> Optional[dict]:
        """
        Gibt aktuellen Benutzer als Dictionary zurück.
        """
        benutzer = BenutzerRepository.get_by_id(user_id)
        if not benutzer:
            return None
        
        return {
            'id': str(benutzer.id),
            'vorname': benutzer.vorname,
            'nachname': benutzer.nachname,
            'email': benutzer.email,
            'rolle': benutzer.rolle,
            'rfid_karte': benutzer.rfid_karte,
        }
