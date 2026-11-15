To: assessment@enam.com
Subject: IIT Delhi – AI Engineer - 2027

Hi,

My submission for the FINN build challenge:

- Prototype (open on a phone): [DEPLOYED LINK]
- Repository: [GITHUB LINK]
- AI build history: [SHARE LINK / ATTACHED EXPORT]

What I built
FINN is a mobile web app with three screens. The Brief opens with one sentence ("4 need you. 19 don't.")
and ranks every filing across a 20-stock NSE portfolio for a window I choose: full cards for what
matters, one line for what is worth knowing, a grey count for the routine paperwork. Results filings
show Revenue, EBITDA, PBT and PAT with QoQ and YoY on the card; a management change shows the incoming
person's background, taken from the profile in the filing itself. Price and volume alerts run on
thresholds the user sets with sliders, and each move is paired with the filing that most likely caused
it. Ask takes any NSE ticker and builds a research view from the company's statements, concall
transcripts and annual report. Its centrepiece is "Said vs did": numeric guidance from the last five
calls laid against what was then reported, including when guidance was cut and whether the company met
the original number or only the lowered one.

Key decisions and trade-offs
1. Filter, don't aggregate. Every design choice serves the split between "needs you" and "buried".
   Same-day filings on one topic are folded together, and nothing is deleted.
2. Models extract, code decides. A model never computes or grades a number. It pulls out what
   management said; plain arithmetic compares it with the reported figures. That costs some coverage
   (capex and qualitative guidance are shown but not graded) and buys trust.
3. Cheapest tool that works. Rules classify formulaic filings; only ambiguous ones go to a small model,
   batched. Retrieval is TF-IDF over pages rather than embeddings. The strong model is called once per
   company on a compact fact sheet. Everything immutable is cached by content hash. The app runs end to
   end with no model key at all, on regex and rules, and tells the user which path produced what.
4. Resilience over purity on the data plumbing. Filings come from NSE, then BSE, then screener.in;
   every source falls back to its last good answer and the brief says when it is stale or incomplete.
5. Stateless server, state on the phone, so it survives free-tier restarts and several reviewers at once.
6. Interaction: one input that takes a ticker, a question, a time window or a rule, by typing or voice,
   and a spoken version of the brief.

What I left out on purpose
Accounts, intraday data, OCR for scanned filings, a vector database, position sizes and P&L, and grading
of guidance that cannot be checked against the standardised statements.

Where I would take it next
Cross-check filing-parsed results against standardised tables, OCR fallback, true web push with the app
closed, segment-level said-vs-did, peer context on each card, and ranking that learns from what the
user buries.

I built this with Claude as a coding agent; the full conversation is in the build history above.

Thanks,
[YOUR NAME]
[ROLL NUMBER / CONTACT]
