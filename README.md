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
   String einen Verschattungsfaktor – Sonnenstände, an denen der reale
   Ertrag systematisch niedriger ausfällt als die Baseline, verraten die
   Position der Obstruktion, ganz ohne dass sie geometrisch beschrieben
   werden muss.
4. Ein rollierendes 28-Tage-Fenster (konfigurierbar) hält das Modell nah an
   der aktuellen Situation (z.B. Laubfall bei einem Baum).
5. Ergebnis: ein angepasster Forecast-Sensor pro String, plus ein
   Konfidenz-Attribut.

## Offene Fragen für das weitere Brainstorming

- Genaue Kernel-Bandbreite / Standard-Trainingsfenster-Feintuning mit
  echten Daten.
- Coordinator-Rekalibrierungs-Zyklus (wie oft neu fitten?).
- Umgang mit Wechselrichter-Clipping/Temperatur-Derating, das die Baseline
  ebenfalls (nicht-verschattungsbedingt) drückt und die Regression stören
  könnte.
- Diagnose-/Debug-Darstellung des gelernten Verschattungsfeldes (z.B. als
  Polardiagramm Azimut/Elevation) für den Nutzer.

## Struktur

Siehe [`adr/000-coding-standards.md`](adr/000-coding-standards.md) für die
Modulgrenzen und [`adr/001-empirical-shading-model.md`](adr/001-empirical-shading-model.md)
für das Regressionsmodell, die Provider-Erkennung und den Config-Flow.

Weitere ADRs (002 ff.) werden im Laufe des Brainstormings ergänzt.
