import threading
from .models import Ware, Ausleihe

class InventoryThread(threading.Thread):
    def __init__(self, reader, timer_value=25):
        super().__init__()
        self.reader = reader
        self.info = []         # Liste der aktiven eindeutigen EPCs
        self._epc_map = {}     # Hilfsdict: epc -> Listenindex
        self.timer_value = timer_value
        self.running = False

    def run(self):
        self.running = True
        while self.running:
            resp = self.reader.read_response("inventory")
            if resp is None or 'error' in resp: 
                self._update_timers_and_cleanup()
                continue

            try: 
                parsed = self.reader.parse_inventory(resp["payload_raw"])
                epc = parsed.get("epc", None)
            except Exception:
                epc = None
            if epc:
                idx = self._epc_map.get(epc)
                if idx is not None:
                    # EPC ist schon drin → Timer resetten
                    self.info[idx]["timer"] = self.timer_value
                    self.info[idx]['rssi'] = parsed['rssi']
                    self.info[idx]['ant'] = parsed['ant']
                    self.info[idx]['cn'] = parsed['cn']
                else:
                    try:
                        ware = Ware.objects.get(rfid_tag=str(epc), aktiv=True)
                        name = str(ware.name)
                        desc = str(ware.beschreibung)
                        try:
                            ausleihe = Ausleihe.objects.get(ware=ware, status='aktiv', aktiv=True)
                            loaned_by = str(ausleihe.benutzer.id)
                        except Ausleihe.DoesNotExist:
                            loaned_by = 'Niemand'
                    except Ware.DoesNotExist:
                        name = 'Name not found'
                        desc = 'No Description'
                        loaned_by = 'Niemand'

                    # Neu: neues Dict bauen, speichern, index merken
                    combined = resp.copy()
                    combined.update(parsed)
                    combined["timer"] = self.timer_value
                    combined["name"] = name
                    combined["desc"] = desc
                    combined["loaned_by"] = loaned_by
                    # payload_raw (Bytes) entfernen - nicht JSON-serialisierbar
                    combined.pop("payload_raw", None)
                    self.info.append(combined)
                    self._epc_map[epc] = len(self.info) - 1

            self._update_timers_and_cleanup()

            # Stop wenn Inventory zuende
            if resp.get("status") == 0x12:
                break

    def terminate(self):
        self.running = False

    def _update_timers_and_cleanup(self):
        # Timer-Update & Löschen von toten Einträgen
        to_delete = []
        for i, entry in enumerate(self.info):
            entry["timer"] -= 1
            if entry["timer"] <= 0:
                to_delete.append(i)
        # Von hinten nach vorn löschen (damit Indices stimmen)
        for i in reversed(to_delete):
            epc_del = self.info[i].get("epc")
            if epc_del and epc_del in self._epc_map:
                del self._epc_map[epc_del]
            del self.info[i]
        # Map-Indices aktualisieren, falls Listengröße sich änderte
        # (Optional, falls häufige EPCs erwartet werden)
        self._epc_map = {entry["epc"]: idx for idx, entry in enumerate(self.info) if "epc" in entry}
