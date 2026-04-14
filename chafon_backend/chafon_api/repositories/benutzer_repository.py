"""
Repository für Benutzer-Datenbankzugriffe.
"""
import uuid
from typing import Optional, List
from django.db.models import QuerySet
from ..models import Benutzer


class BenutzerRepository:
    """Repository für Benutzer-Operationen."""
    
    @staticmethod
    def get_all_active() -> QuerySet[Benutzer]:
        """Gibt alle aktiven Benutzer zurück."""
        return Benutzer.objects.filter(aktiv=True)
    
    @staticmethod
    def get_active_by_role(rolle: str) -> QuerySet[Benutzer]:
        """Gibt alle aktiven Benutzer einer Rolle zurück."""
        return Benutzer.objects.filter(aktiv=True, rolle=rolle)
    
    @staticmethod
    def get_by_id(benutzer_id: str) -> Optional[Benutzer]:
        """Gibt einen Benutzer anhand seiner ID zurück."""
        try:
            return Benutzer.objects.get(id=benutzer_id, aktiv=True)
        except Benutzer.DoesNotExist:
            return None
    
    @staticmethod
    def get_by_email(email: str) -> Optional[Benutzer]:
        """Gibt einen Benutzer anhand seiner E-Mail zurück."""
        try:
            return Benutzer.objects.get(email__iexact=email.lower().strip())
        except Benutzer.DoesNotExist:
            return None
    
    @staticmethod
    def get_by_rfid(rfid_karte: str) -> Optional[Benutzer]:
        """Gibt einen Benutzer anhand seiner RFID-Karte zurück."""
        try:
            return Benutzer.objects.get(rfid_karte=rfid_karte, aktiv=True)
        except Benutzer.DoesNotExist:
            return None
    
    @staticmethod
    def check_rfid_exists(rfid_karte: str, exclude_id: str = None) -> bool:
        """Prüft ob eine RFID-Karte bereits vergeben ist."""
        queryset = Benutzer.objects.filter(rfid_karte=rfid_karte)
        if exclude_id:
            queryset = queryset.exclude(id=exclude_id)
        return queryset.exists()
    
    @staticmethod
    def create(
        email: str,
        vorname: str,
        nachname: str,
        passwort_hash: str,
        rolle: str = 'Student',
        rfid_karte: str = None,
        labor_id: str = None
    ) -> Benutzer:
        """Erstellt einen neuen Benutzer."""
        return Benutzer.objects.create(
            email=email.lower().strip(),
            vorname=vorname,
            nachname=nachname,
            passwort_hash=passwort_hash,
            rolle=rolle,
            rfid_karte=rfid_karte,
            labor_id=labor_id
        )
    
    @staticmethod
    def update(benutzer: Benutzer, **kwargs) -> Benutzer:
        """Aktualisiert einen Benutzer."""
        for key, value in kwargs.items():
            if hasattr(benutzer, key):
                setattr(benutzer, key, value)
        benutzer.save()
        return benutzer
    
    @staticmethod
    def deactivate(benutzer: Benutzer) -> None:
        """Deaktiviert einen Benutzer (soft delete)."""
        benutzer.aktiv = False
        benutzer.save()
    
    @staticmethod
    def to_dict(benutzer: Benutzer) -> dict:
        """Konvertiert einen Benutzer in ein Dictionary."""
        return {
            'id': str(benutzer.id),
            'vorname': benutzer.vorname,
            'nachname': benutzer.nachname,
            'email': benutzer.email,
            'rolle': benutzer.rolle,
            'rfid_karte': benutzer.rfid_karte,
            'hat_passwort': benutzer.hat_passwort(),
            'hat_karte': bool(benutzer.rfid_karte),
        }
    
    @staticmethod
    def list_to_dict(benutzer_list: QuerySet[Benutzer]) -> List[dict]:
        """Konvertiert eine Liste von Benutzern in Dictionaries."""
        return [BenutzerRepository.to_dict(b) for b in benutzer_list]
