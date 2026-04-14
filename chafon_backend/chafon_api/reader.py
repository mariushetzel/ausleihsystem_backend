import serial
import struct
import random
import time

class UHFReader:
    hComm = 0

    HEAD = 0xCF
    ADDR = 0xFF  # broadcast or device address

    COMMAND_NAMES = {
        0x0001: "INVENTORY_CONTINUE",
        0x0002: "INVENTORY_STOP",
        0x0050: "MODULE_INIT",
        0x0052: "MODULE_REBOOT",
        0x0053: "SET_POWER",
        0x0071: "SET_ALL_PARAM",
        0x0072: "GET_ALL_PARAM",
        0x0079: "ATNN_RSSI_FILTER"
    }

    def __init__(self, port="COM3", baudrate=115200, timeout=0.1):
        self.ser = serial.Serial(port, baudrate, timeout=timeout)
        self.timeout = timeout

    def close(self):
        """Close the serial connection."""
        if self.ser.is_open:
            self.ser.close()

    def _baudrate_to_index(self, baudrate):
        """Konvertiere Baudrate zu Index für das Protokoll"""
        baudrate_map = {
            9600: 0,
            19200: 1,
            38400: 2,
            57600: 3,
            115200: 4
        }
        # Falls es schon ein Index ist (0-4), gib ihn zurück
        if isinstance(baudrate, int) and 0 <= baudrate <= 4:
            return baudrate
        return baudrate_map.get(int(baudrate), 4)  # Default 115200

    # ------------------------------------------------------------
    # CRC16 CCITT (0x8408)
    # ------------------------------------------------------------
    def crc16(self, data: bytes):
        crc = 0xFFFF
        for byte in data:
            crc ^= byte
            for _ in range(8):
                if crc & 1:
                    crc = (crc >> 1) ^ 0x8408
                else:
                    crc >>= 1
        return struct.pack(">H", crc & 0xFFFF)

    # ------------------------------------------------------------
    # Senden + Antwort empfangen
    # ------------------------------------------------------------
    def send_command(self, hcomm, cmd, payload=b"", no_read=False):
        if self.hComm == hcomm:
            frame = bytearray([
                self.HEAD,
                self.ADDR
            ])
            frame += struct.pack(">H", cmd)
            frame.append(len(payload))
            frame += payload
            frame += self.crc16(frame)

            self.ser.write(frame)
            if not no_read:
                parsed_cmd = self.COMMAND_NAMES.get(cmd, hex(cmd))
                return self.read_response(parsed_cmd)
            return None
        else:
            return {
                "cmd": self.COMMAND_NAMES.get(cmd, hex(cmd)),
                "status": 666
            }

    # ------------------------------------------------------------
    # Antwort parsen → menschlich lesbares Dict
    # ------------------------------------------------------------
    def read_response(self, parsed_cmd):
        start = time.time()
        while True:
            if self.ser.in_waiting > 0:
                head = self.ser.read(1)
                if head != b'\xCF':
                    return {"error": parsed_cmd + ": Invalid header"}

                addr = self.ser.read(1)
                cmd_bytes = self.ser.read(2)
                length_byte = self.ser.read(1)
                status_byte = self.ser.read(1)
                payload_len = length_byte[0] - 1 if length_byte[0] > 0 else 0
                payload = self.ser.read(payload_len)
                crc_bytes = self.ser.read(2)

                # Rekonstruiere alle bytes OHNE die zwei letzten CRC-Bytes:
                raw_without_crc = (
                        head + addr + cmd_bytes + length_byte + status_byte + payload
                )
                calculated_crc = self.crc16(raw_without_crc)  # gibt 2 Bytes zurück

                if crc_bytes != calculated_crc:
                    return {"error": parsed_cmd + ": CRC mismatch"}

                resp = {
                    "cmd": self.COMMAND_NAMES.get(struct.unpack(">H", cmd_bytes)[0], cmd_bytes.hex()),
                    "status": status_byte[0],
                    "payload_raw": payload
                }

                return resp

            if (time.time() - start) > self.timeout:
                return {"error": parsed_cmd + ": Timeout waiting for response", "status": 1001}
            time.sleep(0.001)

    # ------------------------------------------------------------
    # Inventory response parsing
    # ------------------------------------------------------------
    def parse_inventory(self, data: bytes):
        if len(data) < 6:
            return {}
        rssi = struct.unpack(">h", data[0:2])[0]
        ant = data[2]
        channel = data[3]
        epc_len = data[4]
        epc = data[5:5+epc_len].hex().upper()

        return {
            "rssi": rssi,
            "ant": ant,
            "cn": channel,
            "epc_len": epc_len,
            "epc": epc
        }

    # ------------------------------------------------------------
    # Get-all-parameters parsing
    # ------------------------------------------------------------
    def parse_all_params(self, data: bytes):
        if len(data) < 25:
            return {"error": "invalid length"}

        # first 7 fixed bytes
        addr, proto, mode, interface, baud, wgset, ant = data[:7]

        # frequency block (8 bytes)
        region = data[7]
        startfreq_int = struct.unpack(">H", data[8:10])[0]
        startfreq_dec = struct.unpack(">H", data[10:12])[0]
        stepfreq = struct.unpack(">H", data[12:14])[0]
        cnt = data[14]

        # remaining bytes
        rfpower = data[15]
        area = data[16]
        q = data[17]
        session = data[18]
        acs_addr = data[19]
        acs_len = data[20]
        filter_time = data[21]
        trigger_time = data[22]
        buzzer_time = data[23]
        poll_interval = data[24]

        return {
            "addr": addr,
            "rf_protocol": proto,
            "work_mode": mode,
            "interface": interface,
            "baudrate": baud,
            "wgset": wgset,
            "antenna_mask": ant,

            "rfid_freq": {
                "REGION": region,
                "STRATFREI": startfreq_int,
                "STRATFRED": startfreq_dec,
                "STEPFRE": stepfreq,
                "CN": cnt,
            },

            "rf_power": rfpower,
            "inquiry_area": area,
            "qvalue": q,
            "session": session,

            "acs_addr": acs_addr,
            "acs_data_len": acs_len,
            "filter_time": filter_time,
            "trigger_time": trigger_time,
            "buzzer_time": buzzer_time,
            "polling_interval": poll_interval
        }

    # ------------------------------------------------------------
    # RSSI filter parsing
    # ------------------------------------------------------------
    def parse_rssi_filter(self, data: bytes):
        if len(data) < 19:
            return {}

        option = data[0]
        basic_rssi = struct.unpack(">h", data[1:3])[0]
        offsets = list(data[3:19])

        return {
            "option": option,
            "basic_rssi": basic_rssi,
            "offsets": offsets
        }

    # ============================================================
    # PUBLIC API — all return the parsed reader response
    # ============================================================

    def rfm_module_init(self):
        resp = self.send_command(0, 0x0050)
        if 'error' not in resp:
            self.hComm = random.randint(0, 255)
        return resp

    def rfm_reboot(self, hcomm):
        resp = self.send_command(hcomm, 0x0052)
        return resp

    def rfm_set_pwr(self, hcomm, pwr: int):
        payload = bytes([max(0, min(30, pwr)), 0])
        resp = self.send_command(hcomm,0x0053, payload)
        return resp

    def rfm_set_all_param(self, hcomm, params: dict):
        # validate completeness
        required = [
            "addr", "rf_protocol", "work_mode", "interface", "baudrate", "wgset",
            "antenna_mask", "rfid_freq", "rf_power", "inquiry_area", "qvalue",
            "session", "acs_addr", "acs_data_len", "filter_time", "trigger_time",
            "buzzer_time", "polling_interval"
        ]
        for r in required:
            if r not in params:
                raise ValueError(f"missing parameter: {r}")

        f = params["rfid_freq"]

        # Alle Werte auf 0-255 begrenzen (Byte-Bereich)
        def to_byte(val):
            return int(val) & 0xFF

        # pack structure exactly like manual (25 bytes)
        # Baudrate ist ein Index (0-7), nicht der tatsächliche Wert!
        baudrate_index = self._baudrate_to_index(params["baudrate"])
        
        payload = bytearray([
            to_byte(params["addr"]),
            to_byte(params["rf_protocol"]),
            to_byte(params["work_mode"]),
            to_byte(params["interface"]),
            to_byte(baudrate_index),
            to_byte(params["wgset"]),
            to_byte(params["antenna_mask"]),
            to_byte(f["REGION"])
        ])

        payload += struct.pack(">H", int(f["STRATFREI"]) & 0xFFFF)
        payload += struct.pack(">H", int(f["STRATFRED"]) & 0xFFFF)
        payload += struct.pack(">H", int(f["STEPFRE"]) & 0xFFFF)
        payload.append(to_byte(f["CN"]))

        payload.append(to_byte(params["rf_power"]))
        payload.append(to_byte(params["inquiry_area"]))
        payload.append(to_byte(params["qvalue"]))
        payload.append(to_byte(params["session"]))
        payload.append(to_byte(params["acs_addr"]))
        payload.append(to_byte(params["acs_data_len"]))
        payload.append(to_byte(params["filter_time"]))
        payload.append(to_byte(params["trigger_time"]))
        payload.append(to_byte(params["buzzer_time"]))
        payload.append(to_byte(params["polling_interval"]))

        if len(payload) != 25:
            raise RuntimeError(f"rfm_set_all_param payload must be 25 bytes, got {len(payload)}")

        resp = self.send_command(hcomm,0x0071, payload)
        return resp

    def rfm_get_all_param(self, hcomm):
        resp = self.send_command(hcomm, 0x0072)
        if 'error' not in resp:
            resp.update(self.parse_all_params(resp["payload_raw"]))
        return resp

    def rfm_inventoryiso_continue(self, hcomm, inv_type=0, param=0):
        payload = bytes([inv_type]) + struct.pack(">I", param)
        resp = self.send_command(hcomm, 0x0001, payload, no_read=True)
        return resp

    def rfm_inventoryiso_stop(self, hcomm):
        resp = self.send_command(hcomm, 0x0002)
        return resp

    def rfm_set_get_atnn_rssi_filter(self, hcomm, option, basic_rssi, offsets):
        if len(offsets) != 16:
            raise ValueError("offsets must be 16 bytes")
        payload = bytes([option]) + struct.pack(">h", basic_rssi) + bytes(offsets)
        resp = self.send_command(hcomm,0x0079, payload)
        if 'error' not in resp:
            resp.update(self.parse_rssi_filter(resp["payload_raw"]))
        return resp