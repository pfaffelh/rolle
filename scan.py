import asyncio
from bleak import BleakScanner
FTMS="00001826-0000-1000-8000-00805f9b34fb"
async def main():
    devs = await BleakScanner.discover(timeout=15, return_adv=True)
    print(len(devs), "Geräte insgesamt")
    for d,a in sorted(devs.values(), key=lambda x:-x[1].rssi):
        tag = "  <-- FTMS (steuerbar)" if FTMS in [u.lower() for u in a.service_uuids] else ""
        print(d.address, repr(a.local_name), a.rssi, a.service_uuids, tag)
asyncio.run(main())
