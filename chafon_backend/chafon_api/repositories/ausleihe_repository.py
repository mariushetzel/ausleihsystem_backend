"""
Repository für Ausleihe-Datenbankzugriffe.
"""
from typing import Optional, List
from django.db.models import QuerySet
from ..models import Ausleihe, Benutzer, Ware


class AusleiheRepository:
    """Repository für Ausleihe-Operationen."""
    
    @staticmethod
    def get_all_active() -> QuerySet[Ausleihe]:
        """Gibt alle aktiven Ausleihen zurück."""
        return Ausleihe.objects.filter(aktiv=True)
    
    @staticmethod
    def get_by_id(ausleihe_id: str) -> Optional[Ausleihe]:
        """Gibt eine Ausleihe anhand ihrer ID zurück."""
        try:
            return Ausleihe.objects.get(id=ausleihe_id, aktiv=True)
        except Ausleihe.DoesNotExist:
            return None
    
    @staticmethod
    def get_by_benutzer(benutzer_id: str) -> QuerySet[Ausleihe]:
        """Gibt alle Ausleihen eines Benutzers zurück."""
        return Ausleihe.objects.filter(benutzer_id=benutzer_id, aktiv=True)
    
    @staticmethod
    def get_by_ware(ware_id: str) -> QuerySet[Ausleihe]:
        """Gibt alle Ausleihen einer Ware zurück."""
        return Ausleihe.objects.filter(ware_id=ware_id, aktiv=True)
    
    @staticmethod
    def filter_by_status(queryset: QuerySet[Ausleihe], status: str) -> QuerySet[Ausleihe]:
        """Filtert Ausleihen nach Status."""
        return queryset.filter(status=status)
    
    @staticmethod
    def get_with_prefetch() -> QuerySet[Ausleihe]:
        """Gibt aktive Ausleihen mit vorab geladenen Related-Objekten zurück."""
        return Ausleihe.objects.filter(
            aktiv=True,
            status__in=['aktiv', 'rueckgabe_beantragt']
        ).select_related(
            'ware', 'benutzer'
        ).prefetch_related('ware__kategorien')
    
    @staticmethod
    def create(
        ware: Ware,
        benutzer: Benutzer,
        geplante_rueckgabe: str = None,
        verbleib_ort: str = '',
        notiz: str = ''
    ) -> Ausleihe:
        """Erstellt eine neue Ausleihe."""
        return Ausleihe.objects.create(
            ware=ware,
            benutzer=benutzer,
            geplante_rueckgabe=geplante_rueckgabe,
            verbleib_ort=verbleib_ort,
            notiz=notiz
        )
    
    @staticmethod
    def update_status(ausleihe: Ausleihe, status: str) -> Ausleihe:
        """Aktualisiert den Status einer Ausleihe."""
        ausleihe.status = status
        ausleihe.save()
        return ausleihe
    
    @staticmethod
    def complete_return(ausleihe: Ausleihe, schadensmeldung: str = None) -> Ausleihe:
        """Schließt eine Ausleihe ab (Rückgabe)."""
        ausleihe.status = 'abgeschlossen'
        ausleihe.ist_zurueckgegeben = True
        ausleihe.tatsaechliche_rueckgabe = timezone.now()
        if schadensmeldung:
            ausleihe.schadensmeldung = schadensmeldung
        ausleihe.save()
        
        # Ware als verfügbar markieren
        ausleihe.ware.ist_ausgeliehen = False
        ausleihe.ware.save()
        
        return ausleihe
    
    @staticmethod
    def to_dict(ausleihe: Ausleihe, benutzer_name: str = None, anonymisiert: bool = False) -> dict:
        """Konvertiert eine Ausleihe in ein Dictionary."""
        if benutzer_name is None:
            benutzer_name = f"{ausleihe.benutzer.vorname} {ausleihe.benutzer.nachname}"
        
        # Kategorien laden
        kategorien_list = list(ausleihe.ware.kategorien.all())
        primary_kategorie = kategorien_list[0].name if kategorien_list else None
        
        return {
            'id': str(ausleihe.id),
            'ware': {
                'id': str(ausleihe.ware.id),
                'name': ausleihe.ware.name,
                'rfid_tag': ausleihe.ware.rfid_tag,
                'schranknummer': ausleihe.ware.schranknummer,
                'kategorie_name': primary_kategorie,
                'kategorien': [{'id': str(k.id), 'name': k.name} for k in kategorien_list],
            },
            'benutzer': {
                'id': str(ausleihe.benutzer.id),
                'name': 'Andere' if anonymisiert else benutzer_name,
            },
            'status': ausleihe.status,
            'ausgeliehen_am': ausleihe.ausgeliehen_am,
            'geplante_rueckgabe': ausleihe.geplante_rueckgabe,
            'rueckgabe_beantragt_am': ausleihe.rueckgabe_beantragt_am,
            'tatsaechliche_rueckgabe': ausleihe.tatsaechliche_rueckgabe,
            'verbleib_ort': None if anonymisiert else ausleihe.verbleib_ort,
            'notiz': ausleihe.notiz,
        }
    
    @staticmethod
    def list_to_dict(ausleihen: QuerySet[Ausleihe], current_user_id: str = None, is_student: bool = False) -> List[dict]:
        """Konvertiert eine Liste von Ausleihen in Dictionaries."""
        result = []
        for a in ausleihen:
            anonymisiert = is_student and str(a.benutzer.id) != str(current_user_id)
            benutzer_name = f"{a.benutzer.vorname} {a.benutzer.nachname}"
            result.append(AusleiheRepository.to_dict(a, benutzer_name, anonymisiert))
        return result


# Import für complete_return
from django.utils import timezone
