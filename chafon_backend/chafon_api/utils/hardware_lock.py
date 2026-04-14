"""
Hardware-Locking für RFID-Antenne und Kartenleser.

ACHTUNG: Aktuell nur prozess-lokal. Für Multi-Worker-Setup
muss dies zu Redis/Distributed Locking geändert werden.
"""
from datetime import datetime, timedelta

# Global State für Hardware-Locking
hardware_lock = {
    'locked_by': None,      # user_id oder None
    'locked_at': None,      # Zeitstempel
    'session_id': None,     # Für Identifikation
    'device_type': None     # 'rfid' oder 'card_reader'
}


def acquire_hardware_lock(user_id, session_id, device_type='rfid'):
    """
    Versucht den Hardware-Lock zu erhalten.
    Gibt (success, message) zurück.
    """
    global hardware_lock
    
    # Prüfe ob jemand anders die Hardware nutzt (Timeout nach 30 Sekunden)
    if hardware_lock['locked_by'] and hardware_lock['locked_at']:
        lock_age = datetime.now() - hardware_lock['locked_at']
        if lock_age < timedelta(seconds=30):
            if hardware_lock['locked_by'] != user_id:
                return False, f"Hardware wird bereits verwendet (User: {hardware_lock['locked_by']}, Gerät: {hardware_lock.get('device_type', 'unbekannt')})"
        else:
            # Lock ist abgelaufen, freigeben
            hardware_lock['locked_by'] = None
            hardware_lock['locked_at'] = None
            hardware_lock['session_id'] = None
            hardware_lock['device_type'] = None
    
    # Lock setzen
    hardware_lock['locked_by'] = user_id
    hardware_lock['locked_at'] = datetime.now()
    hardware_lock['session_id'] = session_id
    hardware_lock['device_type'] = device_type
    return True, "Lock erworben"


def release_hardware_lock(user_id, session_id):
    """
    Gibt den Hardware-Lock frei.
    """
    global hardware_lock
    
    if hardware_lock['locked_by'] == user_id and hardware_lock['session_id'] == session_id:
        hardware_lock['locked_by'] = None
        hardware_lock['locked_at'] = None
        hardware_lock['session_id'] = None
        hardware_lock['device_type'] = None
        return True
    return False


def is_hardware_locked():
    """
    Prüft ob die Hardware verwendet wird.
    Gibt (locked, info) zurück.
    """
    global hardware_lock
    
    if not hardware_lock['locked_by']:
        return False, None
    
    lock_age = datetime.now() - hardware_lock['locked_at']
    
    if lock_age > timedelta(seconds=30):
        # Lock abgelaufen
        hardware_lock['locked_by'] = None
        hardware_lock['locked_at'] = None
        hardware_lock['session_id'] = None
        hardware_lock['device_type'] = None
        return False, None
    
    return True, {
        'user_id': hardware_lock['locked_by'],
        'device_type': hardware_lock.get('device_type'),
        'since': hardware_lock['locked_at'].isoformat()
    }


# Legacy-Funktionen für Abwärtskompatibilität (RFID)
def acquire_scan_lock(user_id, session_id):
    return acquire_hardware_lock(user_id, session_id, 'rfid')


def release_scan_lock(user_id, session_id):
    return release_hardware_lock(user_id, session_id)


def is_scanning_locked():
    locked, info = is_hardware_locked()
    if info and info.get('device_type') != 'rfid':
        return False, None  # Nur RFID-Lock zählt für alte Funktionen
    return locked, info
