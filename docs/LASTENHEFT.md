# AleXiona Demonstrator — Technisches Lastenheft v1

**Status**: Entwurf
**Version**: 1.0
**Ziel**: Demonstrator-Architektur für klinischen Evidenz- und Strukturierungsassistenten

---

## 0. Systemziel und Positionierung

AleXiona ist **kein Diagnosesystem**.

AleXiona ist ein **klinischer Strukturierungs- und Evidenzassistent**:

- Patientennahe, klinische und externe Wissensquellen als zeitlich markierte **Claims** strukturieren
- Claims gegeneinander **abwägen** (Evidenz, Widerspruch, Herkunft, Zeit, Risiko)
- Befunde, Hypothesen und offene Fragen **transparent aufbereiten**
- Klinische Entscheidungsunterstützung — nicht autonome Entscheidung

### Architekturprinzip

```
User / Patientendaten / Arztinput
        │
        ▼
   [Intake Adapter]        ← Modul A
        │
        ▼
   [Claim Engine]          ← Modul B
        │
        ▼
   [Evidence Engine]       ← Modul C
        │
        ▼
   [Clinical Guardrails]   ← Modul D
        │
        ▼
   [Render Engine]         ← Modul E
        │
        ▼
   Ausgabe (Arzt / Patient / API)

   [Audit Layer]           ← Modul F  (querschnittlich)
```

Das LLM ist ein **Teilmotor** (Sprache, Strukturierung), nicht die Entscheidungsschicht.

---

## 1. Eingabequellen

Vier epistemisch getrennte Quellen. Sie dürfen **nicht im Prompt-Brei verschwinden** — jede Quelle braucht eigene Herkunftsmarkierung.

| Quelle | Typ | SourceType | EvidenceTier |
|--------|-----|-----------|--------------|
| Patientengespräch (Anamnese, Symptome) | Freitext | `patient_report` | `patient_generated` |
| Wearable / Fitness-Tracker | Zeitreihe | `wearable` | `patient_generated` |
| Home Device (RR, SpO2, Thermometer) | numerisch | `home_device` | `patient_generated` |
| Angehörigenangaben | Freitext | `caregiver_report` | `patient_generated` |
| Labor | numerisch / kodiert | `lab_system` | `lab_confirmed` |
| Vitals / Befunde (klinisch dokumentiert) | Freitext / strukturiert | `clinician` | `clinician_observed` |
| Arztbriefe / Diagnosen / Medikation | Freitext | `imported_document` | `clinician_observed` |
| Bildgebung (Modell-Output) | strukturiert | `imaging_model` | `instrument_measured` |
| Leitlinien / SOPs / Fachinformationen | Regeltext | `guideline` | `guideline_structured` |

### v1 / v2 Abgrenzung

| Quelle | v1 | v2 |
|--------|----|----|
| Patientengespräch (Freitext) | ✅ | — |
| Wearable / Home Device | ✅ Stub mit Beispieldaten | ✅ Live-Import |
| Labor | ✅ manuelle Eingabe | ✅ HL7/FHIR-Adapter |
| Arztbriefe | ✅ Datei-Upload (PDF/TXT) | ✅ IHE-Adapter |
| Leitlinien | ✅ hardcodierte Regelsets | ✅ Document Store |
| Bildgebung | ❌ | ✅ DICOM + Modell-Inference |

---

## 2. Datenobjekte

### 2.1 Claim (Kernobjekt)

