"""
Benutzer Service für Benutzerverwaltung.
"""
import bcrypt
from typing import Optional, Tuple, List
from ..models import Benutzer
from ..repositories import BenutzerRepository
from ..utils.helpers import get_role_level, log_action


class BenutzerService:
    """Service für Benutzer-Operationen."""
    
    @staticmethod
    def get_benutzer_liste(user_role: str) -> List[dict]:
        """
        Holt die Liste der Benutzer basierend auf der Rolle des anfragenden Users.
        """
        if user_role == 'Mitarbeiter':
            benutzer = BenutzerRepository.get_active_by_role('Student')
        else:
            # Laborleiter und Admin sehen alle
            benutzer = BenutzerRepository.get_all_active()
        
        return BenutzerRepository.list_to_dict(benutzer)
    
    @staticmethod
    def create_benutzer(
        request,
        email: str,
        vorname: str,
        nachname: str,
        rolle: str = 'Student',
        passwort: str = None,
        rfid_karte: str = None,
        labor_id: str = None
    ) -> Tuple[bool, dict]:
        """
        Erstellt einen neuen Benutzer.
        """
        current_user_level = get_role_level(request.user_role)
        requested_level = get_role_level(rolle)
        
        # Berechtigungsprüfung
        if request.user_role == 'Mitarbeiter' and requested_level >= current_user_level:
            return False, {'error': 'Mitarbeiter dürfen nur Benutzer mit Rolle "Student" anlegen'}
        
        if request.user_role == 'Laborleiter' and requested_level >= current_user_level:
            return False, {'error': f'Laborleiter dürfen keine Rolle "{rolle}" vergeben'}
        
        # E-Mail prüfen
        if BenutzerRepository.get_by_email(email):
            return False, {'error': 'E-Mail bereits registriert'}
        
        # RFID prüfen
        if rfid_karte and BenutzerRepository.check_rfid_exists(rfid_karte):
            return False, {'error': 'Diese Karte ist bereits vergeben'}
        
        # Passwort hashen
        if passwort:
            passwort_hash = bcrypt.hashpw(passwort.encode(), bcrypt.gensalt()).decode()
        else:
            # Temporäres Passwort für Karten-Login
            passwort_hash = bcrypt.hashpw('__KARTEN_LOGIN_ONLY__'.encode(), bcrypt.gensalt()).decode()
        
        # Benutzer erstellen
        benutzer = BenutzerRepository.create(
            email=email,
            vorname=vorname,
            nachname=nachname,
            passwort_hash=passwort_hash,
            rolle=rolle,
            rfid_karte=rfid_karte,
            labor_id=labor_id
        )
        
        log_action(request, 'benutzer_erstellt', details={
            'neuer_benutzer_id': str(benutzer.id),
            'rolle': rolle,
            'mit_passwort': bool(passwort)
        })
        
        return True, {
            'success': True,
            'id': str(benutzer.id),
            'message': 'Benutzer erstellt' + ('' if passwort else ' - Login per Karte möglich')
        }
    
    @staticmethod
    def update_benutzer(
        request,
        benutzer_id: str,
        **kwargs
    ) -> Tuple[bool, dict]:
        """
        Aktualisiert einen Benutzer.
        """
        benutzer = BenutzerRepository.get_by_id(benutzer_id)
        if not benutzer:
            return False, {'error': 'Benutzer nicht gefunden'}
        
        current_user_level = get_role_level(request.user_role)
        target_user_level = get_role_level(benutzer.rolle)
        
        # Man darf nur Benutzer bearbeiten mit niedrigerer Rolle
        if target_user_level >= current_user_level:
            return False, {'error': 'Keine Berechtigung diesen Benutzer zu bearbeiten'}
        
        # Neue Rolle prüfen
        if 'rolle' in kwargs:
            new_role_level = get_role_level(kwargs['rolle'])
            if new_role_level >= current_user_level:
                return False, {'error': f'Sie können keine Rolle vergeben, die gleich oder höher ist als Ihre eigene'}
        
        # Passwort hashen falls vorhanden
        if 'passwort' in kwargs:
            kwargs['passwort_hash'] = bcrypt.hashpw(
                kwargs.pop('passwort').encode(), bcrypt.gensalt()
            ).decode()
        
        BenutzerRepository.update(benutzer, **kwargs)
        
        log_action(request, 'benutzer_aktualisiert', details={
            'benutzer_id': str(benutzer.id),
            'felder': list(kwargs.keys())
        })
        
        return True, {'success': True, 'message': 'Benutzer aktualisiert'}
    
    @staticmethod
    def delete_benutzer(request, benutzer_id: str) -> Tuple[bool, dict]:
        """
        Deaktiviert einen Benutzer (soft delete).
        """
        benutzer = BenutzerRepository.get_by_id(benutzer_id)
        if not benutzer:
            return False, {'error': 'Benutzer nicht gefunden'}
        
        current_user_level = get_role_level(request.user_role)
        target_user_level = get_role_level(benutzer.rolle)
        
        if target_user_level >= current_user_level:
            return False, {'error': 'Keine Berechtigung diesen Benutzer zu löschen'}
        
        BenutzerRepository.deactivate(benutzer)
        
        log_action(request, 'benutzer_deaktiviert', details={
            'benutzer_id': str(benutzer.id)
        })
        
        return True, {'success': True, 'message': 'Benutzer deaktiviert'}
    
    @staticmethod
    def check_rfid_karte(rfid_karte: str, exclude_benutzer_id: str = None) -> Tuple[bool, Optional[dict]]:
        """
        Prüft ob eine RFID-Karte vergeben ist.
        Gibt (vergeben, benutzer_info) zurück.
        """
        existing = BenutzerRepository.get_by_rfid(rfid_karte)
        
        if existing and str(existing.id) != exclude_benutzer_id:
            return True, {
                'id': str(existing.id),
                'vorname': existing.vorname,
                'nachname': existing.nachname,
                'email': existing.email
            }
        
        return False, None
