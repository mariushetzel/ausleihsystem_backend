from threading import Thread
import serial
import time
import logging

logger = logging.getLogger(__name__)

class CardThread(Thread):
    def __init__(self, port, baudrate):
        super(CardThread, self).__init__()
        self.code = None
        self.flag = True
        self.daemon = True  # Wichtig: Thread beendet sich wenn Hauptprogramm endet

        self.ser = serial.Serial()
        self.ser.port = port
        self.ser.baudrate = 9600
        self.ser.timeout = 0.1  # 100ms Timeout für schnelleres Polling
        self.ser.write_timeout = 1
        
        # Buffer leeren beim Start
        try:
            self.ser.open()
            time.sleep(0.1)
            self.ser.reset_input_buffer()
            self.ser.reset_output_buffer()
        except serial.SerialException as e:
            raise Exception(f"Konnte Card Reader nicht öffnen: {e}")

        if self.ser.is_open:
            logger.info(f"Card Reader geöffnet auf {port} @ 9600 baud")
        else:
            self.terminate()

    def run(self):
        buffer = ""
        try:
            while self.flag:
                try:
                    # Nicht-blockierend mit Timeout lesen
                    if self.ser.in_waiting > 0:
                        data = self.ser.read(self.ser.in_waiting).decode('utf-8', errors='ignore')
                        buffer += data
                        
                        # Zeilenweise verarbeiten
                        while '\n' in buffer:
                            line, buffer = buffer.split('\n', 1)
                            line = line.strip()
                            
                            if not line:
                                continue
                            
                            # Raw-Daten-Debug entfernt
                            
                            # System-Informationen ignorieren
                            if line.startswith("Seriennummer") or \
                               line.startswith("Firmware") or \
                               line.startswith("RFID-Modul") or \
                               line.startswith("Reader"):
                                continue
                            
                            # Karten-ID erkannt (nur Hex-Zeichen)
                            if len(line) >= 8 and all(c in '0123456789ABCDEFabcdef' for c in line):
                                self.code = line.upper()
                                logger.info(f"Karte erkannt: {self.code}")
                    else:
                        # Kurze Pause wenn keine Daten vorhanden
                        time.sleep(0.05)
                        
                except Exception as e:
                    logger.error(f"Card Reader Fehler: {e}")
                    time.sleep(0.1)
                    
        except Exception as e:
            logger.info(f"Card Thread beendet: {e}")

    def terminate(self):
        self.flag = False
        try:
            if self.ser and self.ser.is_open:
                self.ser.close()
        except:
            pass
