"""SSD1306 driver and four views for the 0.96-inch 128x64 OLED.

Das Bild wird im Speicher gezeichnet und nur dort übertragen, wo es sich geändert
hat. Der I2C-Bus läuft in Software und braucht für ein ganzes Bild etwa 0,2 s.
Auf dem Pi ist Pillow nicht installiert, deshalb steht die Schrift hier im Code.
"""

BREITE = 128
HOEHE = 64
OLED_ADRESSE = 0x3C

# Hochkant-Pixelspalten je Zeichen (5x7), von Leerzeichen bis "z".
_SCHRIFT = bytes.fromhex(
    "0000000000 00005F0000 0007000700 147F147F14 242A7F2A12 2313086462 3649552250 0005030000"
    "001C224100 0041221C00 14083E0814 08083E0808 0050300000 0808080808 0060600000 2010080402"
    "3E5149453E 00427F4000 4261514946 2141454B31 1814127F10 2745454539 3C4A494930 0171090503"
    "3649494936 064949291E 0036360000 0056360000 0814224100 1414141414 0041221408 0201510906"
    "324979413E 7E1111117E 7F49494936 3E41414122 7F4141221C 7F49494941 7F09090901 3E4149497A"
    "7F0808087F 00417F4100 2040413F01 7F08142241 7F40404040 7F020C027F 7F0408107F 3E4141413E"
    "7F09090906 3E4151215E 7F09192946 4649494931 01017F0101 3F4040403F 1F2040201F 3F4038403F"
    "6314081463 0708700807 6151494543 007F414100 0204081020 0041417F00 0402010204 4040404040"
    "0001020400 2054545478 7F48444438 3844444420 384444487F 3854545418 087E090102 0C5252523E"
    "7F08040478 00447D4000 2040443D00 7F10284400 00417F4000 7C04180478 7C08040478 3844444438"
    "7C14141408 081414187C 7C08040408 4854545420 043F444020 3C4040207C 1C2040201C 3C4030403C"
    "4428102844 0C5050503C 4464544C44"
)
_SONDERZEICHEN = {
    "°": bytes.fromhex("0006090906"),
    "ä": bytes.fromhex("2055545578"),
    "ö": bytes.fromhex("3845444538"),
    "ü": bytes.fromhex("3C4140217C"),
    "Ä": bytes.fromhex("7C1312137C"),
    "Ö": bytes.fromhex("3C4342433C"),
    "Ü": bytes.fromhex("3C4140413C"),
}

_START_BEFEHLE = [
    0xAE,              # aus
    0xD5, 0x80,        # Takt
    0xA8, 0x3F,        # 64 Zeilen
    0xD3, 0x00,        # kein Versatz
    0x40,              # Startzeile 0
    0x8D, 0x14,        # Ladungspumpe an
    0x20, 0x00,        # horizontale Adressierung
    0xA0, 0xC0,        # Bild um 180 Grad gedreht, so steht es im Einbau richtig
    0xDA, 0x12,        # COM-Belegung für 64 Zeilen
    0x81, 0xCF,        # Kontrast
    0xD9, 0xF1,        # Vorladung
    0xDB, 0x40,        # VCOM
    0xA4, 0xA6,        # Speicher anzeigen, nicht invertiert
    0xAF,              # an
]


def _muster(zeichen):
    if zeichen in _SONDERZEICHEN:
        return _SONDERZEICHEN[zeichen]
    nummer = ord(zeichen) - 0x20
    if not 0 <= nummer < len(_SCHRIFT) // 5:
        nummer = ord("?") - 0x20
    return _SCHRIFT[nummer * 5:nummer * 5 + 5]


class Bild:
    def __init__(self):
        self.daten = bytearray(BREITE * HOEHE // 8)

    def rechteck(self, x, y, breite, hoehe):
        for px in range(x, x + breite):
            for py in range(y, y + hoehe):
                if 0 <= px < BREITE and 0 <= py < HOEHE:
                    self.daten[px + (py // 8) * BREITE] |= 1 << (py % 8)

    def text(self, x, y, text, groesse=1):
        for zeichen in text:
            for spalte, muster in enumerate(_muster(zeichen)):
                for zeile in range(7):
                    if muster >> zeile & 1:
                        self.rechteck(x + spalte * groesse, y + zeile * groesse, groesse, groesse)
            x += 6 * groesse

    def text_rechts(self, x_ende, y, text, groesse=1):
        self.text(x_ende - (len(text) * 6 - 1) * groesse + 1, y, text, groesse)


class Oled:
    def __init__(self, bus):
        self.bus = bus
        # Der zuletzt übertragene Inhalt; None erzwingt Neustart und ganzes Bild.
        self.alt = None

    def _befehle(self, befehle):
        self.bus.write(OLED_ADRESSE, bytes([0x00, *befehle]))

    def zeigen(self, daten):
        try:
            if self.alt is None:
                self._befehle(_START_BEFEHLE)
            for seite in range(HOEHE // 8):
                beginn = seite * BREITE
                neu = daten[beginn:beginn + BREITE]
                alt = self.alt[beginn:beginn + BREITE] if self.alt else None
                spalten = [x for x in range(BREITE) if alt is None or neu[x] != alt[x]]
                if spalten:
                    von, bis = spalten[0], spalten[-1]
                    self._befehle([0x21, von, bis, 0x22, seite, seite])
                    self.bus.write(OLED_ADRESSE, bytes([0x40, *neu[von:bis + 1]]))
            self.alt = bytes(daten)
        except Exception:
            # Nach einer Störung (z. B. Wackelkontakt) beim nächsten Mal neu starten.
            self.alt = None
            raise

    def ausschalten(self):
        self._befehle([0xAE])
        self.alt = None


def _value(readings, side, sensor, field, pattern):
    value = readings.get((side, sensor, field))
    if value is None and sensor == "sht45":
        value = readings.get((side, "scd40", field))
    return "--" if value is None else pattern.format(value)


def render(view, readings, controls, enabled):
    from display import VIEWS

    title, device = VIEWS[view]
    image = Bild()
    image.text(0, 0, title)
    image.text_rechts(127, 0, f"{view + 1}/{len(VIEWS)}")
    image.rechteck(0, 9, 128, 1)
    if device is None:
        image.text(37, 12, "Links")
        image.text_rechts(127, 12, "Rechts")
        rows = (
            ("T", "sht45", "temperature_c", "{:.1f}°C"),
            ("rF", "sht45", "humidity_pct", "{:.0f}%"),
            ("CO2", "scd40", "co2_ppm", "{:.0f}"),
            ("Lux", "bh1750", "illuminance_lux", "{:.0f}"),
        )
        for index, (label, sensor, field, pattern) in enumerate(rows):
            y = 22 + index * 10
            image.text(0, y, label)
            image.text(37, y, _value(readings, "left", sensor, field, pattern))
            image.text_rechts(127, y, _value(readings, "right", sensor, field, pattern))
    elif not enabled:
        image.text(12, 25, "Steuerung aus")
        image.text(0, 55, "2x: naechste Ansicht")
    else:
        value = controls[device]
        image.text(32, 16, f"{value}%", 2)
        image.rechteck(8, 38, 112, 1)
        image.rechteck(8, 45, 112, 1)
        image.rechteck(8, 38, 1, 8)
        image.rechteck(119, 38, 1, 8)
        image.rechteck(10, 40, round(value * 108 / 100), 4)
        image.text(0, 48, "Halten: 0%")
        image.text(0, 56, "1x +5  2x weiter")
    return image.daten

