"""
Ausleihsystem API Views mit JWT-Authentifizierung.
"""

import uuid
from datetime import datetime
from functools import wraps

import jwt
from django.db import IntegrityError
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from . import jwt_utils
from .models import (
    Benutzer, Ware, Warenkategorie, VerbleibOrt, Ausleihe,
    AusleiheHistorie, AusleiheLog, AntennenEinstellung, ErlaubteEmailDomain,
    KategorieVerbleibRegel, Schadensmeldung, SystemEinstellung
)
from .ant_task import InventoryThread
from .card_task import CardThread
from .reader import UHFReader

# NEU: Redis-basierter HardwareManager (ersetzt globalen Zustand)
from .utils import HardwareManager

# Global State für RFID-Reader (prozess-lokal, wird pro Session verwaltet)
# Diese bleiben bestehen, da sie pro-Prozess Hardware-Handles sind
reader = None
inventory_thread = None
current_cardthread = None
work_mode = None

# Hardware-Locking - jetzt über Redis für distributed locking
# Alte globale Variablen entfernt - werden durch HardwareManager ersetzt
def acquire_hardware_lock(user_id, session_id, device_type='rfid'):
    """
    Versucht den Hardware-Lock zu erhalten.
    Gibt (success, message) zurück.
    """
    # NEU: Verwende Redis-basierten HardwareManager
    return HardwareManager.acquire_lock(user_id, session_id, device_type)
    if hardware_lock['locked_by'] and hardware_lock['locked_at']:
        lock_age = datetime.now() - hardware_lock['locked_at']
        if lock_age < timedelta(seconds=30):
            if hardware_lock['locked_by'] != user_id:
                return False, f"Hardware wird bereits verwendet (User: {hardware_lock['locked_by']}, Gerät: {hardware_lock.get('device_type', 'unbekannt')})"
        else:
            # Lock ist abgelaufen, freigeben
            hardware_lock['locked_by'] = None
            hardware_lock['locked_at'] = None
            # Lock abgelaufen - HardwareManager (Redis) löst das automatisch
            pass
    
    # Lock setzen über HardwareManager
    return HardwareManager.acquire_lock(user_id, session_id, device_type)

def release_hardware_lock(user_id, session_id):
    """
    Gibt den Hardware-Lock frei.
    """
    return HardwareManager.release_lock(user_id, session_id)

def is_hardware_locked():
    """
    Prüft ob die Hardware verwendet wird.
    Gibt (locked, info) zurück.
    """
    return HardwareManager.is_locked('rfid')

# Legacy-Funktionen für Abwärtskompatibilität (RFID)
def acquire_scan_lock(user_id, session_id):
    return HardwareManager.acquire_lock(user_id, session_id, 'rfid')

def release_scan_lock(user_id, session_id):
    return HardwareManager.release_lock(user_id, session_id)

def is_scanning_locked():
    locked, info = HardwareManager.is_locked('rfid')
    if info and info.get('device_type') != 'rfid':
        return False, None  # Nur RFID-Lock zählt für alte Funktionen
    return locked, info


# =============================================================================
# HILFSFUNKTIONEN & DECORATORS
# =============================================================================

def get_auth_header(request):
    """Extrahiert das Bearer Token aus dem Authorization Header."""
    auth_header = request.headers.get('Authorization', '')
    if auth_header.startswith('Bearer '):
        return auth_header[7:]
    return None


