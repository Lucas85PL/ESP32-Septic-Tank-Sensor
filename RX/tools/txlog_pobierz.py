#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Pobiera log nadajnika (TX) zapisany w odbiorniku (RX) i zapisuje go do pliku .txt.
Zawartosc logu NIE jest wypisywana w terminalu - na ekran trafia tylko krotkie podsumowanie.

Uzycie (zamknij najpierw PlatformIO Monitor - port COM moze byc otwarty tylko raz):
    python tools/txlog_pobierz.py                 # auto-wykrycie portu, plik logi_tx/txlog_RRRRMMDD_GGMMSS.txt
    python tools/txlog_pobierz.py --port COM5
    python tools/txlog_pobierz.py --last 10       # tylko 10 ostatnich cykli
    python tools/txlog_pobierz.py --out moj.txt
    python tools/txlog_pobierz.py --clear         # po poprawnym zapisie skasuj log w odbiorniku

Wymaga: pip install pyserial (jest w srodowisku PlatformIO: ~/.platformio/penv/Scripts/python.exe).
"""

import argparse
import datetime
import pathlib
import re
import sys
import time

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    # Brak pyserial w tym Pythonie - sprobuj Pythona z PlatformIO (ma pyserial)
    import os
    _pio = pathlib.Path.home() / ".platformio" / "penv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if _pio.exists() and os.path.abspath(sys.executable) != str(_pio):
        os.execv(str(_pio), [str(_pio)] + sys.argv)
    sys.exit("Brak biblioteki pyserial. Zainstaluj: pip install pyserial")

BEGIN = b"===TXLOG-BEGIN==="
END_RE = re.compile(rb"===TXLOG-END bytes=(\d+)===")
KNOWN_VIDS = {0x10C4, 0x1A86, 0x0403, 0x303A}  # CP210x, CH340, FTDI, Espressif


def pick_port(requested):
    if requested:
        return requested
    ports = [p for p in list_ports.comports() if p.vid in KNOWN_VIDS] or list(list_ports.comports())
    if len(ports) == 1:
        return ports[0].device
    if not ports:
        sys.exit("Nie znaleziono zadnego portu szeregowego. Podlacz odbiornik lub podaj --port.")
    print("Znaleziono kilka portow - podaj --port:")
    for p in ports:
        print(f"  {p.device}  {p.description}")
    sys.exit(2)


def open_port(port, baud):
    ser = serial.Serial()
    ser.port = port
    ser.baudrate = baud
    ser.timeout = 0.2
    ser.dtr = False   # bez resetu plytki przy otwarciu portu
    ser.rts = False
    if sys.platform != "win32":
        ser.exclusive = True   # Linux: nie dziel portu z otwartym Monitorem (dane by sie rozdzielily)
    try:
        ser.open()
    except serial.SerialException as e:
        sys.exit(f"Nie mozna otworzyc {port}: {e}\nZamknij PlatformIO Monitor (Ctrl+C w jego terminalu) / inny program uzywajacy portu.\n"
                 "Linux: brak dostepu? sudo usermod -aG dialout $USER (i ponowne logowanie).")
    return ser


def fetch_dump(ser, begin_timeout=6.0, idle_timeout=15.0):
    """Wysyla TXLOG DUMP i zwraca (payload_bytes, zadeklarowany_rozmiar)."""
    ser.reset_input_buffer()
    ser.write(b"\nTXLOG DUMP\n")

    buf = bytearray()
    t_start = time.time()
    t_last = time.time()
    resent = False
    begin_end = -1   # indeks bajtu tuz za linia BEGIN
    last_progress = 0

    while True:
        chunk = ser.read(4096)
        now = time.time()
        if chunk:
            buf += chunk
            t_last = now

        if begin_end < 0:
            i = buf.find(BEGIN)
            if i >= 0:
                nl = buf.find(b"\n", i)
                if nl >= 0:
                    begin_end = nl + 1
            elif now - t_start > begin_timeout / 2 and not resent:
                ser.write(b"\nTXLOG DUMP\n")   # np. odbiornik byl wlasnie w trakcie startu
                resent = True
            elif now - t_start > begin_timeout:
                sys.exit("Brak odpowiedzi odbiornika (nie wykryto ===TXLOG-BEGIN===). "
                         "Sprawdz port i czy w odbiorniku jest wgrane oprogramowanie z obsluga TXLOG.")
        if begin_end >= 0:
            m = END_RE.search(buf, begin_end)
            if m:
                payload = bytes(buf[begin_end:m.start()])
                return payload, int(m.group(1))
            if len(buf) - last_progress > 20000:
                last_progress = len(buf)
                print(f"\r  odebrano {len(buf) - begin_end} B ...", end="", flush=True)
            if now - t_last > idle_timeout:
                sys.exit("\nPrzerwano: odbiornik przestal wysylac dane przed znacznikiem konca.")


def keep_last_records(text, n):
    parts = re.split(r"(?m)^(?=##### RX )", text)
    header = parts[0] if parts and not parts[0].startswith("##### RX ") else ""
    records = [p for p in parts if p.startswith("##### RX ")]
    return header + "".join(records[-n:]), len(records)


def main():
    ap = argparse.ArgumentParser(description="Zgrywa log TX z odbiornika do pliku .txt")
    ap.add_argument("--port", help="np. COM5 (domyslnie auto)")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--out", help="plik wyjsciowy (domyslnie logi_tx/txlog_<data>.txt)")
    ap.add_argument("--last", type=int, metavar="N", help="zapisz tylko N ostatnich cykli")
    ap.add_argument("--clear", action="store_true", help="po zapisie skasuj log w odbiorniku")
    args = ap.parse_args()

    port = pick_port(args.port)
    print(f"Port: {port} - pobieram log TX z odbiornika...")
    ser = open_port(port, args.baud)
    try:
        payload, declared = fetch_dump(ser)
        print()

        if len(payload) != declared:
            print(f"UWAGA: odebrano {len(payload)} B, odbiornik zadeklarowal {declared} B "
                  "(mozliwe zaklocenia) - plik zapisany mimo to.")

        text = payload.decode("utf-8", errors="replace").replace("\r\n", "\n")
        total_records = len(re.findall(r"(?m)^##### RX ", text))
        if args.last:
            text, total_records = keep_last_records(text, args.last)

        now = datetime.datetime.now()
        out = pathlib.Path(args.out) if args.out else \
            pathlib.Path(__file__).resolve().parent.parent / "logi_tx" / f"txlog_{now:%Y%m%d_%H%M%S}.txt"
        out.parent.mkdir(parents=True, exist_ok=True)
        header = f"# Log TX pobrany z odbiornika {now:%Y-%m-%d %H:%M:%S} (port {port})\n"
        out.write_text(header + text, encoding="utf-8")

        ids = [int(x) for x in re.findall(r"(?m)^##### RX epoch=[0-9A-F]+ id=(\d+)", text)]
        shown = len(re.findall(r"(?m)^##### RX ", text))
        rng = f", cykle {min(ids)}-{max(ids)}" if ids else ""
        print(f"Zapisano {shown} rekordow ({len(text)} znakow{rng}) -> {out}")
        if shown == 0:
            print("Log w odbiorniku jest pusty (nadajnik jeszcze nic nie przeslal).")

        if args.clear and shown > 0 and len(payload) == declared:
            ser.reset_input_buffer()
            ser.write(b"\nTXLOG CLEAR\n")
            time.sleep(0.5)
            print("Wyslano TXLOG CLEAR - log w odbiorniku skasowany.")
    finally:
        ser.close()


if __name__ == "__main__":
    main()