```python
class Claim:
    id:                     str           # UUID
    text:                   str           # lesbare Aussage
    claim_type:             ClaimType     # symptom | finding | lab | imaging |
                                          # hypothesis | diagnosis | therapy |
                                          # risk_factor | guideline
    source_type:            SourceType    # siehe Tabelle oben
    evidence_tier:          EvidenceTier  # patient_generated → guideline_structured
    evidence_support_score: float         # 0.0–1.0 (Evidenzstärke, NICHT Wahrscheinlichkeit)
    status:                 ClaimStatus   # observed | inferred | confirmed | refuted |
                                          # contested | resolved | superseded | withdrawn
    event_time:             datetime      # WANN das medizinische Ereignis eintrat
    assertion_time:         datetime      # WANN der Claim ins System eingetragen wurde
    valid_from:             datetime      # Gültigkeitsstart
    valid_until:            datetime      # Gültigkeitsende / Ablauf
    entities:               list[str]     # medizinische Konzepte
    relations:              list[Relation]
    normalized_token:       str           # kanonisches Lab-Token (z.B. "crp")
    uncertainty_flag:       bool          # ausdrückliche Unsicherheitsmarkierung
    assumptions:            list[str]     # explizite Annahmen hinter dem Claim
    supersedes_claim_id:    str           # Vorgänger-Claim bei Aktualisierung
    patient_data_ref:       str           # Rückverweis auf PatientObservation / PGM
    source_ref:             str           # Dokumentname / Gerätename / Test
    derived_from:           list[str]     # explizite epistemische Ableitung
    related_to:             list[str]     # semantische Nähe
    trend:                  ClaimTrend    # improving | worsening | stable | unknown
    time_offset:            str           # Legacy: "t+6h"
```

### 2.2 PatientObservation

```python
class PatientObservation:
    id:               str
    raw_text:         str
    source_type:      str        # patient_report | caregiver_report
    event_time:       datetime
    assertion_time:   datetime
    body_location:    str        # "Brust", "linker Arm"
    onset_hint:       str        # "seit 3 Tagen", "gestern Morgen"
    severity_hint:    str        # "mild", "stark", "8/10"
    negation_hint:    bool       # "kein Schmerz", "kein Fieber"
    uncertainty_hint: bool       # "ich glaube", "vielleicht"
    candidate_ids:    list[str]  # erzeugte ClaimCandidates
```

### 2.3 PatientGeneratedMeasurement

```python
class PatientGeneratedMeasurement:
    id:                   str
    device_type:          str        # wearable | home_device
    device_name:          str        # "Apple Watch Series 9", "Omron BP cuff"
    token:                str        # "heart_rate", "spo2", "systolic_bp"
    value:                float
    unit:                 str
    qualitative:          str        # high | low | normal
    event_time:           datetime
    assertion_time:       datetime
    measurement_quality:  str        # good | medium | poor | unknown
    session_duration_s:   int        # für Wearables
    candidate_id:         str
```

### 2.4 TrendSignal

```python
class TrendSignal:
    id:            str
    token:         str
    direction:     str        # rising | falling | stable | volatile
    magnitude_pct: float      # prozentuale Veränderung im Zeitfenster
    window_hours:  float
    start_value:   float
    end_value:     float
    n_points:      int
    clinical_flag: str        # "tachycardia_trend", "hypoxia_trend", ...
    candidate_id:  str
```

### 2.5 ReasoningResult

```python
class ReasoningResult:
    leading_hypothesis:     str
    supporting_evidence:    list[str]
    conflicting_evidence:   list[str]
    evidence_support_score: float
    alternatives:           list[Alternative]
    missing_evidence:       list[MissingEvidence]
    focus_points:           list[str]
```

### 2.6 CompositeScore

```python
class CompositeScore:
    name:             str           # "qSOFA", "Wells-PE", "GRACE-ACS"
    score:            int
    interpretation:   str           # low | intermediate | high
    criteria_met:     list[str]
    criteria_missing: list[str]
    as_claim:         dict          # direkt als Claim-Dict verwendbar
```

### 2.7 Conflict

```python
class Conflict:
    id:                 str
    type:               ConflictType   # competing_hypothesis | negation | evidence_mismatch |
                                       # timeline_gap | stale_lab_evidence | time_paradox | ...
    severity:           ConflictSeverity  # error | warning | info
    message:            str
    affected_claim_ids: list[str]
```

---

## 3. API-Flows

### 3.1 POST /intake/conversation

**Eingang**: Freitextgespräch (Patient oder Arzt)
**Verarbeitung**: `extract_claims()` → `normalize_claims()` → `attach_metadata()`
**Ausgang**: `ClaimExtractionResult`

```
Request:
  { "text": "...", "session_id": "...", "source_type": "patient_report" }

Response:
  {
    "claims": [ Claim, ... ],
    "session_id": "..."
  }
```

