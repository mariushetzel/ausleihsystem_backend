"""
Ware Service für Warenverwaltung.
"""
from typing import Optional, Tuple, List
from ..models import Benutzer, Ausleihe
from ..repositories import WareRepository, BenutzerRepository
from ..utils.helpers import log_action


class WareService:
    """Service für Ware-Operationen."""
    
    @staticmethod
    def get_waren_liste(
        user_id: str,
        kategorie_id: str = None,
        verfuegbar_only: bool = False,
        offset: int = 0,
        limit: int = 100
    ) -> dict:
        """
        Holt die Liste der Waren mit Pagination.
        """
        # Limit begrenzen
        limit = min(limit, 500)
        
        # Base QuerySet
        waren = WareRepository.get_all_active()
        
        # Filter anwenden
        if kategorie_id:
            waren = WareRepository.filter_by_kategorie(waren, kategorie_id)
        if verfuegbar_only:
            waren = WareRepository.filter_verfuegbar(waren)
        
        # Gesamtanzahl
        total_count = waren.count()
        
        # Pagination
        waren_page = WareRepository.get_paginated(waren, offset, limit)
        
        # Benutzer für Berechtigungsprüfung
        benutzer = BenutzerRepository.get_by_id(user_id)
        
        # Letzte Ausleihen laden
        letzte_ausleihe_map = WareRepository.get_letzte_ausleihen(waren_page)
        
        # Daten aufbereiten
        data = []
        for ware in waren_page:
            erlaubte_orte = []
            if benutzer:
                erlaubte_orte = [o.name for o in ware.get_erlaubte_verbleib_orte(benutzer.rolle)]
            
            ware_dict = WareRepository.to_dict(
                ware,
                erlaubte_orte=erlaubte_orte,
                letzte_ausleihe=letzte_ausleihe_map.get(str(ware.id))
            )
            data.append(ware_dict)
        
        return {
            'waren': data,
            'total': total_count,
            'limit': limit,
            'offset': offset,
            'has_more': offset + len(data) < total_count
        }
    
    @staticmethod
    def create_ware(
        request,
        name: str,
        beschreibung: str = '',
        rfid_tag: str = None,
        schranknummer: str = '',
        labor_id: str = None,
        kategorie_ids: List[str] = None
    ) -> Tuple[bool, dict]:
        """
        Erstellt eine neue Ware.
        """
        # Berechtigungsprüfung
        if request.user_role not in ['Mitarbeiter', 'Laborleiter', 'Admin']:
            return False, {'error': 'Nur Mitarbeiter, Laborleiter oder Admin'}
        
        ware = WareRepository.create(
            name=name,
            beschreibung=beschreibung,
            rfid_tag=rfid_tag,
            schranknummer=schranknummer,
            labor_id=labor_id
        )
        
        # Kategorien zuweisen
        if kategorie_ids:
            WareRepository.set_kategorien(ware, kategorie_ids)
        
        log_action(request, 'ware_erstellt', ware=ware)
        
        return True, {
            'success': True,
            'id': str(ware.id),
            'message': 'Ware erstellt'
        }
    
    @staticmethod
    def update_ware(
        request,
        ware_id: str,
        **kwargs
    ) -> Tuple[bool, dict]:
        """
        Aktualisiert eine Ware.
        """
        ware = WareRepository.get_by_id(ware_id)
        if not ware:
            return False, {'error': 'Ware nicht gefunden'}
        
        # Kategorie_ids separat behandeln
        kategorie_ids = kwargs.pop('kategorie_ids', None)
        
        WareRepository.update(ware, **kwargs)
        
        if kategorie_ids is not None:
            WareRepository.set_kategorien(ware, kategorie_ids)
        
        log_action(request, 'ware_aktualisiert', ware=ware, details={
            'felder': list(kwargs.keys())
        })
        
        return True, {'success': True, 'message': 'Ware aktualisiert'}
    
    @staticmethod
    def delete_ware(request, ware_id: str) -> Tuple[bool, dict]:
        """
        Deaktiviert eine Ware (soft delete).
        """
        ware = WareRepository.get_by_id(ware_id)
        if not ware:
            return False, {'error': 'Ware nicht gefunden'}
        
        WareRepository.deactivate(ware)
        
        log_action(request, 'ware_deaktiviert', ware=ware)
        
        return True, {'success': True, 'message': 'Ware deaktiviert'}
    
    @staticmethod
    def get_ware_detail(ware_id: str, user_id: str = None) -> Optional[dict]:
        """
        Holt Details einer einzelnen Ware.
        """
        ware = WareRepository.get_by_id(ware_id)
        if not ware:
            return None
        
        benutzer = BenutzerRepository.get_by_id(user_id) if user_id else None
        erlaubte_orte = []
        
        if benutzer:
            erlaubte_orte = [o.name for o in ware.get_erlaubte_verbleib_orte(benutzer.rolle)]
        
        result = WareRepository.to_dict(ware, erlaubte_orte=erlaubte_orte)
        
        # Aktuelle Ausleihe laden falls vorhanden
        if ware.ist_ausgeliehen:
            aktuelle_ausleihe = Ausleihe.objects.filter(
                ware=ware,
                status__in=['aktiv', 'rueckgabe_beantragt']
            ).select_related('benutzer').first()
            
            if aktuelle_ausleihe:
                result['aktuelle_ausleihe'] = {
                    'id': str(aktuelle_ausleihe.id),
                    'benutzer_name': f"{aktuelle_ausleihe.benutzer.vorname} {aktuelle_ausleihe.benutzer.nachname}",
                    'benutzer_email': aktuelle_ausleihe.benutzer.email,
                    'verbleib_ort': aktuelle_ausleihe.verbleib_ort,
                    'geplante_rueckgabe': aktuelle_ausleihe.geplante_rueckgabe.isoformat() if aktuelle_ausleihe.geplante_rueckgabe else None,
                    'ausgeliehen_am': aktuelle_ausleihe.ausgeliehen_am.isoformat() if aktuelle_ausleihe.ausgeliehen_am else None,
                    'status': aktuelle_ausleihe.status,
                }
            else:
                result['aktuelle_ausleihe'] = None
        else:
            result['aktuelle_ausleihe'] = None
        
        return result
