# Shady – Shading-Adjusted PV Forecast

**Status:** Brainstorming / Konzeptphase

Shady ist eine Home-Assistant-Integration, die einen bestehenden
PV-Ertragsforecast (z.B. von Forecast.Solar oder Solcast) anhand lokaler
Verschattung anpasst – etwa durch einen Baum, ein Nachbargebäude oder
sonstige Horizont-Obstruktionen, die generische Forecast-Dienste nicht
kennen.

Das Projekt übernimmt die Engineering-Konventionen von
[Effy](https://github.com/eschnepel/effy) (siehe [`adr/000-coding-standards.md`](adr/000-coding-standards.md))
als gemeinsame Basis für beide Integrationen.

## Grundidee (zu verfeinern)

1. Nutzer definiert ein **Horizontprofil** (z.B. Liste aus
   Azimut/Elevation-Punkten, die den Baum/die Obstruktion beschreiben).
2. Shady berechnet für jeden Forecast-Zeitpunkt den **Sonnenstand**
   (Azimut + Elevation) anhand Standort und Zeit.
3. Liegt die Sonne hinter der Obstruktion (Elevation < Horizontprofil an
   diesem Azimut), wird ein **Verschattungsfaktor** ermittelt und auf den
   rohen Forecast-Wert angewendet.
4. Ergebnis: ein neuer, angepasster Forecast-Sensor.

## Offene Fragen für das Brainstorming

- Wie bildet man einen Baum realistisch ab (harte Kante vs. diffuse
  Teilverschattung durch Blätterdach)?
- Wie pflegt der Nutzer das Horizontprofil (manuell, Kartentool, Foto-basiert)?
- Soll Shady saisonale Veränderungen (Laubfall) berücksichtigen?
- Welche Forecast-Quellen müssen unterstützt werden (Forecast.Solar,
  Solcast, Open-Meteo, eigene Sensoren)?
- Auflösung: 15-Minuten-Raster wie viele PV-Forecast-Integrationen, oder
  konfigurierbar?

## Struktur

Siehe [`adr/000-coding-standards.md`](adr/000-coding-standards.md) für die
vorgesehenen Modulgrenzen (`sun_geometry.py`, `horizon_profile.py`,
`shading.py`, `forecast_adjust.py`, `coordinator.py`, `sensor.py`,
`config_flow.py`).

Weitere ADRs (001 ff.) werden im Laufe des Brainstormings ergänzt.
