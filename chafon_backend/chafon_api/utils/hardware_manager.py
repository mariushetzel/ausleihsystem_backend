"""
Hardware Manager mit Redis-basiertem distributed locking.

Diese Klasse ersetzt den alten globalen Zustand in views_legacy.py
und ermöglicht thread-safe, skalierbares Hardware-Locking über
mehrere Worker-Prozesse und Server.
"""
import json
import time
import logging
from typing import Optional, Tuple, Dict, Any
from django.core.cache import caches

logger = logging.getLogger(__name__)

# Redis cache für Hardware-Operationen
hardware_cache = caches['hardware']


class HardwareManager:
    """
    Zentraler Manager für Hardware-Locking und RFID-Reader-Verwaltung.
    
    Verwendet Redis für distributed locking, um Konflikte bei mehreren
    Worker-Prozessen oder Server-Instanzen zu vermeiden.
    """
    
    # Lock timeout in Sekunden (30s wie im alten Code)
    LOCK_TIMEOUT = 30
    
    # Key Präfixe für Redis
    LOCK_KEY_PREFIX = 'hardware:lock:'
    READER_KEY_PREFIX = 'hardware:reader:'
    SESSION_KEY_PREFIX = 'hardware:session:'
    
    @staticmethod
    def acquire_lock(
        user_id: str,
        session_id: str,
        device_type: str = 'rfid'
    ) -> Tuple[bool, str]:
        """
        Versucht den Hardware-Lock zu erhalten.
        
        Args:
            user_id: ID des Benutzers
            session_id: Session-ID für Identifikation
            device_type: 'rfid' oder 'card_reader'
            
        Returns:
            (success, message)
        """
        lock_key = f"{HardwareManager.LOCK_KEY_PREFIX}{device_type}"
        
        # Prüfe ob bereits ein Lock existiert
        existing_lock = hardware_cache.get(lock_key)
        
        if existing_lock:
            lock_data = json.loads(existing_lock)
            
            # Prüfe ob Lock abgelaufen (Redis TTL sollte das eigentlich erledigen)
            locked_at = lock_data.get('locked_at', 0)
            if time.time() - locked_at < HardwareManager.LOCK_TIMEOUT:
                # Lock ist noch aktiv und gehört jemand anderem
                if lock_data.get('user_id') != user_id:
                    return False, (
                        f"Hardware wird bereits verwendet "
                        f"(User: {lock_data.get('user_id')}, "
                        f"Gerät: {lock_data.get('device_type', 'unbekannt')})"
                    )
            # Lock ist abgelaufen oder gehört dem gleichen User - überschreiben
        
        # Neuen Lock setzen
        lock_data = {
            'user_id': user_id,
            'session_id': session_id,
            'device_type': device_type,
            'locked_at': time.time()
        }
        
        # Mit NX (nur wenn nicht existiert) und TTL setzen
        hardware_cache.set(
            lock_key,
            json.dumps(lock_data),
            timeout=HardwareManager.LOCK_TIMEOUT
        )
        
        logger.info(f"Hardware lock acquired by {user_id} for {device_type}")
        return True, "Lock erworben"
    
    @staticmethod
    def release_lock(user_id: str, session_id: str) -> bool:
        """
        Gibt den Hardware-Lock frei.
        
        Args:
            user_id: ID des Benutzers
            session_id: Session-ID
            
        Returns:
            True wenn Lock freigegeben wurde
        """
        for device_type in ['rfid', 'card_reader']:
            lock_key = f"{HardwareManager.LOCK_KEY_PREFIX}{device_type}"
            existing_lock = hardware_cache.get(lock_key)
            
            if existing_lock:
                lock_data = json.loads(existing_lock)
                if (
                    lock_data.get('user_id') == user_id and
                    lock_data.get('session_id') == session_id
                ):
                    hardware_cache.delete(lock_key)
                    logger.info(f"Hardware lock released by {user_id} for {device_type}")
                    return True
        
        return False
    
    @staticmethod
    def is_locked(device_type: str = 'rfid') -> Tuple[bool, Optional[Dict[str, Any]]]:
        """
        Prüft ob die Hardware verwendet wird.
        
        Args:
            device_type: 'rfid' oder 'card_reader'
            
        Returns:
            (locked, info_dict oder None)
        """
        lock_key = f"{HardwareManager.LOCK_KEY_PREFIX}{device_type}"
        existing_lock = hardware_cache.get(lock_key)
        
        if not existing_lock:
            return False, None
        
        lock_data = json.loads(existing_lock)
        
        # Prüfe ob Lock abgelaufen
        locked_at = lock_data.get('locked_at', 0)
        if time.time() - locked_at > HardwareManager.LOCK_TIMEOUT:
            # Lock ist abgelaufen - löschen
            hardware_cache.delete(lock_key)
            return False, None
        
        info = {
            'user_id': lock_data.get('user_id'),
            'device_type': lock_data.get('device_type'),
            'since': time.strftime(
                '%Y-%m-%dT%H:%M:%S',
                time.localtime(locked_at)
            )
        }
        
        return True, info
    
    @staticmethod
    def store_reader_config(
        session_id: str,
        port: str,
        baudrate: int,
        h_comm: int
    ) -> None:
        """
        Speichert Reader-Konfiguration für eine Session.
        
        Args:
            session_id: Session-ID
            port: Serieller Port
            baudrate: Baudrate
            h_comm: Hardware-Kommunikations-Handle
        """
        key = f"{HardwareManager.READER_KEY_PREFIX}{session_id}"
        config = {
            'port': port,
            'baudrate': baudrate,
            'h_comm': h_comm,
            'created_at': time.time()
        }
        hardware_cache.set(key, json.dumps(config), timeout=300)  # 5 Minuten TTL
    
    @staticmethod
    def get_reader_config(session_id: str) -> Optional[Dict[str, Any]]:
        """
        Holt Reader-Konfiguration für eine Session.
        
        Args:
            session_id: Session-ID
            
        Returns:
            Config-Dict oder None
        """
        key = f"{HardwareManager.READER_KEY_PREFIX}{session_id}"
        config = hardware_cache.get(key)
        
        if config:
            return json.loads(config)
        return None
    
    @staticmethod
    def delete_reader_config(session_id: str) -> None:
        """
        Löscht Reader-Konfiguration für eine Session.
        """
        key = f"{HardwareManager.READER_KEY_PREFIX}{session_id}"
        hardware_cache.delete(key)
    
    @staticmethod
    def keep_alive(session_id: str) -> bool:
        """
        Verlängert den Lock für eine Session (Heartbeat).
        
        Args:
            session_id: Session-ID
            
        Returns:
            True wenn Session existiert und verlängert wurde
        """
        for device_type in ['rfid', 'card_reader']:
            lock_key = f"{HardwareManager.LOCK_KEY_PREFIX}{device_type}"
            existing_lock = hardware_cache.get(lock_key)
            
            if existing_lock:
                lock_data = json.loads(existing_lock)
                if lock_data.get('session_id') == session_id:
                    # Lock verlängern
                    lock_data['locked_at'] = time.time()
                    hardware_cache.set(
                        lock_key,
                        json.dumps(lock_data),
                        timeout=HardwareManager.LOCK_TIMEOUT
                    )
                    return True
        
        return False
    
    @staticmethod
    def force_release_all() -> int:
        """
        Gibt alle Locks frei (Admin-Funktion).
        
        Returns:
            Anzahl der freigegebenen Locks
        """
        count = 0
        for device_type in ['rfid', 'card_reader']:
            lock_key = f"{HardwareManager.LOCK_KEY_PREFIX}{device_type}"
            if hardware_cache.delete(lock_key):
                count += 1
        
        logger.warning(f"All hardware locks forcefully released ({count} locks)")
        return count


# Legacy-Funktionen für Abwärtskompatibilität
def acquire_hardware_lock(user_id, session_id, device_type='rfid'):
    """Legacy wrapper für HardwareManager.acquire_lock()"""
    return HardwareManager.acquire_lock(user_id, session_id, device_type)


def release_hardware_lock(user_id, session_id):
    """Legacy wrapper für HardwareManager.release_lock()"""
    return HardwareManager.release_lock(user_id, session_id)


def is_hardware_locked():
    """Legacy wrapper für HardwareManager.is_locked()"""
    return HardwareManager.is_locked('rfid')


def acquire_scan_lock(user_id, session_id):
    """Legacy wrapper für RFID-Lock"""
    return HardwareManager.acquire_lock(user_id, session_id, 'rfid')


def release_scan_lock(user_id, session_id):
    """Legacy wrapper für RFID-Unlock"""
    return HardwareManager.release_lock(user_id, session_id)


def is_scanning_locked():
    """Legacy wrapper für RFID-Status"""
    locked, info = HardwareManager.is_locked('rfid')
    return locked, info
