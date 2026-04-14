"""
Hilfsfunktionen für Views.
"""
import uuid
from ..models import Benutzer, AusleiheLog, ErlaubteEmailDomain


def get_client_info(request):
    """Extrahiert Geräteinformationen aus dem Request."""
    return {
        'device_info': request.headers.get('User-Agent', '')[:500],
        'ip_address': request.META.get('REMOTE_ADDR', '')
    }


def log_action(request, aktion, ware=None, ausleihe=None, details=None):
    """Loggt eine Aktion im AusleiheLog."""
    try:
        user_id = uuid.UUID(request.user_id) if hasattr(request, 'user_id') else None
        benutzer = Benutzer.objects.get(id=user_id) if user_id else None
        
        client_info = get_client_info(request)
        
        AusleiheLog.objects.create(
            benutzer=benutzer,
            benutzer_id_logged=user_id,
            ware=ware,
            ware_id_logged=ware.id if ware else None,
            ausleihe=ausleihe,
            aktion=aktion,
            methode='api',
            details=details or {},
            ip_address=client_info['ip_address'],
            device_info=client_info['device_info']
        )
    except Exception:
        pass  # Logging sollte nicht den Hauptablauf stören


def validate_email_domain(email):
    """
    Prüft ob die E-Mail eine erlaubte Domain hat.
    Die erlaubten Domains werden aus der Datenbank geladen.
    Wenn keine Domains konfiguriert sind, sind alle Domains erlaubt.
    """
    if not email:
        return False, 'E-Mail ist erforderlich'
    
    email = email.lower().strip()
    
    # Lade erlaubte Domains aus der Datenbank
    allowed_domains = list(ErlaubteEmailDomain.objects.filter(aktiv=True).values_list('domain', flat=True))
    
    # Wenn keine Domains konfiguriert, sind alle Domains erlaubt
    if not allowed_domains:
        return True, None
    
    if not any(email.endswith(domain) for domain in allowed_domains):
        domains_str = ', '.join(allowed_domains)
        return False, f'Nur E-Mail-Adressen mit folgenden Endungen sind erlaubt: {domains_str}'
    
    return True, None


def get_role_level(rolle):
    """Gibt die Hierarchie-Stufe einer Rolle zurück."""
    levels = {
        'Student': 1,
        'Mitarbeiter': 2,
        'Laborleiter': 3,
        'Admin': 4
    }
    return levels.get(rolle, 0)
