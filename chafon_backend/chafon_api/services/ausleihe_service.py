"""
Ausleihe Service für Ausleih-Logik.
"""
from datetime import datetime
from typing import Optional, Tuple, List
from ..models import Ausleihe, Ware, Benutzer, VerbleibOrt, KategorieVerbleibRegel
from ..repositories import AusleiheRepository, WareRepository, BenutzerRepository
from ..utils.helpers import log_action


class AusleiheService:
    """Service für Ausleihe-Operationen."""
    
    @staticmethod
    def get_ausleihen_liste(
        user_id: str,
        user_role: str,
        status_filter: str = None,
        meine_only: bool = False
    ) -> List[dict]:
        """
        Holt die Liste der Ausleihen.
        """
        # Base QuerySet
        ausleihen = AusleiheRepository.get_with_prefetch()
        
        # Filter anwenden
        if meine_only:
            ausleihen = ausleihen.filter(benutzer_id=user_id)
        
        if status_filter:
            ausleihen = AusleiheRepository.filter_by_status(ausleihen, status_filter)
        
        # Konvertieren mit Anonymisierung für Studenten
        is_student = user_role == 'Student'
        return AusleiheRepository.list_to_dict(
            ausleihen,
            current_user_id=user_id,
            is_student=is_student
        )
    
    @staticmethod
    def create_ausleihe(
        request,
        ware_id: str,
        geplante_rueckgabe: str = None,
        verbleib_ort_name: str = '',
        notiz: str = ''
    ) -> Tuple[bool, dict]:
        """
        Erstellt eine neue Ausleihe.
        """
        # Ware prüfen
        ware = WareRepository.get_by_id(ware_id)
        if not ware:
            return False, {'error': 'Ware nicht gefunden'}
        
        # Benutzer holen
        benutzer = BenutzerRepository.get_by_id(request.user_id)
        
        # Verbleib-Ort Objekt finden
        verbleib_ort_obj = None
        if verbleib_ort_name:
            try:
                verbleib_ort_obj = VerbleibOrt.objects.get(name=verbleib_ort_name, aktiv=True)
            except VerbleibOrt.DoesNotExist:
                pass
        
        # Berechtigung prüfen
        kann_ausleihen, grund = ware.kann_ausgeliehen_werden_von(
            benutzer,
            verbleib_ort=verbleib_ort_obj
        )
        if not kann_ausleihen:
            return False, {'error': grund}
        
        # Maximale Leihdauer prüfen
        if verbleib_ort_obj:
            kategorie = ware.kategorien.first()
            if kategorie:
                try:
                    regel = KategorieVerbleibRegel.objects.get(
                        kategorie=kategorie,
                        verbleib_ort=verbleib_ort_obj
                    )
                    if regel.maximale_leihdauer_tage and geplante_rueckgabe:
                        rueckgabe_datum = datetime.strptime(geplante_rueckgabe, '%Y-%m-%d').date()
                        heute = datetime.now().date()
                        tage = (rueckgabe_datum - heute).days
                        if tage > regel.maximale_leihdauer_tage:
                            return False, {
                                'error': f'Maximale Ausleihdauer für diesen Ort: {regel.maximale_leihdauer_tage} Tage'
                            }
                except KategorieVerbleibRegel.DoesNotExist:
                    pass
        
        # Ausleihe erstellen
        ausleihe = AusleiheRepository.create(
            ware=ware,
            benutzer=benutzer,
            geplante_rueckgabe=geplante_rueckgabe,
            verbleib_ort=verbleib_ort_name,
            notiz=notiz
        )
        
        # Ware als ausgeliehen markieren
        ware.ist_ausgeliehen = True
        ware.save()
        
        log_action(request, 'ausleihe_erstellt', ware=ware, ausleihe=ausleihe)
        
        return True, {
            'success': True,
            'id': str(ausleihe.id),
            'message': 'Ware ausgeliehen'
        }
    
    @staticmethod
    def beantrage_rueckgabe(request, ausleihe_id: str) -> Tuple[bool, dict]:
        """
        Beantragt die Rückgabe einer Ausleihe.
        """
        ausleihe = AusleiheRepository.get_by_id(ausleihe_id)
        if not ausleihe:
            return False, {'error': 'Ausleihe nicht gefunden'}
        
        # Berechtigung prüfen (nur eigene Ausleihe oder Laborleiter+)
        if str(ausleihe.benutzer.id) != request.user_id and request.user_role not in ['Laborleiter', 'Admin']:
            return False, {'error': 'Keine Berechtigung'}
        
        AusleiheRepository.update_status(ausleihe, 'rueckgabe_beantragt')
        
        log_action(request, 'rueckgabe_beantragt', ware=ausleihe.ware, ausleihe=ausleihe)
        
        return True, {'success': True, 'message': 'Rückgabe beantragt'}
    
    @staticmethod
    def quittiere_rueckgabe(
        request,
        ausleihe_id: str,
        schadensmeldung: str = None
    ) -> Tuple[bool, dict]:
        """
        Quittiert die Rückgabe einer Ausleihe.
        """
        ausleihe = AusleiheRepository.get_by_id(ausleihe_id)
        if not ausleihe:
            return False, {'error': 'Ausleihe nicht gefunden'}
        
        # Nur Laborleiter+ dürfen quittieren
        if request.user_role not in ['Laborleiter', 'Admin']:
            return False, {'error': 'Nur Laborleiter oder Admin können Rückgaben quittieren'}
        
        AusleiheRepository.complete_return(ausleihe, schadensmeldung)
        
        log_action(request, 'rueckgabe_quittiert', ware=ausleihe.ware, ausleihe=ausleihe, details={
            'schadensmeldung': schadensmeldung
        })
        
        return True, {'success': True, 'message': 'Rückgabe quittiert'}
    
    @staticmethod
    def markiere_als_verschwunden(request, ausleihe_id: str) -> Tuple[bool, dict]:
        """
        Markiert eine Ausleihe als verschwunden.
        """
        ausleihe = AusleiheRepository.get_by_id(ausleihe_id)
        if not ausleihe:
            return False, {'error': 'Ausleihe nicht gefunden'}
        
        if request.user_role not in ['Laborleiter', 'Admin']:
            return False, {'error': 'Nur Laborleiter oder Admin'}
        
        AusleiheRepository.update_status(ausleihe, 'verschwunden')
        
        # Ware bleibt ausgeliehen (soft-delete)
        log_action(request, 'als_verschwunden_markiert', ware=ausleihe.ware, ausleihe=ausleihe)
        
        return True, {'success': True, 'message': 'Als verschwunden markiert'}
