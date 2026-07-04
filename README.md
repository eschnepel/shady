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

## Grundidee (siehe ADR-001 für Details)

Kein manuell gepflegtes Horizontprofil. Shady lernt die Verschattung
**empirisch** aus der Differenz zwischen einem bestehenden PV-Forecast
(oder einer Sonnenstunden-Prognose) und dem realen historischen Ertrag:

1. Für jeden konfigurierten String wird eine **Baseline** (unverschatteter
   Forecast) automatisch erkannt – entweder aus einer PV-Forecast-
   Integration (z.B. Forecast.Solar, Solcast) oder, falls keine vorhanden
   ist, aus der Sonnenstunden-Prognose einer Wetterintegration.
2. Shady berechnet für jeden historischen 5-Minuten-Slot den **Sonnenstand**
   (Azimut + Elevation) anhand Standort und Zeit.
3. Eine **kernel-gewichtete Regression** über (Azimut, Elevation) lernt pro
   String **und pro 5-Minuten-Slot des Tages** (00:00, 00:05, …, 23:55 –
   dasselbe Raster wie die HA-Recorder-Statistics) einen eigenen
   Verschattungsfaktor – Sonnenstände, an denen der reale Ertrag
   systematisch niedriger ausfällt als die Baseline, verraten die Position
   der Obstruktion, ganz ohne dass sie geometrisch beschrieben werden muss.
   Ein globaler Smoothing-Radius (Default: 1 Nachbar-Slot) verhindert harte
   Sprünge zwischen benachbarten Slots.
4. Ein rollierendes 28-Tage-Fenster (konfigurierbar) hält das Modell nah an
   der aktuellen Situation (z.B. Laubfall bei einem Baum). Optional, pro
   String: Wechselrichter-Clipping-Samples werden aus dem Training
   ausgeschlossen, Temperatur-Derating wird vor der Regression herausgerechnet
   – beides deaktiviert Shady standardmäßig, bis explizit konfiguriert.
5. Ergebnis: ein angepasster Forecast-Sensor pro String (heute + morgen),
   plus ein Konfidenz-Attribut.

## Offene Fragen für das weitere Brainstorming

- Smoothing-Radius-Default (§3b) mit echten Daten validieren.
- Diagnose-/Debug-Darstellung des gelernten Verschattungsfeldes (z.B. als
  Polardiagramm Azimut/Elevation) für den Nutzer.

## Struktur

Siehe [`adr/000-coding-standards.md`](adr/000-coding-standards.md) für die
Modulgrenzen, [`adr/001-empirical-shading-model.md`](adr/001-empirical-shading-model.md)
für das Regressionsmodell, die Provider-Erkennung und den Config-Flow,
[`adr/002-coordinator-update-strategy.md`](adr/002-coordinator-update-strategy.md)
für Rekalibrierungs- und Forecast-Update-Trigger, und
[`adr/003-yield-corrections-clipping-derating.md`](adr/003-yield-corrections-clipping-derating.md)
für die optionalen Clipping-/Derating-Korrekturen.

Weitere ADRs (004 ff.) werden im Laufe des Brainstormings ergänzt.
