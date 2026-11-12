#!/usr/bin/env python3
"""Bluetooth-FTMS-Anbindung einer Fahrradrolle (Fitness Machine Service).

Befehle: ERG (Zielleistung in Watt), Widerstand (Stufe), Simulation (Steigung in %).
Daten:   Leistung, Trittfrequenz, Geschwindigkeit (Indoor Bike Data).

Die Rolle akzeptiert meist nur eine Bluetooth-Verbindung gleichzeitig –
andere Apps (Handy) vorher trennen.
"""
import asyncio
import struct
import threading

from bleak import BleakClient, BleakScanner

FTMS_SERVICE = "00001826-0000-1000-8000-00805f9b34fb"
INDOOR_BIKE_DATA = "00002ad2-0000-1000-8000-00805f9b34fb"
CONTROL_POINT = "00002ad9-0000-1000-8000-00805f9b34fb"

RESULTS = {1: "OK", 2: "nicht unterstützt", 3: "ungültiger Wert", 4: "fehlgeschlagen", 5: "keine Kontrolle"}


def parse_indoor_bike_data(data: bytes) -> dict:
    """Dekodiert die FTMS-Charakteristik 'Indoor Bike Data' (0x2AD2)."""
    flags = int.from_bytes(data[0:2], "little")
    i = 2
    out = {}

    def take(fmt):
        nonlocal i
        v = struct.unpack_from("<" + fmt, data, i)[0]
        i += struct.calcsize(fmt)
        return v

    try:
        if not flags & 0x0001:  # Bit 0 = 0 bedeutet: Geschwindigkeit vorhanden
            out["speed"] = take("H") / 100.0
        if flags & 0x0002:
            take("H")  # Durchschnittsgeschwindigkeit
        if flags & 0x0004:
            out["cadence"] = take("H") / 2.0
        if flags & 0x0008:
            take("H")  # Durchschnittstrittfrequenz
        if flags & 0x0010:
            lo, hi = take("H"), take("B")
            out["distance"] = lo + (hi << 16)
        if flags & 0x0020:
            out["resistance"] = take("h")
        if flags & 0x0040:
            out["power"] = take("h")
        if flags & 0x0080:
            take("h")  # Durchschnittsleistung
        if flags & 0x0100:
            out["kcal"] = take("H"); take("H"); take("B")
        if flags & 0x0200:
            out["hr"] = take("B")
    except struct.error:
        pass
    return out


class Trainer:
    """Kapselt die BLE-Verbindung; läuft in einem eigenen asyncio-Thread."""

    def __init__(self, on_data, on_status):
        self.on_data = on_data
        self.on_status = on_status
        self.client = None
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever, daemon=True).start()

    def run(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self.loop)

    async def scan(self):
        self.on_status("Suche Rollen (10 s) …")
        found = await BleakScanner.discover(timeout=10, return_adv=True)
        self.found = {d.address: d for d, a in found.values()}
        devs = [(d.address, a.local_name or d.name or "?") for d, a in found.values()
                if FTMS_SERVICE in [u.lower() for u in a.service_uuids]]
        self.on_status(f"{len(devs)} Rolle(n) gefunden" if devs else
                       "Keine Rolle gefunden – Handy/Woosh getrennt? Rolle wach (kurz treten)?")
        return devs

    async def connect(self, address):
        self.on_status(f"Verbinde mit {address} …")
        target = getattr(self, "found", {}).get(address, address)
        last = None
        for attempt in range(1, 4):
            try:
                self.client = BleakClient(target, timeout=20,
                                          disconnected_callback=lambda c: self.on_status("Verbindung getrennt"))
                await self.client.connect()
                break
            except Exception as e:
                last = e
                self.on_status(f"Versuch {attempt} fehlgeschlagen ({e!r}), neuer Versuch …")
                await asyncio.sleep(2)
        else:
            raise RuntimeError(f"Keine Verbindung nach 3 Versuchen: {last!r}")
        await self.client.start_notify(INDOOR_BIKE_DATA, lambda _, d: self.on_data(parse_indoor_bike_data(d)))
        await self.client.start_notify(CONTROL_POINT, self._cp_response)
        await self._write(bytes([0x00]))  # Request Control
        await asyncio.sleep(0.3)
        await self._write(bytes([0x07]))  # Start/Resume
        self.on_status("Verbunden ✔")

    def _cp_response(self, _, data: bytes):
        if len(data) >= 3 and data[0] == 0x80:
            res = RESULTS.get(data[2], str(data[2]))
            if data[2] != 1:
                self.on_status(f"Rolle antwortet auf Befehl 0x{data[1]:02x}: {res}")

    async def _write(self, payload: bytes):
        if self.client and self.client.is_connected:
            await self.client.write_gatt_char(CONTROL_POINT, payload, response=True)

    async def disconnect(self):
        if self.client:
            await self.client.disconnect()

    async def set_power(self, watts: int):
        await self._write(struct.pack("<Bh", 0x05, int(watts)))

    async def set_resistance(self, level: float):
        # Einheit 0.1; viele Rollen interpretieren das als 0–100 %
        await self._write(struct.pack("<BB", 0x04, max(0, min(255, int(level * 10)))))

    async def set_grade(self, grade_percent: float):
        # Wind 0 m/s, Steigung in 0.01 %, Rollwiderstand 0.004, Luftwiderstand 0.51 kg/m
        await self._write(struct.pack("<BhhBB", 0x11, 0, int(grade_percent * 100), 40, 51))
