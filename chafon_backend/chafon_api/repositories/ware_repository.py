"""
Repository für Ware-Datenbankzugriffe.
"""
from typing import Optional, List
from django.db.models import QuerySet, Max
from ..models import Ware, Ausleihe


class WareRepository:
    """Repository für Ware-Operationen."""
    
    @staticmethod
    def get_all_active() -> QuerySet[Ware]:
        """Gibt alle aktiven Waren zurück."""
        return Ware.objects.filter(aktiv=True).prefetch_related('kategorien')
    
    @staticmethod
    def get_by_id(ware_id: str) -> Optional[Ware]:
        """Gibt eine Ware anhand ihrer ID zurück."""
        try:
            return Ware.objects.get(id=ware_id, aktiv=True)
        except Ware.DoesNotExist:
            return None
    
    @staticmethod
    def filter_by_kategorie(queryset: QuerySet[Ware], kategorie_id: str) -> QuerySet[Ware]:
        """Filtert Waren nach Kategorie."""
        return queryset.filter(kategorien__id=kategorie_id)
    
    @staticmethod
    def filter_verfuegbar(queryset: QuerySet[Ware]) -> QuerySet[Ware]:
        """Filtert nach verfügbaren Waren."""
        return queryset.filter(ist_ausgeliehen=False, ist_gesperrt=False)
    
    @staticmethod
    def get_paginated(queryset: QuerySet[Ware], offset: int = 0, limit: int = 100) -> QuerySet[Ware]:
        """Wendet Pagination auf ein QuerySet an."""
        return queryset[offset:offset + limit]
    
    @staticmethod
    def get_letzte_ausleihen(waren: QuerySet[Ware]) -> dict:
        """Holt die letzten Ausleihen für eine Liste von Waren."""
        letzte_ausleihen = Ausleihe.objects.filter(
            ware__in=waren
        ).values('ware').annotate(
            letzte_ausleihe=Max('ausgeliehen_am')
        )
        return {str(a['ware']): a['letzte_ausleihe'] for a in letzte_ausleihen}
    
    @staticmethod
    def create(
        name: str,
        beschreibung: str = '',
        rfid_tag: str = None,
        schranknummer: str = '',
        labor_id: str = None
    ) -> Ware:
        """Erstellt eine neue Ware."""
        return Ware.objects.create(
            name=name,
            beschreibung=beschreibung,
            rfid_tag=rfid_tag,
            schranknummer=schranknummer,
            labor_id=labor_id
        )
    
    @staticmethod
    def update(ware: Ware, **kwargs) -> Ware:
        """Aktualisiert eine Ware."""
        for key, value in kwargs.items():
            if hasattr(ware, key):
                setattr(ware, key, value)
        ware.save()
        return ware
    
    @staticmethod
    def set_kategorien(ware: Ware, kategorie_ids: List[str]) -> None:
        """Setzt die Kategorien einer Ware."""
        ware.kategorien.set(kategorie_ids)
    
    @staticmethod
    def deactivate(ware: Ware) -> None:
        """Deaktiviert eine Ware (soft delete)."""
        ware.aktiv = False
        ware.save()
    
    @staticmethod
    def to_dict(ware: Ware, erlaubte_orte: List[str] = None, letzte_ausleihe: str = None) -> dict:
        """Konvertiert eine Ware in ein Dictionary."""
        kategorien = [{'id': str(k.id), 'name': k.name} for k in ware.kategorien.all()]
        
        return {
            'id': str(ware.id),
            'name': ware.name,
            'beschreibung': ware.beschreibung,
            'kategorien': kategorien,
            'kategorie_ids': [str(k.id) for k in ware.kategorien.all()],
            'rfid_tag': ware.rfid_tag,
            'schranknummer': ware.schranknummer,
            'ist_ausgeliehen': ware.ist_ausgeliehen,
            'ist_gesperrt': ware.ist_gesperrt,
            'sperr_grund': ware.sperr_grund if ware.ist_gesperrt else None,
            'verfuegbar': ware.ist_verfuegbar() and (erlaubte_orte is None or len(erlaubte_orte) > 0),
            'erlaubte_verbleib_orte': erlaubte_orte or [],
            'erstellt_am': ware.erstellt_am.isoformat() if ware.erstellt_am else None,
            'letzte_ausleihe': letzte_ausleihe,
        }
