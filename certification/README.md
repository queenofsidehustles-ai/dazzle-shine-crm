# Certifying Nana's onboarding

Run it:

    ./certification/run.sh

It makes a throwaway SQLite business, starts a local server, walks the setup
chat over real HTTP, and prints a pass/fail line per check. Nothing touches
production; no Anthropic credits are spent.

## Why this exists rather than another file in tests/

`tests/test_setup_assistant.py` replaces `setup_assistant._post`, so nothing it
runs ever builds a request body. That is a good unit test and it was green
every day that production was answering every owner with an apology, because
the model name on the wire was one that does not exist and no test has ever
looked at the wire.

Here the stub sits at `requests.post` instead. The app's own code builds the
body, picks the model, sets the headers and parses the reply; the harness
writes down what went out and checks it.

## What it certifies

- Only the owner can ask or confirm; signed out is refused on both routes.
- The outgoing request carries a published model id, the key header, the
  version header, and the tool declarations.
- A card is an offer: nothing is written before the button.
- The button saves once. A replayed token and a token that was never issued
  both save nothing, and say so.
- Pricing, a cleaner and a customer each persist and appear on their own page,
  and setup progress advances.
- When the provider fails -- a model that does not exist, or an unreachable
  API -- the owner is told something plain, no card is offered off a failed
  call, and nothing written earlier is lost.

## What it does not certify

The model's judgement. Every reply here is scripted, so this proves the
plumbing around Nana, not that Nana gives good answers. For the live path --
real key, real model, real reply -- use Console → Health → "Check that Claude
answers", which is the only check that spends a real credit and the only one
that can catch a model name that does not exist in production.
