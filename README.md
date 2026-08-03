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

1. Zuerst wird global eine **Standard-Baseline** (unverschatteter
   Forecast) automatisch erkannt – entweder aus einer PV-Forecast-
   Integration (z.B. Forecast.Solar, Solcast) oder, falls keine vorhanden
   ist, aus der Sonnenstunden-Prognose einer Wetterintegration – bevor
   überhaupt ein String angelegt wird. Jeder String kann diese Baseline
   optional mit einer eigenen überschreiben (z.B. ein Solcast-Standort pro
   Dachausrichtung); eine solche Override gilt automatisch als
   "temperaturbewusst" (siehe Punkt 4), ohne eigene Nachfrage. Manche
   Provider liefern nur stündliche oder halbstündliche Werte – Shady
   verteilt diese auf die feineren 5-Minuten-Slots.
2. Pro String **und** pro 5-Minuten-Slot des Tages (00:00, 00:05, …,
   23:55 – dasselbe Raster wie die HA-Recorder-Statistics) wird ein
   eigenes Regressionsmodell trainiert: `PV ≈ f(FC)` – der Ist-Ertrag als
   Funktion des rohen Forecast-Werts, über die letzten 28 Tage desselben
   Slots. Default-Methode ist `wls2` (fängt die physikalisch plausible
   Krümmung durch Diffus-/Direktlicht-Anteil bei Verschattung ein, ohne
   das Extrapolations-Risiko von `wls3`); `linear` (im POC validiert),
   `kernel`, `wls3` stehen als Optionen zur Verfügung.
3. Ein globaler Smoothing-Radius (Default: 1 Nachbar-Slot) verhindert harte
   Sprünge zwischen benachbarten Slots – außer an einer Verschattungsgrenze:
   weicht der Median einer Nachbar-Serie um mehr als 25% (konfigurierbar)
   vom Median der Haupt-Slot-Serie ab, wird die gesamte Nachbar-Serie für
   diesen Slot vom Training ausgeschlossen, statt die Vorhersage in die
   falsche Richtung zu ziehen. Alternativ (Cutoff-Wert `-1%`) wird die
   Nachbar-Serie statt ausgeschlossen auf den Median des Haupt-Slots
   umskaliert und bleibt so nutzbar – Wetter- und Zeitabstand-Gewichtung
   greifen unverändert weiter.
4. Ein rollierendes 28-Tage-Fenster (konfigurierbar) hält das Modell nah an
   der aktuellen Situation (z.B. Laubfall bei einem Baum). Optional, pro
   String: Wechselrichter-/Konverter-Clipping-Samples werden aus dem
   Training ausgeschlossen *und* die korrigierte Ausgabe wird zusätzlich
   auf das Limit gedeckelt; Temperatur-Derating wird vor der Regression
   herausgerechnet und bei der Vorhersage wieder zurückgerechnet – beides
   deaktiviert Shady standardmäßig, bis explizit konfiguriert. Ein
   zusätzliches globales Flag (ein FC-Datenprovider pro Config-Entry) legt
   fest, ob dieser Provider (z.B. Solcast) den Temperaturkoeffizienten
   bereits selbst einrechnet – falls ja, wird Shadys eigene
   Temperatur-Korrektur für alle Strings übersprungen, um keine doppelte
   Verrechnung zu erzeugen. Ein String mit eigener Baseline-Override
   (Punkt 1) gilt dabei immer automatisch als temperaturbewusst, unabhängig
   vom globalen Flag.
5. Ergebnis: ein angepasster Forecast-Sensor pro String (heute + morgen),
   mit einer auf Tagessumme aggregierten Konfidenz (`FC`-gewichtet über
   alle Slots des Tages – die Konfidenz eines einzelnen Slots ist für sich
   genommen wenig aussagekräftig).
