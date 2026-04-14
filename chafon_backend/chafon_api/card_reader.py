"""
Einfacher Card Reader - Direktes Lesen ohne Thread.
Öffnet die serielle Verbindung kurz, liest und schließt wieder.
"""

import serial
import time


class CardReader:
    """
    Einfacher Card Reader für direktes Polling.
    Kein Thread - stattdessen kurzes Öffnen/Lesen/Schließen bei jedem Aufruf.
    """
    
    def __init__(self, port='/dev/ttyUSB0', baudrate=9600):
        self.port = port
        self.baudrate = baudrate
        self._last_code = None
        
    def read_card(self, timeout_ms=700):
        """
        Liest von der seriellen Schnittstelle.
        
        Args:
            timeout_ms: Wie lange auf Karte warten (Standard 700ms - mehr als 500ms Intervall des Readers)
            
        Returns:
            str: Kartennummer oder None wenn keine Karte
        """
        try:
            with serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=timeout_ms / 1000.0,  # ms zu Sekunden
                write_timeout=1,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE
            ) as ser:
                # Buffer leeren (alte Daten wegwerfen)
                ser.reset_input_buffer()
                
                # Kurz warten und lesen
                start_time = time.time()
                buffer = ""
                
                while (time.time() - start_time) < (timeout_ms / 1000.0):
                    if ser.in_waiting > 0:
                        data = ser.read(ser.in_waiting).decode('utf-8', errors='ignore')
                        buffer += data
                        
                        # Zeilenweise prüfen
                        if '\n' in buffer:
                            lines = buffer.split('\n')
                            for line in lines[:-1]:  # Alle vollständigen Zeilen
                                line = line.strip()
                                if self._is_valid_card(line):
                                    self._last_code = line.upper()
                                    return self._last_code
                            buffer = lines[-1]  # Rest behalten
                    
                    time.sleep(0.01)  # 10ms warten
                
                return None
                
        except serial.SerialException as e:
            return None
        except Exception as e:
            return None
    
    def _is_valid_card(self, line):
        """Prüft ob die Zeile eine gültige Kartennummer ist."""
        if not line or len(line) < 8:
            return False
        
        # System-Meldungen ignorieren
        if line.startswith(("Seriennummer", "Firmware", "RFID-Modul", "Reader")):
            return False
        
        # Nur Hex-Zeichen erlaubt (Kartennummern sind Hex)
        return all(c in '0123456789ABCDEFabcdef' for c in line)


# Singleton-Instanz für den aktiven Reader
_active_reader = None


def start_reader(port='/dev/ttyUSB0', baudrate=9600):
    """Startet einen neuen Card Reader (ersetzt alten falls vorhanden)."""
    global _active_reader
    _active_reader = CardReader(port, baudrate)
    return _active_reader


def stop_reader():
    """Stoppt den aktiven Reader."""
    global _active_reader
    _active_reader = None


def read_card(timeout_ms=150):
    """
    Liest von aktivem Reader oder startet temporär einen.
    
    Returns:
        str: Kartennummer oder None
    """
    global _active_reader
    
    if _active_reader is None:
        return None
    
    return _active_reader.read_card(timeout_ms)


def get_last_code():
    """Gibt die letzte gelesene Karte zurück (für Polling)."""
    global _active_reader
    if _active_reader:
        code = _active_reader._last_code
        _active_reader._last_code = None  # Reset nach Lesen
        return code
    return None