### 3.2 POST /intake/measurements

**Eingang**: Liste von `PatientGeneratedMeasurement`
**Verarbeitung**: `ingest_measurement()` → `extract_trend_signal()` → ClaimCandidates → Claims
**Ausgang**: erzeugte Claims + optionale TrendSignals

```
Request:
  {
    "measurements": [ PatientGeneratedMeasurement, ... ],
    "session_id": "..."
  }

Response:
  {
    "claims": [ Claim, ... ],
    "trend_signals": [ TrendSignal, ... ]
  }
```

### 3.3 POST /intake/clinical

**Eingang**: Labor, Medikation, Arztbrief, Vitals
**Verarbeitung**: `extract_claims()` mit `source_type=clinician|lab_system|imported_document`
**Ausgang**: `ClaimExtractionResult`

### 3.4 POST /chat

**Eingang**: Nutzerfrage + Session-History
**Verarbeitung**: `build_reasoning_context()` → LLM + Evidence Engine
**Ausgang**: strukturierte Antwort + Claims + ReasoningResult + Conflicts

```
Request:
  { "message": "...", "session_id": "...", "history": [ ChatMessage, ... ] }

Response:
  {
    "reply":      "...",
    "claims":     [ Claim, ... ],
    "reasoning":  ReasoningResult,
    "conflicts":  [ Conflict, ... ],
    "composite_scores": [ CompositeScore, ... ]
  }
```

### 3.5 GET /graph/{session_id}

**Eingang**: Session-ID
**Ausgang**: Knoten + Kanten des Claim-Graphen für UI-Rendering

```
Response:
  {
    "nodes": [ { "id": "...", "label": "...", "claim_type": "...",
                 "evidence_tier": "...", "status": "...",
                 "evidence_support_score": 0.72 } ],
    "edges": [ { "from": "...", "to": "...", "type": "..." } ]
  }
```

### 3.6 POST /graph/{session_id}/node/{claim_id}

**Eingang**: `NodeUpdate` (Arzt-Patch: Status, Score, Anmerkungen)
**Ausgang**: aktualisierter Claim

### 3.7 POST /reasoning/counterfactual

**Eingang**: `excluded_claim_id` + Session-ID
**Ausgang**: `CounterfactualResult` inkl. `guideline_shift`

### 3.8 POST /reasoning/hypothesis-counterfactual

**Eingang**: `hypothesis_label` + Session-ID
**Ausgang**: `HypothesisCounterfactualResult`

### 3.9 GET /conflicts/{session_id}

**Eingang**: Session-ID
**Ausgang**: alle aktiven `Conflict`-Objekte

---

## 4. Scoring-Architektur (Evidence Engine, Modul C)

### Scorer-Übersicht

| Scorer | Beschreibung | Quelle |
|--------|-------------|--------|
| **Evidenz-Score** | Wie stark stützen vorhandene Claims die Hypothese? | `score_hypothesis()` |
| **Widerspruchs-Score** | Welche Claims sprechen aktiv dagegen? | `detect_conflicts()` |
| **Quellen-Score** | Herkunftsgewichtung (patient_report=0.4 … guideline=1.5) | `_SOURCE_WEIGHTS` |
| **Zeit-Score** | Exponentieller Verfall nach Halbwertszeit je Claim-Typ | `_temporal_weight()` |
| **Leitlinien-Score** | Regelbasierte Prüfung gegen validierte Guideline-Regelsets | `evaluate_guideline()` |
| **Composite-Score** | qSOFA / Wells-PE / GRACE-ACS | `compute_relevant_scores()` |
| **Red-Flag-Score** | Kritische Konstellationen, nicht dem LLM überlassen | `compute_risk_flags()` (v1 Stub) |
| **Vollständigkeits-Score** | Fehlen entscheidende Informationen? | `prioritize_missing()` |

### Quellen-Gewichtung

```
guideline_structured  →  1.5×
lab_confirmed         →  1.2×
clinician_observed    →  1.0×  (Baseline)
instrument_measured   →  0.9×
wearable              →  0.7×
home_device           →  0.6×
caregiver_report      →  0.5×
patient_report        →  0.4×
```