6. Optional (Diagnose-Switch, Default aus): ein Streudiagramm-Sensor pro
   String mit allen vier Regressionsmethoden im direkten Vergleich auf den
   eigenen historischen Daten, fertig aufbereitet für ApexCharts – inkl.
   Trefferquote pro Methode (als Zahl im `accuracy`-Attribut und direkt im
   Serien-Namen, z.B. "wls2 (96%)"). Standardmäßig wird immer der letzte
   vollständige Slot gezeigt; über den Service `shady.select_diagnostic_slot`
   (Zeitstempel-Parameter) lässt sich stattdessen gezielt ein bestimmter,
   bereits vergangener Slot auswählen, z.B. um ein konkretes Ereignis zu
   untersuchen. Die historischen Slot-Daten werden gecacht (Update nur bei
   Rekalibrierung bzw. Systemstart), damit weder die 5-Minuten-Aktualisierung
   noch die manuelle Slot-Auswahl wiederholte Recorder-Abfragen auslösen.
7. Zusätzlich, über alle Strings summiert: Ist-Ertrag jetzt, korrigierter
   Forecast jetzt, korrigierter Forecast für den ganzen Tag (288-Werte-
   Array), Rest-Tages-Prognose, sowie zwei Integralsensoren (Ist-Energie
   und korrigierte-Forecast-Energie, beide mit Reset um Mitternacht) für
   den direkten Ist-vs-Forecast-Vergleich in kWh über den Tagesverlauf.
8. Optional, **pro String**: die Rest-Tages-Prognose reagiert auf die in
   den letzten 2 Stunden beobachtete Ist-vs-Forecast-Abweichung (direkt
   aus der Recorder-Historie gelesen, ab mindestens 12 aktiven Slots in
   diesem Fenster), begrenzt durch einen konfigurierbaren Cut-off (Default
   0 = deaktiviert). Pro String, weil z.B. Schnee unter einem verschatteten
   String später abtaut als unter einem freien – ein aggregierter Wert
   würde beides vermischen. Nach jedem Provider-Forecast-Update wird zudem
   eine Stunde lang linear zwischen altem und neuem FC-Wert übergeblendet,
   damit Wettermodell-Updates nicht als Sprung im Dashboard auftauchen.

## Offene Fragen für das weitere Brainstorming

- Smoothing-Radius-Default (§3b) mit echten Daten validieren.

## Struktur

Siehe [`docs/architecture.mmd`](docs/architecture.mmd) für ein
Mermaid-Abhängigkeitsdiagramm der Verarbeitungsschritte (String- und
Aggregatebene kombiniert).

Siehe [`adr/000-coding-standards.md`](adr/000-coding-standards.md) für die
Modulgrenzen, [`adr/001-empirical-shading-model.md`](adr/001-empirical-shading-model.md)
für das Regressionsmodell, die Provider-Erkennung und den Config-Flow,
[`adr/002-coordinator-update-strategy.md`](adr/002-coordinator-update-strategy.md)
für Rekalibrierungs- und Forecast-Update-Trigger,
[`adr/003-yield-corrections-clipping-derating.md`](adr/003-yield-corrections-clipping-derating.md)
für die optionalen Clipping-/Derating-Korrekturen,
[`adr/004-diagnostics-switch-and-scatter-sensor.md`](adr/004-diagnostics-switch-and-scatter-sensor.md)
für den optionalen Diagnose-Switch und den ApexCharts-Streudiagramm-Sensor, und
[`adr/005-aggregate-sum-and-integral-sensors.md`](adr/005-aggregate-sum-and-integral-sensors.md)
für die Summen- und Integralsensoren über alle Strings, und
[`adr/006-intraday-deviation-correction.md`](adr/006-intraday-deviation-correction.md)
für die optionale Rest-Tages-Korrektur basierend auf der heutigen
Ist-vs-Forecast-Abweichung, und
[`adr/007-coordinator-cache-split.md`](adr/007-coordinator-cache-split.md)
für die Aufteilung von `coordinator.py` in Orchestrierung und ein
dediziertes, reines `cache.py`-Modul für allen zwischengespeicherten
Zustand.

Weitere ADRs (008 ff.) werden im Laufe des Brainstormings ergänzt.
