# Research status and failures

This release is a pre-sprint software prototype. Its operational target is the
recorded source and frequency of intermediate steering, not intent, responsibility,
real-world human identity or a model's internal causal mechanism. It does not yet
match the full official incident-attribution challenge.

## Evidence classes

1. **Deterministic fixtures:** six mock task families, three control arrangements,
   two worker styles and two repetitions. The 72 sessions and 648 baseline
   predictions are constructed software diagnostics, not independent research
   observations. Perfect complete-view fixture recovery reads setup information.
2. **Historical local-model diagnostics:** limited genuine inference with one
   small Qwen3-0.6B Q8 model through a local WASM runtime, no human participants.
   Model aliases did not establish different underlying models.
3. **Future research:** genuine reviewed steering data, a capable evaluator,
   protocol freeze and appropriate held-out evaluation remain unfinished. No
   competition-period results exist in this initial release.

## Original model failures

Two completed automated mock workflows had task correctness of 3/4 and 4/4. That
does not validate the attribution evaluator. In the later original evaluator run:

| Evidence | Recorded arrangement | Saved output | Observed outcome |
| --- | --- | --- | --- |
| Outward activity | standing instruction | `human_steps` | Schema-valid but wrong relative to the recorded setup; about 284.4 seconds |
| Activity plus messages | standing instruction | `human_steps` | Schema-valid but wrong relative to the recorded setup; about 210.4 seconds |
| Complete records | standing instruction | No saved prediction | Reached the 600-second inference deadline; failed attempt retained at 602.25 seconds |

The third attempt's stored application error category is `transport`; the runtime
diagnosis identified the inference deadline. It is not counted as a completed or
correct prediction. Even a correct setup label in a complete record would not
independently authenticate a human or prove reliable attribution.

A subsequent diagnostic pass copied four literal label controls successfully,
but two revised evidence prompts still returned wrong labels. A complete-record
attempt was interrupted during host resource failure, with no generated output.
Those observations do not isolate a single cause such as prompt length, schema,
evidence quality or model capacity. No stronger capability claim is supported.

A source-bound development plan separates schema, rendering length and evaluator
choice. Its 64 future cells were not executed or scored. Historical replay is
reuse of saved responses, never new inference. Raw archives and the earlier
frozen plan remain preserved locally; they are excluded from this public copy.
The redesigned source is a later revision and is not silently substituted into
that earlier freeze.

## Remaining gates

- Collect and review genuine participant provenance; browser events alone do not
  authenticate human choices. Participation/age eligibility and affiliations have
  not been resolved for submission.
- Establish a usable, specifically authorized model route and adequate evaluator
  capability before spending resources on a new frozen evaluation.
- Review the event's final security/publication rules, dataset and report template
  when released. Do not publish incident data or restricted challenge materials.
- Disclose all pre-sprint preparation and report only work actually done during the
  judged period as sprint work. No registration or submission is claimed here.

The [validation record](validation.md) documents software behavior only. The
working interface is not evidence that these research gates have been passed.
