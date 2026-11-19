# Flame Atlas — Loom Script

**Role:** Full Stack Engineer, Discovered Labs
**Speaker:** Ayoub
**Target length:** about 9 minutes

---

## 0:00–0:30 — Intro

Hi, I'm Ayoub. I'm applying for the Full Stack Engineer role on the Automations team.

Today I'll show you one piece of code I'm proud of: the grounded-answer pipeline in Flame Atlas. Then I'll explain the hardest bug I hit in this project and how I fixed it.

Flame Atlas is a FastAPI backend that answers questions about 15 NASA microgravity combustion experiments. It uses Python, Pydantic AI with Gemini, a typed tool layer over the data, and OpenTelemetry traces sent to Langfuse. For automation work, reliability means keeping AI output bounded and easy to verify.

## 0:30–4:30 — The code I'm proud of

The main idea is simple. The model can write prose, but it cannot invent facts. In scientific data, a wrong citation that sounds real is worse than no answer at all.

The agent has 13 tools to look up measurements, rankings, and metadata. The model chooses which tools to call and writes the final explanation. Every structured claim and citation must trace back to a real tool result.

Each tool returns an Envelope. The Envelope holds three things: the data, the provenance, and warnings. Provenance is a record of where the data came from: the investigation ID, the source file, and the exact fields used.

The run keeps a record of every tool call. Grounded provenance is the current turn plus earlier turns of the conversation. So a follow-up question can reuse verified evidence without pretending the model remembers data it never saw.

When the model finishes, it returns a structured answer with citations. Each citation has four fields: investigation ID, source file, PSI ID, and URL.

Before anything goes back to the user, the `assemble` function runs three checks.

1. If there were no successful tool calls and no earlier evidence, it raises `UNGROUNDED_ANSWER`. The model cannot answer from memory.
2. Each citation must be structurally valid. The investigation must exist, the source file must belong to it, the PSI ID must match it, and the URL must match the local reference template. A made-up PSI ID fails as `INVALID_CITATION`.
3. Each citation's investigation ID and source file pair must appear in the provenance of a tool result from this conversation. Even if the ID is real, if no tool returned it, it fails as `UNGROUNDED_CITATION`.

Prompts ask the model not to hallucinate. This code enforces it.

The same rule applies to numbers. Rankings and oxygen-window coverage are recalculated in Python inside `assemble`. The model never supplies totals or ordering as raw data.

The tests cover a made-up PSI ID, a citation no tool returned, and an answer with no tool calls. They check the exact error codes and the 422 status responses.

## 4:30–7:30 — The hardest bug

The hardest problem here did not produce a stack trace.

A `POST` request to `/api/agent` returned a 500 error after 60.5 seconds. The access log had one line with no explanation.

To find out what happened, I rebuilt the timeline by matching the request ID across three logs: the API log, the model HTTP log, and the tool-call log. I also used the Langfuse trace.

What I found: the model called the `get_environments` tool 39 times in a row. Every model call returned 200 OK. Every tool call finished in one to three milliseconds with no error. Nothing crashed.

The failure was logical. The model kept asking the same question and never produced a final answer, until the 60-second timeout stopped it.

This was hard to diagnose for three reasons. Every service looked healthy. The timeout hid the real cause. And the same day, a different 503 came from a Gemini 429 quota error, so the HTTP status alone told me nothing.

Correlating the request ID across the logs and trusting the sequence in the trace is what got me unstuck.

I fixed the bug at the narrowest layer that owns this rule: the tool wrapper. Before a tool runs, the wrapper compares the tool name and arguments with the previous call. If they are identical, it logs the issue and raises a `REPEATED_TOOL_CALL` error with a 422 status.

The runner passes tool faults straight through instead of turning them into 503 errors. So the request now fails on the second turn instead of hanging for a full minute.

I chose to fail fast on purpose. Sending an error back to a model that is already looping can make it loop again and waste quota and time. A fast, predictable failure is better than a slow one.

I added a regression test with a fake model that always emits the same tool call. It asserts the exact fault code, the 422 status, and that the model is called only twice.

One honest limitation: the guard checks only the previous call, so an A-B-A loop can still slip through. That is a loop that alternates between two different calls.

My next steps are to track a set of all calls in the run, log the last tool call when a timeout happens because that branch is currently silent, and turn this trace into a permanent evaluation test case.

## 7:30–9:00 — Search path and close

The same discipline applies to the search path. Catalog search uses BM25 as a reliable baseline, with an optional ONNX cross-encoder reranker. It is measured with Recall@5 and nDCG@10. If the reranker is missing or fails, search falls back to BM25 order without adding or dropping any records.

In all of these parts, the rule is the same: keep non-deterministic AI components bounded, and verify every structured output against what actually happened.

That is the kind of reliable engineering I want to bring to the Automations team. Thank you.