def jwt_required(view_func):
    """Decorator: Prüft JWT-Token und fügt request.user hinzu."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        token = get_auth_header(request)
        if not token:
            return Response({'error': 'Authorization Header fehlt'}, status=401)
        
        try:
            payload = jwt_utils.verify_access_token(token)
            request.user_id = payload.get('sub')
            request.user_role = payload.get('rolle')
            request.user_payload = payload
            return view_func(request, *args, **kwargs)
        except jwt.ExpiredSignatureError:
            return Response({'error': 'Token abgelaufen'}, status=401)
        except jwt.InvalidTokenError as e:
            return Response({'error': f'Ungültiger Token: {str(e)}'}, status=401)
        except ValueError as e:
            return Response({'error': str(e)}, status=401)
    return wrapper


def require_role(roles):
    """Decorator: Prüft ob Benutzer eine der erforderlichen Rollen hat."""
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if not hasattr(request, 'user_role'):
                return Response({'error': 'Authentifizierung erforderlich'}, status=401)
            
            if request.user_role not in roles:
                return Response(
                    {'error': f'Rolle "{request.user_role}" nicht berechtigt. Benötigt: {roles}'},
                    status=403
                )
            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator


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
        
        AusleiheLog.objects.create(
            benutzer=benutzer,
            benutzer_id_logged=user_id,
            ware=ware,
            ware_id_logged=ware.id if ware else None,
            ausleihe=ausleihe,
            aktion=aktion,
            methode='api',
            details=details or {},
            ip_address=get_client_info(request)['ip_address'],
            device_info=get_client_info(request)['device_info']
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


# =============================================================================
# AUTHENTIFIZIERUNG (JWT)
# =============================================================================

@api_view(['POST'])
@permission_classes([AllowAny])
def register(request):
    """
    Öffentliche Registrierung für neue Benutzer.
    Erstellt Benutzer immer mit Rolle 'Student'.
    Optional: RFID-Karte kann direkt hinterlegt werden.
    """
    data = request.data
    
    try:
        # E-Mail Validierung (nur TH-Köln Domains)
        is_valid, error_msg = validate_email_domain(data.get('email'))
        if not is_valid:
            return Response({'error': error_msg}, status=400)
        
        email = data['email'].lower().strip()
        
        # Prüfen ob E-Mail bereits existiert
        if Benutzer.objects.filter(email=email, aktiv=True).exists():
            return Response({'error': 'E-Mail bereits registriert'}, status=400)
        
        # Prüfen ob RFID-Karte bereits vergeben ist (falls angegeben)
        rfid_karte = data.get('rfid_karte')
        if rfid_karte:
            if Benutzer.objects.filter(rfid_karte=rfid_karte, aktiv=True).exists():
                return Response({'error': 'Diese Karte ist bereits einem anderen Benutzer zugeordnet'}, status=400)
        
        # Passwort hashen
        import bcrypt
        passwort_hash = bcrypt.hashpw(data['passwort'].encode(), bcrypt.gensalt()).decode()
        
        benutzer = Benutzer.objects.create(
            email=email,
            passwort_hash=passwort_hash,
            vorname=data['vorname'],
            nachname=data['nachname'],
            rolle='Student',  # Immer Student für öffentliche Registrierung
            rfid_karte=rfid_karte,
        )
        
        return Response({
            'success': True,
            'id': str(benutzer.id),
            'message': 'Registrierung erfolgreich'
        }, status=201)
        
    except Exception as e:
        return Response({'error': str(e)}, status=400)


@api_view(['POST'])
@permission_classes([AllowAny])
def login(request):
    """
    Login mit RFID-Karte oder E-Mail/Passwort.
    Gibt JWT-Token-Paar zurück.
    """
    data = request.data
    
    # Login-Methode bestimmen
    rfid_karte = data.get('rfid_karte')
    email = data.get('email')
    passwort = data.get('passwort')
    
    try:
        if rfid_karte:
            # Login per RFID
            benutzer = Benutzer.objects.get(rfid_karte=rfid_karte, aktiv=True)
        elif email and passwort:
            # Login per E-Mail/Passwort
            benutzer = Benutzer.objects.get(email=email, aktiv=True)
            # Prüfen ob User nur per Karte angelegt wurde
            import bcrypt
            if benutzer.passwort_hash and '__KARTEN_LOGIN_ONLY__' in benutzer.passwort_hash:
                return Response({
                    'error': 'Bitte melden Sie sich mit Ihrer Karte an und setzen Sie ein Passwort im Profil'
                }, status=401)
            # Passwort prüfen (bcrypt)
            if not bcrypt.checkpw(passwort.encode(), benutzer.passwort_hash.encode()):
                return Response({'error': 'Ungültige Anmeldedaten'}, status=401)
        else:
            return Response({'error': 'RFID-Karte oder E-Mail/Passwort erforderlich'}, status=400)
        
        # Token-Paar erstellen
        client_info = get_client_info(request)
        tokens = jwt_utils.create_token_pair(benutzer, **client_info)
        
        # Login loggen
        log_action(request, 'login', details={'methode': 'rfid' if rfid_karte else 'password'})
        
        return Response({
            'success': True,
            'user': {
                'id': str(benutzer.id),
                'vorname': benutzer.vorname,
                'nachname': benutzer.nachname,
                'email': benutzer.email,
                'rolle': benutzer.rolle,
            },
            **tokens
        })
        
    except Benutzer.DoesNotExist:
        return Response({'error': 'Benutzer nicht gefunden'}, status=401)


@api_view(['POST'])
def logout(request):
    """Logout: Widerruft das aktuelle Token-Paar."""
    token = get_auth_header(request)
    if token:
        try:
            payload = jwt.decode(token, options={"verify_signature": False})
            jti = payload.get('jti')
            if jti:
                from .models import TokenPair
                TokenPair.objects.filter(access_token_jti=jti).update(
                    revoked=True,
                    revoked_at=timezone.now(),
                    revoked_reason='logout'
                )
        except:
            pass
    
    return Response({'success': True, 'message': 'Ausgeloggt'})


@api_view(['POST'])
@permission_classes([AllowAny])
def refresh_token(request):
    """Erstellt neues Token-Paar mit Refresh Token."""
    refresh_token_str = request.data.get('refresh_token')
    if not refresh_token_str:
        return Response({'error': 'Refresh Token fehlt'}, status=400)
    
    try:
        client_info = get_client_info(request)
        tokens = jwt_utils.refresh_access_token(refresh_token_str, **client_info)
        return Response({
            'success': True,
            **tokens
        })
    except jwt.ExpiredSignatureError:
        return Response({'error': 'Refresh Token abgelaufen'}, status=401)
    except (jwt.InvalidTokenError, ValueError) as e:
        return Response({'error': str(e)}, status=401)


@api_view(['GET'])
@jwt_required
def me(request):
    """Gibt aktuellen Benutzer zurück."""
    try:
        benutzer = Benutzer.objects.get(id=request.user_id)
        return Response({
            'id': str(benutzer.id),
            'vorname': benutzer.vorname,
            'nachname': benutzer.nachname,
            'email': benutzer.email,
            'rolle': benutzer.rolle,
            'rfid_karte': benutzer.rfid_karte,
            'letzter_login': benutzer.letzter_login,
        })
    except Benutzer.DoesNotExist:
        return Response({'error': 'Benutzer nicht gefunden'}, status=404)


# =============================================================================
# BENUTZER-VERWALTUNG (Admin)
# =============================================================================

# Rollen-Hierarchie für Berechtigungsprüfungen
ROLE_HIERARCHY = {
    'Student': 1,
    'Mitarbeiter': 2,
    'Laborleiter': 3,
    'Admin': 4
}


def get_role_level(rolle):
    """Gibt den Hierarchie-Level einer Rolle zurück."""
    return ROLE_HIERARCHY.get(rolle, 0)


@api_view(['GET', 'POST'])
@jwt_required
@require_role(['Mitarbeiter', 'Laborleiter', 'Admin'])
def benutzer_liste(request):
    """Liste aller Benutzer oder neuen Benutzer erstellen."""
    current_user_level = get_role_level(request.user_role)
    
    if request.method == 'GET':
        # Mitarbeiter sehen nur Benutzer mit niedrigerer Rolle
        if request.user_role == 'Mitarbeiter':
            benutzer = Benutzer.objects.filter(aktiv=True, rolle='Student')
        else:
            # Laborleiter und Admin sehen alle
            benutzer = Benutzer.objects.filter(aktiv=True)
            
        data = [{
            'id': str(b.id),
            'vorname': b.vorname,
            'nachname': b.nachname,
            'email': b.email,
            'rolle': b.rolle,
            'rfid_karte': b.rfid_karte,
            'hat_passwort': b.hat_passwort(),
            'hat_karte': bool(b.rfid_karte),
        } for b in benutzer]
        return Response(data)
    
    elif request.method == 'POST':
        data = request.data
        
        # E-Mail Validierung (nur TH-Köln Domains)
        is_valid, error_msg = validate_email_domain(data.get('email'))
        if not is_valid:
            return Response({'error': error_msg}, status=400)
        
        email = data['email'].lower().strip()
        requested_rolle = data.get('rolle', 'Student')
        requested_level = get_role_level(requested_rolle)
        
        # Mitarbeiter dürfen nur Studenten anlegen (Rolle < eigene Rolle)
        if request.user_role == 'Mitarbeiter' and requested_level >= current_user_level:
            return Response(
                {'error': 'Mitarbeiter dürfen nur Benutzer mit Rolle "Student" anlegen'},
                status=403
            )
        
        # Laborleiter dürfen keine gleich/höhere Rollen vergeben
        if request.user_role == 'Laborleiter' and requested_level >= current_user_level:
            return Response(
                {'error': f'Laborleiter dürfen keine Rolle "{requested_rolle}" vergeben'},
                status=403
            )
        
        # Passwort optional - wenn nicht angegeben, muss sich User per Karte anmelden
        import bcrypt
        passwort = data.get('passwort')
        if passwort:
            passwort_hash = bcrypt.hashpw(passwort.encode(), bcrypt.gensalt()).decode()
        else:
            # Temporäres Passwort (User muss sich per Karte anmelden und dann Passwort setzen)
            passwort_hash = bcrypt.hashpw('__KARTEN_LOGIN_ONLY__'.encode(), bcrypt.gensalt()).decode()
        
        benutzer = Benutzer.objects.create(
            email=email,
            passwort_hash=passwort_hash,
            vorname=data['vorname'],
            nachname=data['nachname'],
            rolle=requested_rolle,
            rfid_karte=data.get('rfid_karte'),
            labor_id=data.get('labor_id'),
        )
        
        log_action(request, 'benutzer_erstellt', details={
            'neuer_benutzer_id': str(benutzer.id),
            'rolle': requested_rolle,
            'mit_passwort': bool(passwort)
        })
        
        return Response({
            'success': True,
            'id': str(benutzer.id),
            'message': 'Benutzer erstellt' + ('' if passwort else ' - Login per Karte möglich')
        }, status=201)


@api_view(['GET', 'PUT', 'DELETE'])
@jwt_required
def benutzer_detail(request, benutzer_id):
    """Einzelnen Benutzer anzeigen, bearbeiten oder deaktivieren."""
    current_user_level = get_role_level(request.user_role)
    
    try:
        benutzer = Benutzer.objects.get(id=benutzer_id, aktiv=True)
    except Benutzer.DoesNotExist:
        return Response({'error': 'Benutzer nicht gefunden'}, status=404)
    
    target_user_level = get_role_level(benutzer.rolle)
    is_self_edit = str(benutzer.id) == request.user_id
    
    # DELETE nur für Mitarbeiter+
    if request.method == 'DELETE' and request.user_role == 'Student':
        return Response({'error': 'Studenten dürfen keine Benutzer löschen'}, status=403)
    
    # Bei Selbstbearbeitung: Immer erlaubt (außer Rollenerhöhung wird später geprüft)
    # Bei Fremdbearbeitung: Mitarbeiter dürfen nur Studenten bearbeiten
    if not is_self_edit:
        # Studenten dürfen nur sich selbst bearbeiten
        if request.user_role == 'Student':
            return Response(
                {'error': 'Studenten dürfen nur ihr eigenes Profil bearbeiten'},
                status=403
            )
        if request.user_role == 'Mitarbeiter' and target_user_level >= current_user_level:
            return Response(
                {'error': 'Mitarbeiter dürfen nur Benutzer mit Rolle "Student" bearbeiten'},
                status=403
            )
    
    if request.method == 'GET':
        return Response({
            'id': str(benutzer.id),
            'vorname': benutzer.vorname,
            'nachname': benutzer.nachname,
            'email': benutzer.email,
            'rolle': benutzer.rolle,
            'rfid_karte': benutzer.rfid_karte,
            'labor_id': str(benutzer.labor_id) if benutzer.labor_id else None,
            'aktiv': benutzer.aktiv,
            'letzter_login': benutzer.letzter_login,
        })
    
    elif request.method == 'PUT':
        data = request.data
        
        # Neue E-Mail prüfen (falls geändert)
        new_email = data.get('email', benutzer.email)
        if new_email != benutzer.email:
            is_valid, error_msg = validate_email_domain(new_email)
            if not is_valid:
                return Response({'error': error_msg}, status=400)
            new_email = new_email.lower().strip()
        
        # Neue Rolle prüfen (falls geändert)
        new_rolle = data.get('rolle', benutzer.rolle)
        new_level = get_role_level(new_rolle)
        
        # Prüfen ob Benutzer sich selbst bearbeitet
        is_self_edit = str(benutzer.id) == request.user_id
        
        if is_self_edit:
            # Eigene Rolle darf nicht erhöht werden (aber gleich bleiben oder runter)
            if new_level > current_user_level:
                return Response(
                    {'error': 'Sie können Ihre eigene Rolle nicht erhöhen'},
                    status=403
                )
        else:
            # Andere Benutzer dürfen nur Rollen unter der eigenen bekommen
            if new_level >= current_user_level:
                return Response(
                    {'error': f'Sie dürfen keine Rolle "{new_rolle}" vergeben'},
                    status=403
                )
        
        benutzer.vorname = data.get('vorname', benutzer.vorname)
        benutzer.nachname = data.get('nachname', benutzer.nachname)
        benutzer.email = new_email
        benutzer.rolle = new_rolle
        benutzer.rfid_karte = data.get('rfid_karte', benutzer.rfid_karte)
        
        if 'passwort' in data:
            import bcrypt
            benutzer.passwort_hash = bcrypt.hashpw(data['passwort'].encode(), bcrypt.gensalt()).decode()
        
        benutzer.save()
        
        log_action(request, 'benutzer_aktualisiert', details={'benutzer_id': str(benutzer.id)})
        
        return Response({'success': True, 'message': 'Benutzer aktualisiert'})
    
    elif request.method == 'DELETE':
        # Mitarbeiter dürfen nur Studenten löschen
        if request.user_role == 'Mitarbeiter' and target_user_level >= current_user_level:
            return Response(
                {'error': 'Mitarbeiter dürfen nur Benutzer mit Rolle "Student" deaktivieren'},
                status=403
            )
        
        # Soft-Delete
        benutzer.aktiv = False
        benutzer.save()
        
        # Alle Tokens widerrufen
        jwt_utils.revoke_all_user_tokens(str(benutzer.id), 'user_deactivated')
        
        log_action(request, 'benutzer_deaktiviert', details={'benutzer_id': str(benutzer.id)})
        
        return Response({'success': True, 'message': 'Benutzer deaktiviert'})


@api_view(['GET'])
@jwt_required
@require_role(['Mitarbeiter', 'Laborleiter', 'Admin'])
def check_card(request, rfid_karte):
    """
    Prüft ob eine RFID-Karte bereits einem Benutzer zugeordnet ist.
    Wird verwendet um doppelte Karten zu verhindern.
    """
    try:
        benutzer = Benutzer.objects.get(rfid_karte=rfid_karte, aktiv=True)
        return Response({
            'vergeben': True,
            'benutzer': {
                'id': str(benutzer.id),
                'vorname': benutzer.vorname,
                'nachname': benutzer.nachname,
                'email': benutzer.email,
            }
        })
    except Benutzer.DoesNotExist:
        return Response({
            'vergeben': False,
            'benutzer': None
        })


# =============================================================================
# WAREN
# =============================================================================

@api_view(['GET', 'POST'])
@jwt_required
def waren_liste(request):
    """Alle Waren anzeigen oder neue Ware erstellen. Mit Pagination."""
    # Studenten dürfen keine Waren erstellen
    if request.method == 'POST' and request.user_role == 'Student':
        return Response({'error': 'Studenten dürfen keine Waren erstellen'}, status=403)
    
    if request.method == 'GET':
        # Filter
        kategorie_id = request.query_params.get('kategorie')
        verfuegbar = request.query_params.get('verfuegbar')
        
        # Pagination Parameter
        try:
            limit = int(request.query_params.get('limit', 100))  # Default: 100
            offset = int(request.query_params.get('offset', 0))   # Default: 0
        except ValueError:
            limit = 100
            offset = 0
        
        # Limit auf max 500 begrenzen
        limit = min(limit, 500)
        
        waren = Ware.objects.filter(aktiv=True).prefetch_related('kategorien')
        
        if kategorie_id:
            waren = waren.filter(kategorien__id=kategorie_id)
        if verfuegbar == 'true':
            waren = waren.filter(ist_ausgeliehen=False, ist_gesperrt=False)
        
        # Gesamtanzahl für Pagination
        total_count = waren.count()
        
        # Hole Benutzer für Berechtigungsprüfung
        try:
            benutzer = Benutzer.objects.get(id=request.user_id)
        except Benutzer.DoesNotExist:
            benutzer = None
        
        # Pagination anwenden
        waren_page = waren[offset:offset + limit]
        
        # Hole alle Ausleihen für die letzte-Ausleihe-Abfrage (nur für die aktuelle Page)
        from django.db.models import Max
        letzte_ausleihen = Ausleihe.objects.filter(
            ware__in=waren_page
        ).values('ware').annotate(
            letzte_ausleihe=Max('ausgeliehen_am')
        )
        letzte_ausleihe_map = {str(a['ware']): a['letzte_ausleihe'] for a in letzte_ausleihen}
        
        data = []
        for w in waren_page:
            # Erlaubte Verbleib-Orte für diesen Benutzer
            erlaubte_orte = []
            if benutzer:
                erlaubte_orte = [o.name for o in w.get_erlaubte_verbleib_orte(benutzer.rolle)]
            
            data.append({
                'id': str(w.id),
                'name': w.name,
                'beschreibung': w.beschreibung,
                'kategorien': [{'id': str(k.id), 'name': k.name} for k in w.kategorien.all()],
                'kategorie_ids': [str(k.id) for k in w.kategorien.all()],
                'rfid_tag': w.rfid_tag,
                'schranknummer': w.schranknummer,
                'ist_ausgeliehen': w.ist_ausgeliehen,
                'ist_gesperrt': w.ist_gesperrt,
                'sperr_grund': w.sperr_grund if w.ist_gesperrt else None,
                'verfuegbar': w.ist_verfuegbar() and len(erlaubte_orte) > 0,
                'erlaubte_verbleib_orte': erlaubte_orte,
                'erstellt_am': w.erstellt_am.isoformat() if w.erstellt_am else None,
                'letzte_ausleihe': letzte_ausleihe_map.get(str(w.id), None),
            })
        
        return Response({
            'waren': data,
            'total': total_count,
            'limit': limit,
            'offset': offset,
            'has_more': offset + len(data) < total_count
        })
    
    elif request.method == 'POST':
        # Nur Laborleiter+ dürfen Waren erstellen
        if request.user_role not in ['Laborleiter', 'Admin']:
            return Response({'error': 'Nur Laborleiter oder Admin'}, status=403)
        
        data = request.data
        
        ware = Ware.objects.create(
            name=data['name'],
            beschreibung=data.get('beschreibung', ''),
            rfid_tag=data.get('rfid_tag'),
            schranknummer=data.get('schranknummer', ''),
            labor_id=data.get('labor_id'),
        )
        
        # Kategorien zuweisen (ManyToMany)
        kategorie_ids = data.get('kategorie_ids', [])
        if kategorie_ids:
            ware.kategorien.set(kategorie_ids)
        
        log_action(request, 'ware_erstellt', ware=ware)
        
        return Response({
            'success': True,
            'id': str(ware.id),
            'message': 'Ware erstellt'
        }, status=201)


@api_view(['GET', 'PUT', 'DELETE'])
@jwt_required
def ware_detail(request, ware_id):
    """Einzelne Ware anzeigen, bearbeiten oder löschen."""
    # Studenten dürfen Waren nur ansehen, nicht bearbeiten oder löschen
    if request.method in ['PUT', 'DELETE'] and request.user_role == 'Student':
        return Response({'error': 'Studenten dürfen Waren nicht bearbeiten oder löschen'}, status=403)
    
    try:
        ware = Ware.objects.get(id=ware_id, aktiv=True)
    except Ware.DoesNotExist:
        return Response({'error': 'Ware nicht gefunden'}, status=404)
    
    if request.method == 'GET':
        # Erlaubte Verbleib-Orte für den aktuellen User berechnen
        erlaubte_orte = []
        for kategorie in ware.kategorien.filter(aktiv=True):
            regeln = KategorieVerbleibRegel.objects.filter(
                kategorie=kategorie,
                gesperrt=False
            ).select_related('verbleib_ort')
            
            for regel in regeln:
                if regel.verbleib_ort.aktiv:
                    role_level = {'Student': 1, 'Mitarbeiter': 2, 'Laborleiter': 3, 'Admin': 4}
                    user_level = role_level.get(request.user_role, 1)
                    required_level = role_level.get(regel.minimale_rolle, 1)
                    
                    if user_level >= required_level:
                        erlaubte_orte.append({
                            'id': str(regel.verbleib_ort.id),
                            'name': regel.verbleib_ort.name
                        })
        
        # Duplikate entfernen
        erlaubte_orte = list({o['id']: o for o in erlaubte_orte}.values())
        
        return Response({
            'id': str(ware.id),
            'name': ware.name,
            'beschreibung': ware.beschreibung,
            'kategorien': [{'id': str(k.id), 'name': k.name} for k in ware.kategorien.all()],
            'kategorie_ids': [str(k.id) for k in ware.kategorien.all()],
            'rfid_tag': ware.rfid_tag,
            'schranknummer': ware.schranknummer,
            'ist_ausgeliehen': ware.ist_ausgeliehen,
            'ist_gesperrt': ware.ist_gesperrt,
            'sperr_grund': ware.sperr_grund,
            'verfuegbar': ware.ist_verfuegbar() and len(erlaubte_orte) > 0,
            'erlaubte_verbleib_orte': erlaubte_orte,
            'erstellt_am': ware.erstellt_am.isoformat() if ware.erstellt_am else None,
        })
    
    elif request.method == 'PUT':
        # Alle authentifizierten User dürfen Waren bearbeiten (aber nicht alle Felder)
        data = request.data
        
        # Einschränkungen je nach Rolle
        if request.user_role in ['Laborleiter', 'Admin']:
            # Vollzugriff
            ware.name = data.get('name', ware.name)
            ware.beschreibung = data.get('beschreibung', ware.beschreibung)
            ware.rfid_tag = data.get('rfid_tag', ware.rfid_tag)
            ware.schranknummer = data.get('schranknummer', ware.schranknummer)
            ware.ist_gesperrt = data.get('ist_gesperrt', ware.ist_gesperrt)
            ware.sperr_grund = data.get('sperr_grund', ware.sperr_grund)
            
            # Kategorien aktualisieren (ManyToMany)
            if 'kategorie_ids' in data:
                ware.kategorien.set(data['kategorie_ids'])
        else:
            # Eingeschränkte Bearbeitung
            ware.schranknummer = data.get('schranknummer', ware.schranknummer)
            ware.beschreibung = data.get('beschreibung', ware.beschreibung)
        
        ware.save()
        
        log_action(request, 'ware_aktualisiert', ware=ware)
        
        return Response({'success': True, 'message': 'Ware aktualisiert'})
    
    elif request.method == 'DELETE':
        # Nur Laborleiter+ dürfen Waren löschen
        if request.user_role not in ['Laborleiter', 'Admin']:
            return Response({'error': 'Nur Laborleiter oder Admin'}, status=403)
        
        # Prüfen ob Ware ausgeliehen ist
        if ware.ist_ausgeliehen:
            return Response({'error': 'Ware ist ausgeliehen und kann nicht gelöscht werden'}, status=400)
        
        ware.aktiv = False
        ware.save()
        
        log_action(request, 'ware_deaktiviert', ware=ware)
        
        return Response({'success': True, 'message': 'Ware deaktiviert'})


# =============================================================================
# ERLAUBTE E-MAIL DOMAINS
# =============================================================================

@api_view(['GET', 'POST'])
@jwt_required
def email_domains_liste(request):
    """Erlaubte E-Mail-Domains auflisten oder neue erstellen."""
    if request.method == 'GET':
        domains = ErlaubteEmailDomain.objects.filter(aktiv=True).order_by('domain')
        
        data = [{
            'id': str(d.id),
            'domain': d.domain,
            'beschreibung': d.beschreibung,
        } for d in domains]
        return Response(data)
    
    elif request.method == 'POST':
        # Nur Laborleiter+ dürfen Domains verwalten
        if request.user_role not in ['Laborleiter', 'Admin']:
            return Response({'error': 'Nur Laborleiter oder Admin'}, status=403)
        
        data = request.data
        domain = data.get('domain', '').strip().lower()
        
        if not domain:
            return Response({'error': 'Domain ist erforderlich'}, status=400)
        
        # Domain-Format validieren (muss mit @ beginnen)
        if not domain.startswith('@'):
            return Response({'error': 'Domain muss mit @ beginnen (z.B. @th-koeln.de)'}, status=400)
        
        # Prüfen ob Domain bereits existiert
        existing = ErlaubteEmailDomain.objects.filter(domain__iexact=domain).first()
        if existing:
            if existing.aktiv:
                return Response({
                    'id': str(existing.id),
                    'domain': existing.domain,
                    'existing': True,
                    'message': 'Domain existiert bereits'
                })
            else:
                # Inaktive Domain reaktivieren
                existing.aktiv = True
                existing.beschreibung = data.get('beschreibung', existing.beschreibung)
                existing.save()
                return Response({
                    'id': str(existing.id),
                    'domain': existing.domain,
                    'beschreibung': existing.beschreibung,
                    'existing': False,
                    'message': 'Domain reaktiviert'
                }, status=200)
        
        # Neue Domain erstellen
        neue_domain = ErlaubteEmailDomain.objects.create(
            domain=domain,
            beschreibung=data.get('beschreibung', '')
        )
        
        log_action(request, 'email_domain_erstellt', details={'domain': domain})
        
        return Response({
            'id': str(neue_domain.id),
            'domain': neue_domain.domain,
            'beschreibung': neue_domain.beschreibung,
            'existing': False,
            'message': 'Domain erstellt'
        }, status=201)


@api_view(['PUT', 'DELETE'])
@jwt_required
def email_domain_detail(request, domain_id):
    """E-Mail-Domain bearbeiten oder löschen."""
    # Nur Laborleiter+
    if request.user_role not in ['Laborleiter', 'Admin']:
        return Response({'error': 'Nur Laborleiter oder Admin'}, status=403)
    
    try:
        domain = ErlaubteEmailDomain.objects.get(id=domain_id, aktiv=True)
    except ErlaubteEmailDomain.DoesNotExist:
        return Response({'error': 'Domain nicht gefunden'}, status=404)
    
    if request.method == 'PUT':
        data = request.data
        
        if 'domain' in data:
            new_domain = data['domain'].strip().lower()
            if new_domain and new_domain != domain.domain.lower():
                if not new_domain.startswith('@'):
                    return Response({'error': 'Domain muss mit @ beginnen'}, status=400)
                if ErlaubteEmailDomain.objects.filter(domain__iexact=new_domain, aktiv=True).exclude(id=domain_id).exists():
                    return Response({'error': 'Domain bereits vergeben'}, status=400)
                domain.domain = new_domain
        
        if 'beschreibung' in data:
            domain.beschreibung = data['beschreibung']
        
        domain.save()
        
        log_action(request, 'email_domain_aktualisiert', details={'domain': domain.domain})
        
        return Response({
            'id': str(domain.id),
            'domain': domain.domain,
            'beschreibung': domain.beschreibung,
            'message': 'Domain aktualisiert'
        })
    
    elif request.method == 'DELETE':
        # Soft-Delete
        domain.aktiv = False
        domain.save()
        
        log_action(request, 'email_domain_deaktiviert', details={'domain': domain.domain})
        
        return Response({
            'success': True,
            'message': 'Domain deaktiviert'
        })


# =============================================================================
# KATEGORIEN
# =============================================================================

@api_view(['GET', 'POST'])
@jwt_required
def kategorien_liste(request):
    """Alle Warenkategorien anzeigen oder neue Kategorie erstellen."""
    if request.method == 'GET':
        kategorien = Warenkategorie.objects.filter(aktiv=True)
        data = [{
            'id': str(k.id),
            'name': k.name,
            'beschreibung': k.beschreibung,
            'minimale_rolle': k.minimale_rolle,
        } for k in kategorien]
        return Response(data)
    
    elif request.method == 'POST':
        # Nur Laborleiter+ dürfen Kategorien erstellen
        if request.user_role not in ['Laborleiter', 'Admin']:
            return Response({'error': 'Nur Laborleiter oder Admin'}, status=403)
        
        data = request.data
        name = data.get('name', '').strip()
        
        if not name:
            return Response({'error': 'Name ist erforderlich'}, status=400)
        
        # Prüfen ob Kategorie bereits existiert (Case-Insensitive, auch inaktive)
        existing = Warenkategorie.objects.filter(name__iexact=name).first()
        if existing:
            if existing.aktiv:
                # Aktive Kategorie existiert bereits
                return Response({
                    'id': str(existing.id),
                    'name': existing.name,
                    'beschreibung': existing.beschreibung,
                    'minimale_rolle': existing.minimale_rolle,
                    'existing': True,
                    'message': 'Kategorie existiert bereits'
                })
            else:
                # Inaktive Kategorie reaktivieren
                existing.aktiv = True
                existing.name = name  # Name aktualisieren (Groß-/Kleinschreibung)
                existing.beschreibung = data.get('beschreibung', existing.beschreibung)
                existing.minimale_rolle = data.get('minimale_rolle', existing.minimale_rolle)
                existing.save()
                
                log_action(request, 'kategorie_reaktiviert', details={'kategorie_id': str(existing.id), 'name': existing.name})
                
                return Response({
                    'id': str(existing.id),
                    'name': existing.name,
                    'beschreibung': existing.beschreibung,
                    'minimale_rolle': existing.minimale_rolle,
                    'existing': False,
                    'message': 'Kategorie reaktiviert'
                }, status=200)
        
        # Neue Kategorie erstellen
        kategorie = Warenkategorie.objects.create(
            name=name,
            beschreibung=data.get('beschreibung', ''),
            minimale_rolle=data.get('minimale_rolle', 'Student'),
            labor_id=data.get('labor_id')
        )
        
        log_action(request, 'kategorie_erstellt', details={'kategorie_id': str(kategorie.id), 'name': kategorie.name})
        
        return Response({
            'id': str(kategorie.id),
            'name': kategorie.name,
            'beschreibung': kategorie.beschreibung,
            'minimale_rolle': kategorie.minimale_rolle,
            'existing': False,
            'message': 'Kategorie erstellt'
        }, status=201)


@api_view(['PUT', 'DELETE'])
@jwt_required
def kategorie_detail(request, kategorie_id):
    """Einzelne Kategorie bearbeiten oder deaktivieren."""
    # Nur Laborleiter+ dürfen Kategorien verwalten
    if request.user_role not in ['Laborleiter', 'Admin']:
        return Response({'error': 'Nur Laborleiter oder Admin'}, status=403)
    
    try:
        kategorie = Warenkategorie.objects.get(id=kategorie_id, aktiv=True)
    except Warenkategorie.DoesNotExist:
        return Response({'error': 'Kategorie nicht gefunden'}, status=404)
    
    if request.method == 'PUT':
        data = request.data
        
        # Name aktualisieren (falls geändert)
        new_name = data.get('name', '').strip()
        if new_name and new_name != kategorie.name:
            # Prüfen ob Name bei aktiver Kategorie bereits vergeben ist
            existing_active = Warenkategorie.objects.filter(name__iexact=new_name, aktiv=True).exclude(id=kategorie.id).first()
            if existing_active:
                return Response({'error': f'Name "{new_name}" bereits vergeben'}, status=400)
            
            kategorie.name = new_name
        
        # Qualifikations-Einstellung aktualisieren
        if 'minimale_rolle' in data:
            kategorie.minimale_rolle = data['minimale_rolle']
        
        if 'beschreibung' in data:
            kategorie.beschreibung = data['beschreibung']
        
        try:
            kategorie.save()
        except IntegrityError as e:
            return Response({'error': f'Name bereits vergeben'}, status=400)
        
        log_action(request, 'kategorie_aktualisiert', details={'kategorie_id': str(kategorie.id), 'name': kategorie.name})
        
        return Response({
            'id': str(kategorie.id),
            'name': kategorie.name,
            'beschreibung': kategorie.beschreibung,
            'minimale_rolle': kategorie.minimale_rolle,
            'message': 'Kategorie aktualisiert'
        })
    
    elif request.method == 'DELETE':
        # Prüfen wie viele Waren diese Kategorie haben
        waren_count = kategorie.waren.filter(aktiv=True).count()
        
        # Soft-Delete: Kategorie deaktivieren statt löschen
        kategorie.aktiv = False
        kategorie.save()
        
        # Kategorie auch aus allen Waren entfernen
        kategorie.waren.clear()
        
        log_action(request, 'kategorie_deaktiviert', details={'kategorie_id': str(kategorie.id), 'name': kategorie.name, 'waren_count': waren_count})
        
        return Response({
            'success': True, 
            'message': 'Kategorie deaktiviert',
            'waren_count': waren_count
        })


# =============================================================================
# VERBLEIB ORTE
# =============================================================================

@api_view(['GET', 'POST'])
@jwt_required
def verbleib_orte_liste(request):
    """Verbleib-Orte auflisten oder neuen erstellen."""
    if request.method == 'GET':
        orte = VerbleibOrt.objects.filter(aktiv=True).order_by('reihenfolge', 'name')
        data = [{
            'id': str(o.id),
            'name': o.name,
            'beschreibung': o.beschreibung,
            'reihenfolge': o.reihenfolge,
            'raumnummer_erforderlich': o.raumnummer_erforderlich,
        } for o in orte]
        return Response(data)
    
    elif request.method == 'POST':
        # Nur Mitarbeiter+ dürfen Verbleib-Orte erstellen
        if request.user_role == 'Student':
            return Response({'error': 'Nur Mitarbeiter oder höher'}, status=403)
        
        data = request.data
        name = data.get('name', '').strip()
        
        if not name:
            return Response({'error': 'Name ist erforderlich'}, status=400)
        
        # Prüfen ob bereits existiert (inkl. inaktiver)
        existing = VerbleibOrt.objects.filter(name__iexact=name).first()
        if existing:
            if existing.aktiv:
                return Response({
                    'id': str(existing.id),
                    'name': existing.name,
                    'existing': True,
                    'message': 'Verbleib-Ort existiert bereits'
                })
            else:
                # Inaktiven reaktivieren
                existing.aktiv = True
                existing.name = name  # Name aktualisieren (Groß-/Kleinschreibung)
                existing.beschreibung = data.get('beschreibung', existing.beschreibung)
                existing.reihenfolge = data.get('reihenfolge', existing.reihenfolge)
                if 'raumnummer_erforderlich' in data:
                    existing.raumnummer_erforderlich = data.get('raumnummer_erforderlich', False)
                existing.save()
                return Response({
                    'id': str(existing.id),
                    'name': existing.name,
                    'beschreibung': existing.beschreibung,
                    'reihenfolge': existing.reihenfolge,
                    'raumnummer_erforderlich': existing.raumnummer_erforderlich,
                    'existing': False,
                    'message': 'Verbleib-Ort reaktiviert'
                }, status=200)
        
        ort = VerbleibOrt.objects.create(
            name=name,
            beschreibung=data.get('beschreibung', ''),
            reihenfolge=data.get('reihenfolge', 0),
            raumnummer_erforderlich=data.get('raumnummer_erforderlich', False)
        )
        
        log_action(request, 'verbleib_ort_erstellt', details={'verbleib_ort_id': str(ort.id), 'name': ort.name})
        
        return Response({
            'id': str(ort.id),
            'name': ort.name,
            'beschreibung': ort.beschreibung,
            'reihenfolge': ort.reihenfolge,
            'raumnummer_erforderlich': ort.raumnummer_erforderlich,
            'existing': False,
            'message': 'Verbleib-Ort erstellt'
        }, status=201)


@api_view(['PUT', 'DELETE'])
@jwt_required
def verbleib_ort_detail(request, ort_id):
    """Verbleib-Ort bearbeiten oder löschen."""
    # Nur Mitarbeiter+
    if request.user_role == 'Student':
        return Response({'error': 'Nur Mitarbeiter oder höher'}, status=403)
    
    try:
        ort = VerbleibOrt.objects.get(id=ort_id, aktiv=True)
    except VerbleibOrt.DoesNotExist:
        return Response({'error': 'Verbleib-Ort nicht gefunden'}, status=404)
    
    if request.method == 'PUT':
        data = request.data
        
        if 'name' in data:
            new_name = data['name'].strip()
            if new_name and new_name != ort.name:
                # Prüfen ob Name bei aktiven Verbleib-Orten bereits vergeben ist (case-insensitive)
                if VerbleibOrt.objects.filter(name__iexact=new_name, aktiv=True).exclude(id=ort_id).exists():
                    return Response({'error': 'Name bereits vergeben'}, status=400)
                ort.name = new_name
        
        if 'beschreibung' in data:
            ort.beschreibung = data['beschreibung']
        
        if 'reihenfolge' in data:
            ort.reihenfolge = data['reihenfolge']
        
        if 'raumnummer_erforderlich' in data:
            ort.raumnummer_erforderlich = data['raumnummer_erforderlich']
        
        ort.save()
        
        log_action(request, 'verbleib_ort_aktualisiert', details={'verbleib_ort_id': str(ort.id), 'name': ort.name})
        
        return Response({
            'id': str(ort.id),
            'name': ort.name,
            'beschreibung': ort.beschreibung,
            'reihenfolge': ort.reihenfolge,
            'raumnummer_erforderlich': ort.raumnummer_erforderlich,
            'message': 'Verbleib-Ort aktualisiert'
        })
    
    elif request.method == 'DELETE':
        # Soft-Delete
        ort.aktiv = False
        ort.save()
        
        log_action(request, 'verbleib_ort_deaktiviert', details={'verbleib_ort_id': str(ort.id), 'name': ort.name})
        
        return Response({
            'success': True,
            'message': 'Verbleib-Ort deaktiviert'
        })


@api_view(['GET', 'PUT'])
@jwt_required
def kategorie_verbleib_sperren(request, kategorie_id):
    """Gesperrte Verbleib-Orte für eine Kategorie verwalten."""
    try:
        kategorie = Warenkategorie.objects.get(id=kategorie_id, aktiv=True)
    except Warenkategorie.DoesNotExist:
        return Response({'error': 'Kategorie nicht gefunden'}, status=404)
    
    if request.method == 'GET':
        # Alle gesperrten Verbleib-Orte für diese Kategorie
        gesperrt = kategorie.gesperrte_verbleib_orte.filter(aktiv=True)
        return Response([{'id': str(o.id), 'name': o.name} for o in gesperrt])
    
    elif request.method == 'PUT':
        # Nur Mitarbeiter+
        if request.user_role == 'Student':
            return Response({'error': 'Nur Mitarbeiter oder höher'}, status=403)
        
        data = request.data
        verbleib_ort_ids = data.get('gesperrte_verbleib_orte', [])
        
        # IDs validieren und setzen
        gueltige_orte = VerbleibOrt.objects.filter(id__in=verbleib_ort_ids, aktiv=True)
        kategorie.gesperrte_verbleib_orte.set(gueltige_orte)
        
        log_action(request, 'kategorie_verbleib_aktualisiert', details={
            'kategorie_id': str(kategorie.id),
            'gesperrte_orte': [str(o.id) for o in gueltige_orte]
        })
        
        return Response({
            'success': True,
            'message': 'Gesperrte Verbleib-Orte aktualisiert',
            'gesperrte_verbleib_orte': [{'id': str(o.id), 'name': o.name} for o in gueltige_orte]
        })


# =============================================================================
# AUSLEIHEN
# =============================================================================

@api_view(['GET', 'POST'])
@jwt_required
def ausleihen_liste(request):
    """Ausleihen anzeigen oder neue Ausleihe erstellen."""
    if request.method == 'GET':
        # Filter
        status_filter = request.query_params.get('status')
        meine = request.query_params.get('meine') == 'true'
        
        ausleihen = Ausleihe.objects.filter(aktiv=True)
        
        # Studenten sehen nur ihre eigenen wenn 'meine' Parameter gesetzt
        if meine:
            ausleihen = ausleihen.filter(benutzer_id=request.user_id)
        elif request.user_role in ['Laborleiter', 'Admin']:
            pass  # Sehen alle
        else:
            # Mitarbeiter sehen alle aktiven
            pass
        
        if status_filter:
            ausleihen = ausleihen.filter(status=status_filter)
        
        # Für Studenten: Anonymisierte Daten bei fremden Ausleihen
        is_student = request.user_role == 'Student'
        user_id = request.user_id
        
        # Prefetch für ManyToMany Kategorien
        ausleihen = ausleihen.select_related('ware', 'benutzer').prefetch_related('ware__kategorien')
        
        data = []
        for a in ausleihen:
            # Für Studenten bei fremden Ausleihen: Name anonymisieren
            if is_student and str(a.benutzer.id) != str(user_id):
                benutzer_name = 'Andere'
            else:
                benutzer_name = f"{a.benutzer.vorname} {a.benutzer.nachname}"
            
            # Kategorien für die Ware laden (bereits prefetch'd)
            kategorien_list = list(a.ware.kategorien.all())
            primary_kategorie = kategorien_list[0].name if kategorien_list else None
            
            data.append({
                'id': str(a.id),
                'ware': {
                    'id': str(a.ware.id),
                    'name': a.ware.name,
                    'rfid_tag': a.ware.rfid_tag,
                    'schranknummer': a.ware.schranknummer,
                    'kategorie_name': primary_kategorie,
                    'kategorien': [{'id': str(k.id), 'name': k.name} for k in kategorien_list],
                },
                'benutzer': {
                    'id': str(a.benutzer.id),
                    'name': benutzer_name,
                },
                'status': a.status,
                'ausgeliehen_am': a.ausgeliehen_am,
                'geplante_rueckgabe': a.geplante_rueckgabe,
                'verbleib_ort': a.verbleib_ort if not (is_student and str(a.benutzer.id) != str(user_id)) else None,
                'notiz': a.notiz,
            })
        
        return Response(data)
    
    elif request.method == 'POST':
        data = request.data
        
        # Ware prüfen
        try:
            ware = Ware.objects.get(id=data['ware_id'], aktiv=True)
        except Ware.DoesNotExist:
            return Response({'error': 'Ware nicht gefunden'}, status=404)
        
        # Berechtigung prüfen (mit Verbleib-Ort)
        verbleib_ort_name = data.get('verbleib_ort', '')
        verbleib_ort_obj = None
        if verbleib_ort_name:
            try:
                verbleib_ort_obj = VerbleibOrt.objects.get(name=verbleib_ort_name, aktiv=True)
            except VerbleibOrt.DoesNotExist:
                pass
        
        kann_ausleihen, grund = ware.kann_ausgeliehen_werden_von(
            Benutzer.objects.get(id=request.user_id),
            verbleib_ort=verbleib_ort_obj
        )
        if not kann_ausleihen:
            return Response({'error': grund}, status=403)
        
        # Maximale Leihdauer prüfen
        if verbleib_ort_obj:
            kategorie = ware.kategorien.first()
            if kategorie:
                try:
                    regel = KategorieVerbleibRegel.objects.get(
                        kategorie=kategorie,
                        verbleib_ort=verbleib_ort_obj
                    )
                    if regel.maximale_leihdauer_tage:
                        geplante_rueckgabe = data.get('geplante_rueckgabe')
                        if geplante_rueckgabe:
                            from datetime import datetime
                            rueckgabe_datum = datetime.strptime(geplante_rueckgabe, '%Y-%m-%d').date()
                            heute = datetime.now().date()
                            tage = (rueckgabe_datum - heute).days
                            if tage > regel.maximale_leihdauer_tage:
                                return Response({
                                    'error': f'Maximale Ausleihdauer für diesen Ort: {regel.maximale_leihdauer_tage} Tage'
                                }, status=400)
                except KategorieVerbleibRegel.DoesNotExist:
                    pass
        
        # Ausleihe erstellen
        benutzer = Benutzer.objects.get(id=request.user_id)
        
        ausleihe = Ausleihe.objects.create(
            ware=ware,
            benutzer=benutzer,
            geplante_rueckgabe=data.get('geplante_rueckgabe'),
            verbleib_ort=data.get('verbleib_ort', ''),
            notiz=data.get('notiz', ''),
        )
        
        # Ware als ausgeliehen markieren
        ware.ist_ausgeliehen = True
        ware.save()
        
        log_action(request, 'ausleihe_erstellt', ware=ware, ausleihe=ausleihe)
        
        return Response({
            'success': True,
            'id': str(ausleihe.id),
            'message': 'Ware ausgeliehen'
        }, status=201)


@api_view(['GET', 'PUT'])
@jwt_required
def ausleihe_detail(request, ausleihe_id):
    """Einzelne Ausleihe anzeigen oder aktualisieren."""
    try:
        ausleihe = Ausleihe.objects.get(id=ausleihe_id, aktiv=True)
    except Ausleihe.DoesNotExist:
        return Response({'error': 'Ausleihe nicht gefunden'}, status=404)
    
    # Berechtigungsprüfung: Eigene Ausleihe oder höhere Rolle
    if str(ausleihe.benutzer_id) != request.user_id and request.user_role not in ['Laborleiter', 'Admin']:
        return Response({'error': 'Keine Berechtigung'}, status=403)
    
    if request.method == 'GET':
        return Response({
            'id': str(ausleihe.id),
            'ware': {
                'id': str(ausleihe.ware.id),
                'name': ausleihe.ware.name,
                'rfid_tag': ausleihe.ware.rfid_tag,
            },
            'benutzer': {
                'id': str(ausleihe.benutzer.id),
                'name': f"{ausleihe.benutzer.vorname} {ausleihe.benutzer.nachname}",
            },
            'status': ausleihe.status,
            'ausgeliehen_am': ausleihe.ausgeliehen_am,
            'geplante_rueckgabe': ausleihe.geplante_rueckgabe,
            'rueckgabe_beantragt_am': ausleihe.rueckgabe_beantragt_am,
            'tatsaechliche_rueckgabe': ausleihe.tatsaechliche_rueckgabe,
            'verbleib_ort': ausleihe.verbleib_ort,
            'notiz': ausleihe.notiz,
            'genehmigungen': [{
                'aktion': g.aktion,
                'zustand': g.zustand_beim_check,
                'kommentar': g.kommentar,
                'genehmigt_von': f"{g.genehmigt_von.vorname} {g.genehmigt_von.nachname}" if g.genehmigt_von else None,
                'genehmigt_am': g.genehmigt_am,
            } for g in ausleihe.genehmigungen.filter(aktiv=True)],
        })
    
    elif request.method == 'PUT':
        data = request.data
        aktion = data.get('aktion')
        
        if aktion == 'rueckgabe_beantragen':
            # Jeder darf eigene Rückgabe beantragen
            success = ausleihe.beantrage_rueckgabe()
            if success:
                log_action(request, 'rueckgabe_beantragt', ware=ausleihe.ware, ausleihe=ausleihe)
                return Response({'success': True, 'message': 'Rückgabe beantragt'})
            return Response({'error': 'Rückgabe kann nicht beantragt werden'}, status=400)
        
        elif aktion == 'rueckgabe_quittieren':
            # Nur Mitarbeiter+ dürfen quittieren
            if request.user_role in ['Mitarbeiter', 'Laborleiter', 'Admin']:
                genehmigt_von = Benutzer.objects.get(id=request.user_id)
                zustand = data.get('zustand', 'gut')
                kommentar = data.get('kommentar', '')
                
                success = ausleihe.schliesse_ab(genehmigt_von, zustand, kommentar)
                if success:
                    log_action(request, 'rueckgabe_quittiert', ware=ausleihe.ware, ausleihe=ausleihe)
                    return Response({'success': True, 'message': 'Rückgabe quittiert'})
                return Response({'error': 'Ausleihe kann nicht abgeschlossen werden'}, status=400)
            return Response({'error': 'Keine Berechtigung zum Quittieren'}, status=403)
        
        elif aktion == 'ware_verschwunden':
            # Nur Mitarbeiter+ dürfen diese Aktion ausführen
            if request.user_role in ['Mitarbeiter', 'Laborleiter', 'Admin']:
                genehmigt_von = Benutzer.objects.get(id=request.user_id)
                zustand = 'verschwunden'  # Spezieller Zustand
                kommentar = data.get('kommentar', 'Ware als verschwunden markiert')
                
                # 1. Rückgabe quittieren
                success = ausleihe.schliesse_ab(genehmigt_von, zustand, kommentar)
                if success:
                    # 2. Ware deaktivieren (Soft-Delete)
                    ware = ausleihe.ware
                    ware.aktiv = False
                    ware.sperr_grund = 'Verschwunden am ' + timezone.now().strftime('%d.%m.%Y')
                    ware.save()
                    
                    log_action(request, 'ware_verschwunden', ware=ausleihe.ware, ausleihe=ausleihe, 
                              details={'kommentar': kommentar})
                    return Response({'success': True, 'message': 'Rückgabe quittiert und Ware als verschwunden markiert'})
                return Response({'error': 'Ausleihe kann nicht abgeschlossen werden'}, status=400)
            return Response({'error': 'Keine Berechtigung'}, status=403)
        
        return Response({'error': 'Unbekannte Aktion'}, status=400)


# =============================================================================
# HISTORIE
# =============================================================================

@api_view(['GET'])
@jwt_required
def historie_liste(request):
    """Ausleihhistorie anzeigen."""
    # Filter
    ware_id = request.query_params.get('ware_id')
    benutzer_id = request.query_params.get('benutzer_id')
    
    historie = AusleiheHistorie.objects.all()
    
    if ware_id:
        historie = historie.filter(ware_id=ware_id)
    if benutzer_id:
        historie = historie.filter(benutzer_id=benutzer_id)
    
    # Studenten sehen nur ihre eigene Historie
    if request.user_role == 'Student':
        historie = historie.filter(benutzer_id=request.user_id)
    
    data = [{
        'id': str(h.id),
        'ware_name': h.ware_name,
        'ware_kategorie': h.ware_kategorie,
        'benutzer_name': f"{h.benutzer_vorname} {h.benutzer_nachname}",
        'ausgeliehen_am': h.ausgeliehen_am,
        'geplante_rueckgabe': h.geplante_rueckgabe,
        'tatsaechliche_rueckgabe': h.tatsaechliche_rueckgabe,
        'verbleib_ort': h.verbleib_ort,
        'zustand': h.zustand,
        'genehmigt_von': h.genehmigt_von_name if h.genehmigt_von_id else None,
    } for h in historie[:100]]  # Limit für Performance
    
    return Response(data)


# =============================================================================
# RFID / HARDWARE (bestehende Funktionalität erhalten)
# =============================================================================

import serial.tools.list_ports
from copy import deepcopy
from threading import Lock
import time


def get_reader(port=None, baudrate=None, timeout=None):
    """Bestehende Reader-Initialisierung."""
    global reader
    
    if port is not None and baudrate is not None:
        if reader is not None:
            try:
                reader.close()
            except Exception:
                pass
        reader = UHFReader(port, baudrate, timeout)
        return reader
    else:
        if reader is None:
            raise Exception("Reader nicht initialisiert")
        return reader


@api_view(['GET'])
@jwt_required
def get_ports(request):
    """Verfügbare COM-Ports auflisten - alle authentifizierten Benutzer."""
    com_list = list(serial.tools.list_ports.comports())
    com_attr = [list(com_list[i])[0] for i in range(len(com_list))]
    return Response({'ports': com_attr})


def check_hardware_lock(request, device_type='rfid'):
    """
    Hilfsfunktion: Prüft ob die Hardware von einer anderen Session gesperrt ist.
    Gibt (locked, response) zurück. Wenn locked=True, sollte die response zurückgegeben werden.
    """
    session_id = request.data.get('session_id') if hasattr(request, 'data') else request.GET.get('session_id')
    user_id = getattr(request, 'user_id', None)
    
    locked, info = is_hardware_locked()
    if locked and info:
        # Eigener Lock ist OK
        if info['user_id'] == user_id:
            return False, None
        # Anderer Lock
        return True, Response({
            'res': 1002,
            'log': f"Hardware wird bereits verwendet (seit {info['since']}, User: {info['user_id']}, Gerät: {info.get('device_type', 'unbekannt')})",
            'success': False,
            'locked': True,
            'locked_by': info['user_id'],
            'locked_device': info.get('device_type')
        }, status=423)  # 423 Locked
    return False, None


@api_view(['POST'])
@jwt_required
def open_device(request):
    """RFID-Gerät öffnen - alle authentifizierten Benutzer."""
    
    port = request.data.get('port')
    baudrate = int(request.data.get('baudrate', 115200))
    session_id = request.data.get('session_id', str(uuid.uuid4()))  # Eindeutige Session-ID
    
    if not port:
        return Response({'error': 'port is required'}, status=400)
    
    # Prüfe ob jemand anders die Hardware nutzt
    locked, response = check_hardware_lock(request, 'rfid')
    if locked:
        return response
    
    try:
        r = get_reader(port=port, baudrate=baudrate, timeout=0.02)
        resp = r.rfm_module_init()
        
        if resp.get('status') != 0:
            return Response({
                'res': resp['status'],
                'log': f"serial {resp['status']} open fail",
                'success': False,
                'hComm': 0
            })
        
        # Lock setzen
        acquire_hardware_lock(request.user_id, session_id, 'rfid')
        
        return Response({
            'res': 0,
            'log': f"Reader geöffnet: {port}",
            'success': True,
            'hComm': r.hComm,
            'session_id': session_id
        })
        
    except Exception as e:
        return Response({
            'res': 1001,
            'log': f"serial {e} open fail",
            'success': False,
            'hComm': 0
        })


@api_view(['POST'])
@jwt_required
def close_device(request):
    """RFID-Gerät schließen - alle authentifizierten Benutzer."""
    global reader
    
    session_id = request.data.get('session_id')
    
    try:
        # Lock freigeben (egal ob RFID oder Card Reader)
        if session_id:
            release_hardware_lock(request.user_id, session_id)
        
        if reader:
            reader.close()
            reader = None
        return Response({'res': 0, 'log': 'Reader geschlossen', 'success': True})
    except Exception as e:
        return Response({'res': 1001, 'log': str(e), 'success': False})


@api_view(['GET'])
@jwt_required
def get_scanning_status(request):
    """Prüft ob jemand die Hardware nutzt - alle authentifizierten Benutzer."""
    locked, info = is_hardware_locked()
    return Response({
        'scanning': locked and info.get('device_type') == 'rfid' if info else False,
        'card_reader_active': locked and info.get('device_type') == 'card_reader' if info else False,
        'hardware_locked': locked,
        'info': info
    })


@api_view(['POST'])
@jwt_required
def start_counting(request):
    """Tag-Scanning starten - alle authentifizierten Benutzer."""
    global inventory_thread, work_mode
    
    # Prüfe Hardware-Lock
    locked, response = check_hardware_lock(request, 'rfid')
    if locked:
        return response
    
    try:
        hcomm = int(request.data.get('hComm'))
        
        # Parameter aus Request
        params = {
            "addr": int(request.data.get("DEVICEARRD", 0)),
            "rf_protocol": int(request.data.get("RFIDPRO", 0)),
            "work_mode": int(request.data.get("WORKMODE", 0)),
            "interface": int(request.data.get("INTERFACE", 0)),
            "baudrate": int(request.data.get("BAUDRATE", 115200)),
            "wgset": int(request.data.get("WGSET", 0)),
            "antenna_mask": int(request.data.get("ANT", 1)),
            "rfid_freq": {
                "REGION": int(request.data.get("REGION", 1)),
                "STRATFREI": int(float(request.data.get("STRATFREI", 920))),
                "STRATFRED": int(request.data.get("STRATFRED", 0)),
                "STEPFRE": int(request.data.get("STEPFRE", 250)),
                "CN": int(request.data.get("CN", 6)),
            },
            "rf_power": int(request.data.get("RFIDPOWER", 30)),
            "inquiry_area": int(request.data.get("INVENTORYAREA", 6)),
            "qvalue": int(request.data.get("QVALUE", 4)),
            "session": int(request.data.get("SESSION", 0)),
            "acs_addr": int(request.data.get("ACSADDR", 0)),
            "acs_data_len": int(request.data.get("ACSDATALEN", 0)),
            "filter_time": int(request.data.get("FILTERTIME", 0)),
            "trigger_time": int(request.data.get("TRIGGLETIME", 0)),
            "buzzer_time": int(request.data.get("BUZZERTIME", 0)),
            "polling_interval": int(request.data.get("INTERNELTIME", 0))
        }
        
        work_mode = params['work_mode']
        
        r = get_reader()
        
        # Alten Thread stoppen falls vorhanden
        if inventory_thread and inventory_thread.is_alive():
            inventory_thread.terminate()
            inventory_thread.join(timeout=2)
        
        # Parameter setzen und Scanning starten
        r.rfm_set_all_param(hcomm, params)
        time.sleep(0.1)
        
        if work_mode == 0:
            r.rfm_inventoryiso_continue(hcomm)
        
        # Neuen Thread starten
        inventory_thread = InventoryThread(r)
        inventory_thread.start()
        
        return Response({'res': 0, 'log': 'Scanning gestartet', 'success': True})
        
    except Exception as e:
        return Response({'res': 1001, 'log': str(e), 'success': False})


@api_view(['GET'])
@jwt_required
def get_tag_info(request):
    """Gescannte Tags abrufen - alle authentifizierten Benutzer."""
    if inventory_thread is None:
        return Response([])
    
    info = deepcopy(inventory_thread.info)
    
    # Mit Waren aus DB anreichern
    result = []
    for tag in info:
        try:
            ware = Ware.objects.get(rfid_tag=tag.get('epc'), aktiv=True)
            tag['ware_id'] = str(ware.id)
            tag['ware_name'] = ware.name
            tag['ist_ausgeliehen'] = ware.ist_ausgeliehen
        except Ware.DoesNotExist:
            tag['ware_id'] = None
            tag['ware_name'] = 'Unbekannte Ware'
        result.append(tag)
    
    return Response(result)


@api_view(['POST'])
@jwt_required
def inventory_stop(request):
    """Scanning stoppen - alle authentifizierten Benutzer."""
    global inventory_thread
    
    # Prüfe Hardware-Lock
    locked, response = check_hardware_lock(request, 'rfid')
    if locked:
        return response
    
    try:
        hcomm = int(request.data.get('hComm'))
        
        if inventory_thread:
            inventory_thread.terminate()
            inventory_thread.join(timeout=2)
            inventory_thread = None
            
            if work_mode == 0:
                r = get_reader()
                r.rfm_inventoryiso_stop(hcomm)
        
        return Response({'res': 0, 'log': 'Scanning gestoppt', 'success': True})
        
    except Exception as e:
        return Response({'res': 1001, 'log': str(e), 'success': False})


@api_view(['POST'])
@jwt_required
def get_device_para(request):
    """Geräte-Parameter laden - alle authentifizierten Benutzer."""
    # Prüfe Hardware-Lock
    locked, response = check_hardware_lock(request, 'rfid')
    if locked:
        return response
    
    try:
        hcomm = int(request.data.get('hComm'))
        r = get_reader()
        
        # Timeout temporär erhöhen für Parameter-Lesen (0.5s statt 0.02s)
        old_timeout = r.ser.timeout
        r.ser.timeout = 0.5
        
        try:
            resp = r.rfm_get_all_param(hcomm)
        finally:
            # Timeout wieder zurücksetzen für schnelles Scannen
            r.ser.timeout = old_timeout
        
        # Feldnamen mappen (parse_all_params -> setDevicePara erwartet)
        freq = resp.get('rfid_freq', {})
        mapped_resp = {
            'DEVICEARRD': resp.get('addr', 0),
            'RFIDPRO': resp.get('rf_protocol', 0),
            'WORKMODE': resp.get('work_mode', 0),
            'INTERFACE': resp.get('interface', 0),
            'BAUDRATE': resp.get('baudrate', 115200),
            'WGSET': resp.get('wgset', 0),
            'ANT': resp.get('antenna_mask', 1),
            'REGION': freq.get('REGION', 1),
            'STRATFREI': freq.get('STRATFREI', 920),
            'STRATFRED': freq.get('STRATFRED', 0),
            'STEPFRE': freq.get('STEPFRE', 250),
            'CN': freq.get('CN', 6),
            'RFIDPOWER': resp.get('rf_power', 30),
            'INVENTORYAREA': resp.get('inquiry_area', 6),
            'QVALUE': resp.get('qvalue', 4),
            'SESSION': resp.get('session', 0),
            'ACSADDR': resp.get('acs_addr', 0),
            'ACSDATALEN': resp.get('acs_data_len', 0),
            'FILTERTIME': resp.get('filter_time', 0),
            'TRIGGLETIME': resp.get('trigger_time', 0),
            'BUZZERTIME': resp.get('buzzer_time', 0),
            'INTERNELTIME': resp.get('polling_interval', 0),
        }
        
        return Response({
            'res': resp['status'],
            'success': True,
            'log': 'Parameter geladen',
            **mapped_resp
        })
    except Exception as e:
        return Response({'res': 1001, 'log': str(e), 'success': False})


@api_view(['POST'])
@jwt_required
def set_device_para(request):
    """Geräte-Parameter setzen - alle authentifizierten Benutzer."""
    # Prüfe Hardware-Lock
    locked, response = check_hardware_lock(request, 'rfid')
    if locked:
        return response
    
    try:
        hcomm = int(request.data.get('hComm'))
        
        params = {
            "addr": int(request.data.get("DEVICEARRD", 0)),
            "rf_protocol": int(request.data.get("RFIDPRO", 0)),
            "work_mode": int(request.data.get("WORKMODE", 0)),
            "interface": int(request.data.get("INTERFACE", 0)),
            "baudrate": int(request.data.get("BAUDRATE", 115200)),
            "wgset": int(request.data.get("WGSET", 0)),
            "antenna_mask": int(request.data.get("ANT", 1)),
            "rfid_freq": {
                "REGION": int(request.data.get("REGION", 1)),
                "STRATFREI": int(float(request.data.get("STRATFREI", 920))),
                "STRATFRED": int(request.data.get("STRATFRED", 0)),
                "STEPFRE": int(request.data.get("STEPFRE", 250)),
                "CN": min(int(request.data.get("CN", 6)), 255),
            },
            "rf_power": min(int(request.data.get("RFIDPOWER", 30)), 33),
            "inquiry_area": int(request.data.get("INVENTORYAREA", 6)),
            "qvalue": min(int(request.data.get("QVALUE", 4)), 15),
            "session": int(request.data.get("SESSION", 0)),
            "acs_addr": int(request.data.get("ACSADDR", 0)),
            "acs_data_len": int(request.data.get("ACSDATALEN", 0)),
            "filter_time": int(request.data.get("FILTERTIME", 0)),
            "trigger_time": int(request.data.get("TRIGGLETIME", 0)),
            "buzzer_time": min(int(request.data.get("BUZZERTIME", 0)), 255),
            "polling_interval": int(request.data.get("INTERNELTIME", 0))
        }
        
        r = get_reader()
        
        # Timeout temporär erhöhen für Parameter-Schreiben (1 Sekunde)
        old_timeout = r.ser.timeout
        old_reader_timeout = r.timeout
        r.ser.timeout = 1.0
        r.timeout = 1.0
        
        try:
            resp = r.rfm_set_all_param(hcomm, params)
        finally:
            r.ser.timeout = old_timeout
            r.timeout = old_reader_timeout
        
        # Prüfen ob ein Fehler aufgetreten ist
        if 'error' in resp:
            return Response({
                'res': resp.get('status', 1001),
                'log': resp['error'],
                'success': False
            })
        
        return Response({
            'res': resp['status'],
            'log': 'Parameter gesetzt',
            'success': resp['status'] == 0
        })
        
    except Exception as e:
        return Response({'res': 1001, 'log': str(e), 'success': False})


@api_view(['POST'])
@jwt_required
@require_role(['Laborleiter', 'Admin'])
def reboot_device(request):
    """RFID-Antenne rebooten - nur Laborleiter/Admin."""
    # Prüfe Hardware-Lock
    locked, response = check_hardware_lock(request, 'rfid')
    if locked:
        return response
    
    try:
        hcomm = int(request.data.get('hComm'))
        r = get_reader()
        resp = r.rfm_reboot(hcomm)
        
        if resp['status'] != 0:
            return Response({
                'success': False,
                'log': f'reboot failed {resp["status"]}'
            })
        
        return Response({
            'success': True,
            'log': 'Device rebooted'
        })
    except Exception as e:
        return Response({'success': False, 'log': str(e)})



# =============================================================================
# KARTENLESER (Card Reader) - NEU: Direktes Lesen ohne Thread
# =============================================================================

from .card_reader import CardReader, start_reader, stop_reader, read_card, get_last_code

# Aktive Reader-Instanz pro Session
_active_card_readers = {}

@api_view(['POST'])
@permission_classes([AllowAny])
def start_card_reader(request):
    """
    Kartenleser initialisieren - KEINE Authentifizierung nötig.
    Speichert nur Port/Einstellungen, liest noch nicht.
    """
    session_id = request.data.get('session_id', str(uuid.uuid4()))
    user_id = request.data.get('user_id', 'anonymous')
    
    # Prüfe Hardware-Lock - Card Reader hat kurze Sessions, daher Lock erneuern wenn gleicher User
    locked, info = is_hardware_locked()
    if locked and info:
        if info['user_id'] != user_id and info.get('device_type') == 'rfid':
            # RFID Antenne wird von anderem User verwendet - das ist ein echtes Problem
            return Response({
                'success': False,
                'error': f"RFID Antenne wird bereits verwendet (User: {info['user_id']}). Card Reader kann nicht parallel genutzt werden.",
                'locked': True,
                'locked_by': info['user_id']
            }, status=423)
        # Bei Card Reader oder gleichem User: Lock überschreiben
    
    try:
        port = request.data.get('port', '/dev/ttyUSB0')
        baudrate = int(request.data.get('baudrate', 9600))
        
        # Reader starten/aktualisieren
        reader = start_reader(port, baudrate)
        _active_card_readers[session_id] = {
            'reader': reader,
            'user_id': user_id,
            'started_at': datetime.now()
        }
        
        # Lock setzen für Card Reader
        acquire_hardware_lock(user_id, session_id, 'card_reader')
        
        return Response({
            'success': True, 
            'error': None,
            'session_id': session_id
        })
    except Exception as e:
        return Response({'success': False, 'error': str(e)})


@api_view(['GET', 'POST'])
@permission_classes([AllowAny])
def get_card_reader_data(request):
    """
    Liest direkt von der seriellen Schnittstelle.
    Wartet kurz (150ms) auf Karte und gibt Ergebnis zurück.
    KEINE Authentifizierung nötig.
    """
    session_id = request.data.get('session_id') if request.method == 'POST' else request.GET.get('session_id')
    user_id = request.data.get('user_id') if request.method == 'POST' else request.GET.get('user_id')
    
    if not session_id:
        return Response({'success': False, 'code': None, 'error': 'Session ID erforderlich'})
    
    # Card Reader hat keinen strikten Lock - jede Session kann lesen
    # (Der Lock ist nur für RFID-Antenne wichtig, da diese lange geöffnet bleibt)
    
    # Prüfe ob Reader existiert
    if session_id not in _active_card_readers:
        return Response({'success': False, 'code': None, 'error': 'Kartenleser nicht gestartet'})
    
    try:
        # DIREKT lesen mit 700ms Timeout (mehr als 500ms Intervall des Readers)
        code = read_card(timeout_ms=700)
        
        if code:
            return Response({'success': True, 'code': code})
        else:
            return Response({'success': True, 'code': 'None'})
    except Exception as e:
        return Response({'success': False, 'code': None, 'error': str(e)})


@api_view(['POST'])
@permission_classes([AllowAny])
def stop_card_reader(request):
    """Kartenleser stoppen und Lock freigeben."""
    session_id = request.data.get('session_id')
    user_id = request.data.get('user_id')
    
    # Lock freigeben
    if session_id and user_id:
        release_hardware_lock(user_id, session_id)
    
    # Session entfernen
    if session_id and session_id in _active_card_readers:
        del _active_card_readers[session_id]
    
    # Reader stoppen (wenn keine Sessions mehr aktiv)
    if len(_active_card_readers) == 0:
        stop_reader()
    
    return Response({'success': True, 'error': None})


# =============================================================================
# KATEGORIE-VERBLEIB MATRIX
# =============================================================================

@api_view(['GET'])
@jwt_required
def kategorie_verbleib_matrix(request):
    """
    Gibt die komplette Matrix zurück:
    - Spalten: Verbleib-Orte
    - Zeilen: Kategorien
    - Zellen: Minimale Rolle für diese Kombination
    """
    # Alle aktiven Kategorien und Verbleib-Orte laden
    kategorien = Warenkategorie.objects.filter(aktiv=True).order_by('name')
    verbleib_orte = VerbleibOrt.objects.filter(aktiv=True).order_by('reihenfolge', 'name')
    
    # Alle Regeln laden
    regeln = KategorieVerbleibRegel.objects.filter(
        kategorie__aktiv=True,
        verbleib_ort__aktiv=True
    ).select_related('kategorie', 'verbleib_ort')
    
    # Regeln in Dictionary für schnellen Zugriff
    regel_dict = {}
    for regel in regeln:
        key = (str(regel.kategorie.id), str(regel.verbleib_ort.id))
        regel_dict[key] = {
            'minimale_rolle': regel.minimale_rolle,
            'gesperrt': regel.gesperrt,
            'maximale_leihdauer_tage': regel.maximale_leihdauer_tage
        }
    
    # Matrix aufbauen
    kategorien_data = []
    for kat in kategorien:
        zeile = {
            'id': str(kat.id),
            'name': kat.name,
            'zellen': {}
        }
        for ort in verbleib_orte:
            key = (str(kat.id), str(ort.id))
            if key in regel_dict:
                zeile['zellen'][str(ort.id)] = regel_dict[key]
            else:
                # Standard: Keine Einschränkung (Student darf, keine max Dauer)
                zeile['zellen'][str(ort.id)] = {
                    'minimale_rolle': 'Student',
                    'gesperrt': False,
                    'maximale_leihdauer_tage': None
                }
        kategorien_data.append(zeile)
    
    orte_data = [{
        'id': str(o.id),
        'name': o.name,
        'beschreibung': o.beschreibung,
        'raumnummer_erforderlich': o.raumnummer_erforderlich
    } for o in verbleib_orte]
    
    return Response({
        'kategorien': kategorien_data,
        'verbleib_orte': orte_data
    })


@api_view(['POST', 'PUT', 'DELETE'])
@jwt_required
def kategorie_verbleib_regel(request):
    """
    Erstellt, aktualisiert oder löscht eine Berechtigungsregel.
    
    POST: Neue Regel erstellen
    PUT: Bestehende Regel aktualisieren
    DELETE: Regel löschen (zurücksetzen auf Standard)
    """
    # Nur Laborleiter+ dürfen Regeln verwalten
    if request.user_role not in ['Laborleiter', 'Admin']:
        return Response({'error': 'Nur Laborleiter oder Admin'}, status=403)
    
    data = request.data
    kategorie_id = data.get('kategorie_id')
    verbleib_ort_id = data.get('verbleib_ort_id')
    
    if not kategorie_id or not verbleib_ort_id:
        return Response({'error': 'kategorie_id und verbleib_ort_id sind erforderlich'}, status=400)
    
    try:
        kategorie = Warenkategorie.objects.get(id=kategorie_id, aktiv=True)
        verbleib_ort = VerbleibOrt.objects.get(id=verbleib_ort_id, aktiv=True)
    except (Warenkategorie.DoesNotExist, VerbleibOrt.DoesNotExist):
        return Response({'error': 'Kategorie oder Verbleib-Ort nicht gefunden'}, status=404)
    
    if request.method == 'DELETE':
        # Regel löschen (zurücksetzen auf Standard)
        deleted, _ = KategorieVerbleibRegel.objects.filter(
            kategorie=kategorie,
            verbleib_ort=verbleib_ort
        ).delete()
        
        if deleted:
            log_action(request, 'regel_geloescht', details={
                'kategorie': kategorie.name,
                'verbleib_ort': verbleib_ort.name
            })
        
        return Response({
            'success': True,
            'message': 'Regel zurückgesetzt'
        })
    
    # POST oder PUT - Regel erstellen oder aktualisieren
    minimale_rolle = data.get('minimale_rolle', 'Student')
    gesperrt = data.get('gesperrt', False)
    maximale_leihdauer_tage = data.get('maximale_leihdauer_tage')
    
    # Konvertiere null/None/leer String zu None
    if maximale_leihdauer_tage == '' or maximale_leihdauer_tage == 'null':
        maximale_leihdauer_tage = None
    if maximale_leihdauer_tage is not None:
        try:
            maximale_leihdauer_tage = int(maximale_leihdauer_tage)
            if maximale_leihdauer_tage < 1:
                maximale_leihdauer_tage = None
        except (ValueError, TypeError):
            maximale_leihdauer_tage = None
    
    regel, created = KategorieVerbleibRegel.objects.update_or_create(
        kategorie=kategorie,
        verbleib_ort=verbleib_ort,
        defaults={
            'minimale_rolle': minimale_rolle,
            'gesperrt': gesperrt,
            'maximale_leihdauer_tage': maximale_leihdauer_tage
        }
    )
    
    action_type = 'regel_erstellt' if created else 'regel_aktualisiert'
    log_action(request, action_type, details={
        'kategorie': kategorie.name,
        'verbleib_ort': verbleib_ort.name,
        'minimale_rolle': minimale_rolle,
        'gesperrt': gesperrt,
        'maximale_leihdauer_tage': maximale_leihdauer_tage
    })
    
    return Response({
        'id': str(regel.id),
        'kategorie_id': str(kategorie.id),
        'verbleib_ort_id': str(verbleib_ort.id),
        'minimale_rolle': regel.minimale_rolle,
        'gesperrt': regel.gesperrt,
        'maximale_leihdauer_tage': regel.maximale_leihdauer_tage,
        'created': created,
        'message': 'Regel erstellt' if created else 'Regel aktualisiert'
    }, status=201 if created else 200)


@api_view(['GET'])
@jwt_required
def max_leihdauer_abfragen(request):
    """
    Gibt die maximale Leihdauer für eine Kategorie-Verbleib-Kombination zurück.
    GET /api/max-leihdauer/?kategorie_id=xxx&ort_id=yyy
    """
    kategorie_id = request.query_params.get('kategorie_id')
    ort_id = request.query_params.get('ort_id')
    
    if not kategorie_id or not ort_id:
        return Response({'error': 'kategorie_id und ort_id sind erforderlich'}, status=400)
    
    try:
        regel = KategorieVerbleibRegel.objects.get(
            kategorie_id=kategorie_id,
            verbleib_ort_id=ort_id
        )
        max_tage = regel.maximale_leihdauer_tage
    except KategorieVerbleibRegel.DoesNotExist:
        max_tage = None
    
    return Response({
        'kategorie_id': kategorie_id,
        'ort_id': ort_id,
        'maximale_leihdauer_tage': max_tage
    })


@api_view(['GET'])
@jwt_required
def verfuegbare_zeitraeume(request):
    """
    Gibt verfügbare Zeiträume für eine Ware an einem Verbleib-Ort zurück.
    Berücksichtigt bestehende Ausleihen und maximale Leihdauer.
    GET /api/verfuegbare-zeitraeume/?ware_id=xxx&ort_id=yyy
    """
    ware_id = request.query_params.get('ware_id')
    ort_id = request.query_params.get('ort_id')
    
    if not ware_id:
        return Response({'error': 'ware_id ist erforderlich'}, status=400)
    
    try:
        ware = Ware.objects.get(id=ware_id, aktiv=True)
    except Ware.DoesNotExist:
        return Response({'error': 'Ware nicht gefunden'}, status=404)
    
    # Maximale Leihdauer ermitteln (falls Ort angegeben)
    max_tage = None
    if ort_id:
        try:
            kategorie = ware.kategorien.first()
            if kategorie:
                regel = KategorieVerbleibRegel.objects.get(
                    kategorie=kategorie,
                    verbleib_ort_id=ort_id
                )
                max_tage = regel.maximale_leihdauer_tage
        except KategorieVerbleibRegel.DoesNotExist:
            pass
    
    # Blockierte Zeiträume (aktive Ausleihen)
    blockierte_zeitraeume = []
    ausleihen = Ausleihe.objects.filter(
        ware=ware,
        status__in=['aktiv', 'rueckgabe_beantragt']
    ).select_related('benutzer')
    
    for ausleihe in ausleihen:
        blockierte_zeitraeume.append({
            'von': ausleihe.ausgeliehen_am.isoformat() if ausleihe.ausgeliehen_am else None,
            'bis': ausleihe.geplante_rueckgabe.isoformat() if ausleihe.geplante_rueckgabe else None,
            'ausleihe_id': str(ausleihe.id),
            'benutzer': ausleihe.benutzer.name if ausleihe.benutzer else 'Unbekannt'
        })
    
    return Response({
        'ware_id': ware_id,
        'ort_id': ort_id,
        'maximale_leihdauer_tage': max_tage,
        'blockierte_zeitraeume': blockierte_zeitraeume
    })


# =============================================================================
# PING / HEALTH CHECK
# =============================================================================

@api_view(['GET'])
def ping(request):
    """Einfacher Health-Check ohne Authentifizierung."""
    return Response({'ping': True, 'timestamp': timezone.now()})


@api_view(['GET'])
@jwt_required
def ping_auth(request):
    """Authentifizierter Health-Check."""
    return Response({
        'ping': True,
        'user_id': request.user_id,
        'rolle': request.user_role,
        'timestamp': timezone.now()
    })



# =============================================================================
# SCHADENSMELDUNGEN
# =============================================================================

@api_view(['GET', 'POST'])
@jwt_required
def schadensmeldungen_liste(request):
    """
    GET: Alle Schadensmeldungen für eine Ware oder Ausleihe auflisten
    POST: Neue Schadensmeldung erstellen
    """
    if request.method == 'GET':
        ware_id = request.query_params.get('ware_id')
        ausleihe_id = request.query_params.get('ausleihe_id')
        
        meldungen = Schadensmeldung.objects.all()
        
        if ware_id:
            meldungen = meldungen.filter(ware_id=ware_id)
        if ausleihe_id:
            meldungen = meldungen.filter(ausleihe_id=ausleihe_id)
        
        data = [{
            'id': str(m.id),
            'ware_id': str(m.ware_id),
            'ware_name': m.ware.name,
            'ausleihe_id': str(m.ausleihe_id) if m.ausleihe else None,
            'beschreibung': m.beschreibung,
            'rueckgeber': {
                'id': str(m.rueckgeber.id),
                'name': f"{m.rueckgeber.vorname} {m.rueckgeber.nachname}"
            } if m.rueckgeber else None,
            'erstellt_am': m.erstellt_am.isoformat(),
            'quittiert': m.quittiert,
            'quittierer': {
                'id': str(m.quittierer.id),
                'name': f"{m.quittierer.vorname} {m.quittierer.nachname}"
            } if m.quittierer else None,
            'quittiert_am': m.quittiert_am.isoformat() if m.quittiert_am else None,
            'quittierer_beschreibung': m.quittierer_beschreibung,
        } for m in meldungen]
        
        return Response(data)
    
    elif request.method == 'POST':
        data = request.data
        
        # Pflichtfelder prüfen
        ware_id = data.get('ware_id')
        beschreibung = data.get('beschreibung', '').strip()
        
        if not ware_id:
            return Response({'error': 'ware_id ist erforderlich'}, status=400)
        if not beschreibung:
            return Response({'error': 'beschreibung ist erforderlich'}, status=400)
        
        try:
            ware = Ware.objects.get(id=ware_id, aktiv=True)
        except Ware.DoesNotExist:
            return Response({'error': 'Ware nicht gefunden'}, status=404)
        
        # Ausleihe optional
        ausleihe_id = data.get('ausleihe_id')
        ausleihe = None
        if ausleihe_id:
            try:
                ausleihe = Ausleihe.objects.get(id=ausleihe_id)
            except Ausleihe.DoesNotExist:
                return Response({'error': 'Ausleihe nicht gefunden'}, status=404)
        
        # Benutzer aus der Datenbank laden
        try:
            benutzer = Benutzer.objects.get(id=request.user_id)
        except Benutzer.DoesNotExist:
            return Response({'error': 'Benutzer nicht gefunden'}, status=404)
        
        # Bei Warenverwaltung (keine Ausleihe): Mitarbeiter ist gleichzeitig Ersteller und Quittierer
        # Bei Rückgabe: Student ist Ersteller, muss quittiert werden
        ist_warenverwaltung = ausleihe is None
        
        meldung = Schadensmeldung.objects.create(
            ware=ware,
            ausleihe=ausleihe,
            beschreibung=beschreibung,
            rueckgeber=benutzer if not ist_warenverwaltung else None,
            quittiert=ist_warenverwaltung,  # Bei Warenverwaltung direkt quittiert
            quittierer=benutzer if ist_warenverwaltung else None,
            quittiert_am=timezone.now() if ist_warenverwaltung else None,
        )
        
        log_action(request, 'schadensmeldung_erstellt', 
                  details={'ware_id': str(ware.id), 'ausleihe_id': str(ausleihe.id) if ausleihe else None})
        
        return Response({
            'id': str(meldung.id),
            'ware_id': str(meldung.ware_id),
            'beschreibung': meldung.beschreibung,
            'quittiert': meldung.quittiert,
            'message': 'Schadensmeldung erstellt'
        }, status=201)


@api_view(['GET', 'PUT'])
@jwt_required
def schadensmeldung_detail(request, meldung_id):
    """
    GET: Einzelne Schadensmeldung anzeigen
    PUT: Schadensmeldung quittieren (nur Mitarbeiter+)
    """
    try:
        meldung = Schadensmeldung.objects.get(id=meldung_id)
    except Schadensmeldung.DoesNotExist:
        return Response({'error': 'Schadensmeldung nicht gefunden'}, status=404)
    
    if request.method == 'GET':
        return Response({
            'id': str(meldung.id),
            'ware_id': str(meldung.ware_id),
            'ware_name': meldung.ware.name,
            'ausleihe_id': str(meldung.ausleihe_id) if meldung.ausleihe else None,
            'beschreibung': meldung.beschreibung,
            'rueckgeber': {
                'id': str(meldung.rueckgeber.id),
                'name': f"{meldung.rueckgeber.vorname} {meldung.rueckgeber.nachname}"
            } if meldung.rueckgeber else None,
            'erstellt_am': meldung.erstellt_am.isoformat(),
            'quittiert': meldung.quittiert,
            'quittierer': {
                'id': str(meldung.quittierer.id),
                'name': f"{meldung.quittierer.vorname} {meldung.quittierer.nachname}"
            } if meldung.quittierer else None,
            'quittiert_am': meldung.quittiert_am.isoformat() if meldung.quittiert_am else None,
            'quittierer_beschreibung': meldung.quittierer_beschreibung,
        })
    
    elif request.method == 'PUT':
        # Nur Mitarbeiter+ dürfen quittieren
        if request.user_role not in ['Mitarbeiter', 'Laborleiter', 'Admin']:
            return Response({'error': 'Nur Mitarbeiter oder höher'}, status=403)
        
        data = request.data
        
        # Benutzer aus der Datenbank laden
        try:
            benutzer = Benutzer.objects.get(id=request.user_id)
        except Benutzer.DoesNotExist:
            return Response({'error': 'Benutzer nicht gefunden'}, status=404)
        
        # Quittierung
        meldung.quittiert = True
        meldung.quittierer = benutzer
        meldung.quittiert_am = timezone.now()
        
        # Beschreibung kann vom Quittierer bearbeitet werden
        if 'beschreibung' in data:
            meldung.beschreibung = data.get('beschreibung', '').strip()
        
        # Optional: Zusätzliche Ergänzung durch Quittierer (legacy)
        if 'quittierer_beschreibung' in data:
            meldung.quittierer_beschreibung = data.get('quittierer_beschreibung', '').strip()
        
        meldung.save()
        
        log_action(request, 'schadensmeldung_quittiert',
                  details={'meldung_id': str(meldung.id), 'ware_id': str(meldung.ware_id)})
        
        return Response({
            'id': str(meldung.id),
            'quittiert': True,
            'message': 'Schadensmeldung quittiert'
        })


@api_view(['GET'])
@jwt_required
def offene_schadensmeldungen(request):
    """
    Gibt alle nicht quittierten Schadensmeldungen für eine Ausleihe zurück.
    Wird vom Mitarbeiter bei der Quittierung verwendet.
    """
    ausleihe_id = request.query_params.get('ausleihe_id')
    
    if not ausleihe_id:
        return Response({'error': 'ausleihe_id ist erforderlich'}, status=400)
    
    meldungen = Schadensmeldung.objects.filter(
        ausleihe_id=ausleihe_id,
        quittiert=False
    )
    
    data = [{
        'id': str(m.id),
        'ware_id': str(m.ware_id),
        'ware_name': m.ware.name,
        'beschreibung': m.beschreibung,
        'rueckgeber': {
            'id': str(m.rueckgeber.id),
            'name': f"{m.rueckgeber.vorname} {m.rueckgeber.nachname}"
        } if m.rueckgeber else None,
        'erstellt_am': m.erstellt_am.isoformat(),
    } for m in meldungen]
    
    return Response(data)


@api_view(['GET'])
@jwt_required
def ware_schadensmeldungen(request, ware_id):
    """
    Gibt alle Schadensmeldungen für eine bestimmte Ware zurück.
    """
    try:
        ware = Ware.objects.get(id=ware_id)
    except Ware.DoesNotExist:
        return Response({'error': 'Ware nicht gefunden'}, status=404)
    
    meldungen = Schadensmeldung.objects.filter(ware=ware).order_by('-erstellt_am')
    
    data = [{
        'id': str(m.id),
        'ware_id': str(m.ware_id),
        'ware_name': m.ware.name,
        'ausleihe_id': str(m.ausleihe_id) if m.ausleihe else None,
        'beschreibung': m.beschreibung,
        'rueckgeber': {
            'id': str(m.rueckgeber.id),
            'name': f"{m.rueckgeber.vorname} {m.rueckgeber.nachname}"
        } if m.rueckgeber else None,
        'erstellt_am': m.erstellt_am.isoformat(),
        'quittiert': m.quittiert,
        'quittierer': {
            'id': str(m.quittierer.id),
            'name': f"{m.quittierer.vorname} {m.quittierer.nachname}"
        } if m.quittierer else None,
        'quittiert_am': m.quittiert_am.isoformat() if m.quittiert_am else None,
        'quittierer_beschreibung': m.quittierer_beschreibung,
    } for m in meldungen]
    
    return Response(data)


# =============================================================================
# SYSTEM-EINSTELLUNGEN API
# =============================================================================

@api_view(['GET'])
@jwt_required
def system_einstellungen_liste(request):
    """
    Gibt alle System-Einstellungen zurück.
    Alle authentifizierten Benutzer können lesen.
    """
    einstellungen = SystemEinstellung.objects.filter(aktiv=True)
    
    data = [{
        'id': str(e.id),
        'schluessel': e.schluessel,
        'wert': e.wert,
        'beschreibung': e.beschreibung,
        'aktualisiert_am': e.aktualisiert_am.isoformat(),
    } for e in einstellungen]
    
    return Response(data)


@api_view(['GET'])
@jwt_required
def system_einstellung_detail(request, schluessel):
    """
    Gibt eine spezifische System-Einstellung zurück.
    """
    try:
        einstellung = SystemEinstellung.objects.get(schluessel=schluessel)
        return Response({
            'id': str(einstellung.id),
            'schluessel': einstellung.schluessel,
            'wert': einstellung.wert,
            'beschreibung': einstellung.beschreibung,
            'aktualisiert_am': einstellung.aktualisiert_am.isoformat(),
        })
    except SystemEinstellung.DoesNotExist:
        return Response({'error': 'Einstellung nicht gefunden'}, status=404)


@api_view(['POST', 'PUT'])
@jwt_required
@require_role(['Laborleiter', 'Admin'])
def system_einstellung_aktualisieren(request):
    """
    Aktualisiert oder erstellt System-Einstellungen.
    Nur Laborleiter und Admin dürfen Einstellungen ändern.
    
    POST/PUT {"schluessel": "...", "wert": "...", "beschreibung": "..."}
    """
    schluessel = request.data.get('schluessel')
    wert = request.data.get('wert')
    beschreibung = request.data.get('beschreibung', '')
    
    if not schluessel or wert is None:
        return Response({
            'error': 'schluessel und wert sind erforderlich'
        }, status=400)
    
    # Erlaubte Schlüssel für Sicherheit
    ERLAUBTE_SCHLUESSEL = [
        'antenna_port',
        'antenna_baudrate',
        'cardreader_port',
        'cardreader_baudrate',
        'backend_url',
    ]
    
    if schluessel not in ERLAUBTE_SCHLUESSEL:
        return Response({
            'error': f'Ungültiger schluessel. Erlaubt: {", ".join(ERLAUBTE_SCHLUESSEL)}'
        }, status=400)
    
    einstellung = SystemEinstellung.set_value(schluessel, wert, beschreibung)
    
    log_action(request, 'system_einstellung_geaendert', details={
        'schluessel': schluessel,
        'wert': wert
    })
    
    return Response({
        'success': True,
        'id': str(einstellung.id),
        'schluessel': einstellung.schluessel,
        'wert': einstellung.wert,
        'beschreibung': einstellung.beschreibung,
        'message': 'Einstellung gespeichert'
    })


@api_view(['GET'])
@permission_classes([AllowAny])
def system_einstellungen_oeffentlich(request):
    """
    Öffentliche API für grundlegende System-Einstellungen.
    Wird vom Frontend beim Start geladen, um Hardware-Ports zu konfigurieren.
    Keine Authentifizierung nötig.
    """
    # Nur diese Einstellungen sind öffentlich
    OEFFENTLICHE_SCHLUESSEL = [
        'antenna_port',
        'antenna_baudrate',
        'cardreader_port',
        'cardreader_baudrate',
    ]
    
    defaults = {
        'antenna_port': '/dev/ttyUSB0',
        'antenna_baudrate': '115200',
        'cardreader_port': '/dev/ttyUSB0',
        'cardreader_baudrate': '9600',
    }
    
    result = {}
    for schluessel in OEFFENTLICHE_SCHLUESSEL:
        wert = SystemEinstellung.get_value(schluessel, defaults.get(schluessel))
        result[schluessel] = wert
    
    return Response(result)