### Temporaler Verfall (Halbwertszeiten)

```
lab           →  12 h
imaging       →  96 h
finding       →  48 h
symptom       →  24 h
hypothesis    →  72 h
therapy       →  168 h
default       →  48 h
```

### Epistemic Safeguards

1. `patient_generated`-Claims dürfen **nicht** Status `confirmed` tragen
2. `patient_generated`-Claims, die eine `diagnosis`-Hypothese stützen: 0.5× Gewichtung
3. `confirmed`-Boost (1.5×) nur für `clinician_observed` und höher
4. `refuted`-Claims werden **hart aus dem Ranking ausgeschlossen**

---

## 5. Conflict Engine (Modul D)

### Konflikttypen

| Typ | Beschreibung | Severity |
|-----|-------------|----------|
| `competing_hypothesis` | Zwei Hypothesen > 0.7 ESS gleichzeitig aktiv | warning |
| `negation` | Claim und sein negiertes Gegenstück beide aktiv | error |
| `evidence_mismatch` | Therapie ohne passende Indikation | warning |
| `timeline_gap` | Zeitlicher Widerspruch zwischen Claims | warning |
| `stale_hypothesis` | Hypothese ohne neue stützende Evidenz seit > 24h | info |
| `contradictory_values` | Gleicher Lab-Token mit widersprüchlichen Werten | error |
| `temporal_inconsistency` | `event_time` nach `valid_until` | warning |
| `stale_lab_evidence` | Lab-Ergebnis > 48h alt, stützt aber aktive Hypothese | warning |
| `time_paradox` | `assertion_time` liegt vor `event_time` | error |

### Red-Flag-Regeln (v1 Minimal-Set)

Nicht dem LLM überlassen. Regelbasiert, hart kodiert:

```python
RED_FLAGS = [
    # (Token, Operator, Schwellenwert, Flag-Label)
    ("spo2",        "<",  90.0,  "critical_hypoxia"),
    ("systolic_bp", "<",  80.0,  "hemodynamic_shock"),
    ("heart_rate",  ">", 130.0,  "severe_tachycardia"),
    ("heart_rate",  "<",  40.0,  "severe_bradycardia"),
    ("temperature", ">",  39.5,  "high_fever"),
    ("gcs",         "<",   9.0,  "impaired_consciousness"),
    ("troponin",    ">",   0.1,  "troponin_positive"),
    ("lactate",     ">",   4.0,  "severe_lactic_acidosis"),
]
```

Ein Red Flag erzeugt immer einen `Conflict` mit `severity=error` und erscheint als separater Block im Render.

---

## 6. UI-Ansichten (Modul E)

### 6.1 Claim-Ansicht (Kliniker)

Tabelle aller aktiven Claims mit:

