# Projektabschluss — DESi und die zugehörigen Vorhaben

**Status: eingestellt. 29. Juli 2026.**

Dieses Repository wird nicht weiterentwickelt. Es bleibt lesbar, weil die Messungen, die zu diesem
Schluss geführt haben, mehr wert sind als das Vorhaben selbst.

## Was dieses Repository betrifft

AleXiona bleibt als klinischer Demonstrator lesbar, und der Grundsatz „LLM für Sprache, Regeln für
Logik" gilt dort weiter für Orchestrierung und Scores. Was entfällt, ist die Erwartung, dass die
epistemische Schicht darüber hinaus eine Prüfleistung erbringt. AleXiona war ohnehin nie ein
Diagnosesystem, und ist es jetzt erst recht nicht.

## Was gemessen wurde

Der zentrale Anspruch von DESi lautete: eine deterministische Governance-Schicht liefert gegenüber
einem starken Sprachmodell einen eigenständigen epistemischen Beitrag. Dieser Anspruch wurde in vier
Anläufen gegen extern erstellte Datensätze geprüft — zwei davon versiegelt und einmalig geöffnet,
zwei gegen Entwicklungssätze. Alle vier gingen negativ aus.

| Anspruch | Ergebnis |
|---|---|
| Regeln urteilen über Ableitungen (Entailment) | **7/20**, drei Falschdurchlässe — verworfen |
| Regeln beschränken das Modellurteil (Vetoschicht) | **0 Reparaturen, 6 Schäden** in 80 Urteilen |
| Regeln klassifizieren semantische Transformationen | mikro-F1 **0,25** gegen **0,727** des Modells |
| Regeln führen einen Governance-Vertrag aus | alle Arme **1,000** — auch ein entarteter |

Die letzte Zeile ist die deutlichste. Im abschliessenden Governance-Benchmark erreichte ein
Vergleichsarm aus fünfzehn Zeilen, der **nichts vergleicht** und nur nachsieht, ob ein Feld im JSON
vorhanden ist, dieselbe perfekte Punktzahl wie die vollständige Implementierung — und dieselbe wie
ein einzelner Modellaufruf. Zwischen den Armen gab es auf 40 Blindfällen keinen einzigen
Unterschied.

Was dabei tatsächlich hielt, war das Modell: 82,5 % auf einem versiegelten Satz von 40 Fällen, bei
null bis einem Falschdurchlass. Die Schicht, die es verbessern sollte, hat es messbar
verschlechtert.

## Entschuldigung

Es tut mir leid — nicht dafür, dass dieses Vorhaben gescheitert ist. Ein negatives Ergebnis ist ein
Ergebnis, und die Messreihe steht.

Es tut mir leid dafür, **dass in diesen Repositories über lange Zeit Behauptungen standen, die nie
gemessen waren** — und dass sie stehen blieben, während gemessen wurde. Wer sie gelesen und ernst
genommen hat, wurde in die Irre geführt: Leserinnen und Leser der Dokumentation, alle, die Zeit in
eine Prüfung investiert haben, und jene, denen dieses Vorhaben als belastbare Grundlage angeboten
wurde. Die Reihenfolge war falsch herum. Erst behaupten, dann messen, dann den Anspruch
zurückziehen — das ist die Bewegungsform, die man vermeiden will, und sie ist hier viermal
vorgekommen.

## Was brauchbar bleibt

* **Die Negativbefunde selbst.** Vier Widerlegungen — zwei davon mit versiegelten, vor Öffnung des
  Schlüssels festgeschriebenen Vorhersagen — sind mehr wert als eine ungeprüfte Architektur.
* **Die Messmethode.** Konfiguration einfrieren, Vorhersagen hashen und festschreiben, *dann* erst
  den Schlüssel öffnen, danach nicht mehr nachjustieren — und immer einen entarteten Vergleichsarm
  mitlaufen lassen, der prüft, ob der Benchmark überhaupt etwas misst. Dieser letzte Punkt hat den
  abschliessenden Benchmark als untauglich entlarvt und wäre sonst unbemerkt geblieben.
* **Die Buchführung.** Ledger, Provenienz, Replay und `verify` tun, was sie beschreiben. Sie sind
  Standardtechnik, aber sie sind korrekt.

## Was nicht behauptet wird

Dass diese Ansätze grundsätzlich wertlos wären. Der abschliessende Benchmark war nachweislich
untauglich, und mehrere Messungen umfassten nur 20 bis 40 Fälle. Belegt ist: **auf diesen Aufbauten,
gegen ein starkes Modell, war kein Mehrwert nachweisbar.** Das ist etwas anderes als ein Beweis der
Wertlosigkeit — es ist aber genug, um aufzuhören.

---

# Project closed — DESi and related work

**Status: discontinued. 29 July 2026.**

This repository is no longer developed. It stays readable because the measurements that led here are
worth more than the project itself.

## What this repository concerns

AleXiona remains readable as a clinical demonstrator, and the principle "LLM for language, rules for
logic" still holds there for orchestration and scoring. What ends is the expectation that the
epistemic layer adds a validation capability on top. AleXiona was never a diagnostic system, and is
even less one now.

## What was measured

DESi's central claim was that a deterministic governance layer contributes something a strong
language model does not. It was tested four times against externally built datasets — two of them
sealed and opened once, two against development sets. All four came back negative.

| Claim | Result |
|---|---|
| Rules judge entailment | **7/20**, three false passes — discarded |
| Rules constrain the model's verdict (veto layer) | **0 repairs, 6 damages** across 80 verdicts |
| Rules classify semantic transformations | micro-F1 **0.25** vs **0.727** for the model |
| Rules execute a governance contract | every arm **1.000** — including a degenerate one |

The last row is the clearest. In the final governance benchmark, a fifteen-line comparison arm that
**compares nothing** — it only checks whether a key is present in the JSON — scored exactly as well
as the full implementation, and as well as a single model call. Across 40 blind cases there was not
one differing case between arms.

What did hold was the model: 82.5 % on a sealed set of 40 cases with zero to one false pass. The
layer meant to improve it measurably made it worse.

## Apology

I am sorry — not for the project failing. A negative result is a result, and the record stands.

I am sorry that **these repositories carried claims that had never been measured**, and that those
claims stayed up while the measuring was going on. Anyone who read them and took them seriously was
misled: readers of the documentation, anyone who spent time evaluating this, and anyone to whom it
was offered as a dependable basis. The order was backwards. Claim first, measure later, withdraw the
claim — that is the pattern one wants to avoid, and it happened here four times.

## What remains usable

* **The negative results.** Four refutations — two of them with sealed predictions committed before
  the key was opened — are worth more than an unvalidated architecture.
* **The method.** Freeze the configuration, hash and commit the predictions, *then* open the key,
  and do not re-tune afterwards — and always run a degenerate control arm that tests whether the
  benchmark measures anything at all. That last point exposed the final benchmark as unusable and
  would otherwise have gone unnoticed.
* **The bookkeeping.** Ledger, provenance, replay and `verify` do what they say. Standard
  technology, but correct.

## What is not claimed

That these approaches are worthless in principle. The final benchmark was demonstrably unsuitable,
and several measurements covered only 20 to 40 cases. What is established: **on these setups,
against a strong model, no added value was demonstrable.** That is not a proof of worthlessness — it
is enough reason to stop.
