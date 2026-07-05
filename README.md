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

Kein manuell gepflegtes Horizontprofil, keine Sonnenstands-Berechnung.
**Validiert durch einen früheren Proof-of-Concept:** Shady lernt die
Verschattung rein empirisch aus der Beziehung zwischen dem rohen
PV-Forecast-Wert und dem realen historischen Ertrag – pro Slot, direkt
über den Forecast-Wert, nicht über Zeit oder Sonnenstand:

1. Für jeden konfigurierten String wird eine **Baseline** (unverschatteter
   Forecast) automatisch erkannt – entweder aus einer PV-Forecast-
   Integration (z.B. Forecast.Solar, Solcast) oder, falls keine vorhanden
   ist, aus der Sonnenstunden-Prognose einer Wetterintegration. Manche
   Provider liefern nur stündliche oder halbstündliche Werte – Shady
   verteilt diese auf die feineren 5-Minuten-Slots.
2. Pro String **und** pro 5-Minuten-Slot des Tages (00:00, 00:05, …,
   23:55 – dasselbe Raster wie die HA-Recorder-Statistics) wird ein
   eigenes Regressionsmodell trainiert: `PV ≈ f(FC)` – der Ist-Ertrag als
   Funktion des rohen Forecast-Werts, über die letzten 28 Tage desselben
   Slots. Default-Methode ist `linear` (so im POC validiert); `kernel`,
   `wls2`, `wls3` stehen als Optionen zur Verfügung, sind aber – wie
   Beispielrechnungen zeigen – bei Extrapolation über den historischen
   Wertebereich hinaus (der Normalfall bei einer Vorhersage) tendenziell
   instabiler.
3. Ein globaler Smoothing-Radius (Default: 1 Nachbar-Slot) verhindert harte
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
- Diagnose-/Debug-Darstellung der gelernten Slot-Modelle (z.B. als
  FC-vs-PV-Streudiagramm mit Regressionskurve je Slot) für den Nutzer.

## Struktur

Siehe [`adr/000-coding-standards.md`](adr/000-coding-standards.md) für die
Modulgrenzen, [`adr/001-empirical-shading-model.md`](adr/001-empirical-shading-model.md)
für das Regressionsmodell, die Provider-Erkennung und den Config-Flow,
[`adr/002-coordinator-update-strategy.md`](adr/002-coordinator-update-strategy.md)
für Rekalibrierungs- und Forecast-Update-Trigger, und
[`adr/003-yield-corrections-clipping-derating.md`](adr/003-yield-corrections-clipping-derating.md)
für die optionalen Clipping-/Derating-Korrekturen.

Weitere ADRs (004 ff.) werden im Laufe des Brainstormings ergänzt.