| Spalte | Inhalt |
|--------|--------|
| Text | Claim-Aussage |
| Typ | Claim-Typ (Farb-Badge) |
| Quelle | SourceType + source_ref |
| Tier | EvidenceTier (patient / klinisch / Labor…) |
| Score | ESS als Balken (0–100%) |
| Zeit | event_time relativ (z.B. „vor 3 Tagen") |
| Status | observed / inferred / confirmed / refuted … |
| Aktionen | Bestätigen · Widerlegen · Kommentieren |

### 6.2 Evidenz-Panel (Kliniker)

Für jede Hypothese:

```
Hypothese: Infektexazerbation bei COPD
Score: 0.74 ████████░░

PRO:
  • CRP 28 mg/L erhöht — Labor (vor 2h)
  • Belastungsdyspnoe seit 3 Tagen — Patient
  • bekannte COPD — Arztbrief

CONTRA:
  • Temperatur 37.1°C — kein Fieber (Wearable)

LÜCKEN:
  • Prokalzitonin fehlt (unterscheidet viral vs. bakteriell)
  • Sauerstoffsättigung aktuell nicht dokumentiert
```

### 6.3 Red-Flag-Panel

Separater Block, immer sichtbar wenn aktiv:

```
⚠ WARNHINWEISE

[KRITISCH] SpO2 88% — Hypoxie-Trend seit 3h (Wearable)
[KRITISCH] Troponin ausstehend — bei Dyspnoe + Tachykardie erforderlich
```

### 6.4 Quellen-Trace-Panel

Für jeden Claim aufklappbar:

```
CRP 28 mg/L — HOCH
  Quelle:     lab_system / Synlab-Befund 2024-03-21
  EvidenceTier: lab_confirmed
  Erhoben:    2024-03-21 08:15 UTC
  Eingetragen: 2024-03-21 09:02 UTC
  Gültig bis: 2024-03-22 08:15 UTC (12h Halbwertszeit)
  Status:     observed
```

### 6.5 Patientenansicht (vereinfacht)

Keine Scores, keine Hypothesen — nur:

- Zusammenfassung in Alltagssprache
- Was wurde erfasst
- Welche Fragen noch offen sind
- Nächste empfohlene Schritte

---

## 7. Audit Layer (Modul F)

Jede Transformation wird protokolliert:

```python
class AuditEntry:
    timestamp:       datetime
    session_id:      str
    event_type:      str   # claim_extracted | claim_updated | conflict_detected |
                           # hypothesis_scored | red_flag_triggered | render_generated
    actor:           str   # "llm" | "rule_engine" | "clinician:{user_id}"
    input_ref:       str   # ID des Input-Objekts
    output_ref:      str   # ID des Output-Objekts
    details:         dict  # event-spezifische Metadaten
```

### v1: Minimalimplementierung

- Strukturiertes Logging via Python `logging` + JSON-Formatter
- Alle Eingaben, alle erzeugten Claims, alle Conflicts, alle Render-Outputs

### v2: Persistenz

- Dedizierte Audit-Tabelle (Postgres oder MongoDB)
- Replay-Funktion: Claim-Graph zu beliebigem Zeitpunkt rekonstruieren
- DSGVO-Konformität: Export pro Session möglich

---

## 8. Demo-Use-Case: Atemnot / Erschöpfung / auffällige Pulsdaten

**Schrittweise Abarbeitung im Demonstrator:**

### Schritt 1 — Intake

```
Patientengespräch:
  "Ich bin seit 3 Tagen sehr kurzatmig beim Treppensteigen.
   Ich bin müde und mein Fitnesstracker zeigt seit einer Woche
   erhöhten Ruhepuls."

Trackerdaten (importiert):
  Ruhepuls: [72, 75, 78, 82, 85, 88, 91] — 7 Tage

Vorbefunde:
  COPD (bekannt)
  Bisoprolol 5mg täglich
  CRP 28 mg/L (Labor, vor 2h)
```

### Schritt 2 — Claim-Extraktion

```
Claims erzeugt:
  [patient_report]  Belastungsdyspnoe seit 3 Tagen — ESS 0.85
  [patient_report]  Erschöpfung / Müdigkeit — ESS 0.75
  [wearable]        Ruhepuls erhöht seit 7 Tagen (+26%) — ESS 0.65
  [wearable]        Trend: heart_rate rising 26% über 7d [tachycardia_trend]
  [imported_doc]    Bekannte COPD — ESS 0.95
  [imported_doc]    Bisoprolol 5mg täglich — ESS 0.95
  [lab_system]      CRP 28 mg/L erhöht — ESS 0.90
```

### Schritt 3 — Hypothesenraum

```
H1: Infektexazerbation bei COPD          → Score 0.74
H2: Kardiale Dekompensation              → Score 0.51  [Red Flag: Troponin fehlt]
H3: Medikamentennebenwirkung (Betablocker)→ Score 0.28
H4: Datenartefakt (Wearable-Messfehler)  → Score 0.12
```

### Schritt 4 — Evidenzbewertung

```
H1 PRO: CRP, Dyspnoe, COPD-Vorerkrankung
H1 CONTRA: kein Fieber dokumentiert, Prokalzitonin fehlt

H2 PRO: Tachykardie-Trend, Dyspnoe, Erschöpfung
H2 CONTRA: Bisoprolol (Betablocker limitiert HR-Anstieg)
H2 LÜCKE: Troponin, NT-proBNP, EKG, Ödeme?
```

### Schritt 5 — Red-Flag-Check

```
⚠ Troponin nicht dokumentiert — bei Dyspnoe + Tachykardie erforderlich
⚠ Sauerstoffsättigung nicht dokumentiert
```

### Schritt 6 — Rendering

```
STRUKTURIERTE ZUSAMMENFASSUNG
  Hauptsymptome:    Belastungsdyspnoe (3 Tage), Erschöpfung
  Verlauf:          Ruhepuls-Anstieg über 7 Tage (Wearable)
  Messdaten:        CRP 28 mg/L (erhöht)
  Vorerkrankungen:  COPD, Bisoprolol

RELEVANTE CLAIMS (mit Quelle)
  • Erhöhter Ruhepuls seit 7 Tagen (+26%) — Wearable [patient_generated]
  • Belastungsdyspnoe seit 3 Tagen — Patientengespräch [patient_generated]
  • CRP 28 mg/L erhöht — Labor [lab_confirmed]
  • Bekannte COPD — Arztbrief [clinician_observed]
  • Bisoprolol 5mg täglich — Medikation [clinician_observed]

KLINISCHE EINORDNUNG
  Hypothese A: Infektexazerbation bei COPD — mäßig gestützt (0.74)
  Hypothese B: Kardiale Dekompensation — schwach-mittel gestützt (0.51)
  Hypothese C: Medikamentennebenwirkung — schwach gestützt (0.28)

OFFENE PUNKTE / NÄCHSTE SCHRITTE
  • Troponin + NT-proBNP — kardiale Ursache ausschließen
  • Aktuelle Sauerstoffsättigung (SpO2) messen
  • Prokalzitonin — bakteriell vs. viral differenzieren
  • Ödeme / Gewichtszunahme anamnestisch klären
  • EKG bei Tachykardie-Trend
```

---

## 9. v1 / v2 Modulabgrenzung

### v1 — Demonstrator

| Modul | v1-Umfang |
|-------|-----------|
| **A Intake** | Freitext, manuelle Lab-Eingabe, Wearable-Stub (Mock-Daten) |
| **B Claim Engine** | LLM-Extraktion + Normalisierung + Metadaten-Annotation |
| **C Evidence Engine** | Scoring mit 6 Scorern, Composite Scores (qSOFA/Wells/GRACE) |
| **D Guardrails** | 8 Konflikttypen, 8 Red-Flag-Regeln (hardcodiert) |
| **E Render** | Kliniker-View (Graph + 4-Block-Ausgabe), einfaches Quellen-Panel |
| **F Audit** | Strukturiertes JSON-Logging |

### v2 — Produktionsausbau

| Modul | v2-Erweiterung |
|-------|---------------|
| **A Intake** | FHIR-Adapter (Labor, Medikation), DICOM-Stub, Live-Wearable-API |
| **B Claim Engine** | NLP-Pipeline mit medizinischen NER-Modellen, SNOMED-Mapping |
| **C Evidence Engine** | ML-basierter Evidenz-Scorer, Bayesianisches Update |
| **D Guardrails** | Interaktions-Checker, SOP-Engine, Eskalations-Trigger |
| **E Render** | Patientenansicht, Arztbrief-Export, FHIR-Output |
| **F Audit** | Persistenz (Postgres), Replay, DSGVO-Export, MDR-Konformität |

---

## 10. Nicht-Ziele für v1

Bewusst ausgeschlossen, um Scope-Creep zu vermeiden:

- ❌ Vollständiger medizinischer Wissensgraph
- ❌ Autonome Diagnostik oder Therapieempfehlungen
- ❌ Multi-Agenten-Orchestrierung
- ❌ Freie Interoperabilität mit Kliniksystemen (HIS, KIS, RIS)
- ❌ FHIR R4 vollständige Compliance
- ❌ DICOM-Integration
- ❌ MDR-Zertifizierung

---

## 11. Einzeiler-Pitch

> AleXiona kombiniert ein LLM mit einer zweiten epistemischen Prüfschicht, die patientennahe, klinische und externe Wissensquellen als zeitlich markierte Claims strukturiert, gegeneinander abwägt und transparent für medizinische Entscheidungen aufbereitet.
