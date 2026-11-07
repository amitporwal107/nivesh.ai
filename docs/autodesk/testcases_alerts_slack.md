# Desk alerts to Slack — design and test cases (written before the code)

Written 7 Nov 2026 by Account 2. Status: **test cases only, nothing is built.** Source: the owner's review of the desk checks board (items R12, Q4, Q5, Q7): every warning, alert and agent conversation of the Autonomous Trading Desk goes to one Slack channel (workspace `T0CFQR34X6W`, channel `C0CFKMTJNUD`).

## 1. What exists today (checked 7 Nov)

- No Slack sender in the repo. A search for `slack` finds only the English word ("slack" meaning leeway) and one comment in `backend/nidp/deploy/prometheus_rules.yml`.
- The desk already has what a notifier needs: `autodesk.events` is an append-only log that doubles as a transactional outbox, and consumers keep a cursor in `event_cursors` (`DESIGN.md` §3).
- A separate VM health monitor is drafted in `docs/infra_monitoring/PRD.md` (draft, not built). It does not send alerts. Its VM alerts should use the same notifier (see §6).

## 2. Design

The notifier is a **consumer of `autodesk.events`**, not a call inside agent code.

```
state change + event row (one transaction)  ->  notifier reads new events by cursor
   -> filter (which events are alerts, which are workflow chat)
   -> build message (fixed format)  -> de-duplicate / rate limit
   -> transport.send()  ->  Slack channel      (record result as an event: ALERT_SENT / ALERT_FAILED)
```

- **Send-only.** No inbound Slack commands, no buttons that act on the desk. Nothing posted in Slack can change a trade, a policy or a block.
- **Never blocks the desk.** A failed or disabled notifier changes no verdict, delays no cycle and raises nothing into the caller.
- **Transport is a small interface** (`send(channel, text, thread_ts=None) -> result`), so tests use a fake transport, labelled `# MOCK — not real data` in code. The real transport posts with a Slack bot token or an incoming webhook.
- **Secret handling.** The token is read from an environment variable the owner sets on the staging environment (name to agree; proposed `AUTODESK_SLACK_BOT_TOKEN`, and `AUTODESK_SLACK_CHANNEL`). It never appears in code, logs, events, messages, test fixtures or reports.
- **Two kinds of post.**
  1. *Alerts* (top level in the channel): any BLOCKED, DEGRADED, ESCALATE, PAUSE, FREEZE, or incident, and the matching RESOLVED.
  2. *Workflow chat* (Q7, proposed): one thread per workflow, one-line summary per task or handoff. Raw payloads stay in the desk.
- **Message format.** Severity, check id and name, result, since when (IST and UTC), account or simulation label, what was already tried, what the desk may still do, next action, and a link to the desk page.
- **Wording.** Messages avoid the advice words in the owner's rule (AD-92 list).

## 3. Test cases

Method: unit tests with a fake transport and a throwaway Postgres (the usual script), plus one real-channel check that needs the owner's token. "Real" means a message that actually reached the Slack channel.

### Content and format
| ID | Case | Expected |
|---|---|---|
| AD-AL-01 | A BLOCKED pre-market result becomes an alert | One message with severity, check id, result, since, tried, desk state, next action |
| AD-AL-02 | Severity mapping | BLOCKED, FREEZE and ESCALATE are critical; DEGRADED, PAUSE are warning; RESOLVED and notices are info |
| AD-AL-03 | Times | Shown in IST and UTC, from the event's own time, not the send time |
| AD-AL-04 | Account label | Shows the account or simulation name, never a user's email or another tenant's data |
| AD-AL-05 | Wording lint | No message contains a word from the AD-92 list |
| AD-AL-06 | Size | A message over the limit is cut with a visible "truncated" marker, never dropped |

### Secrets and configuration
| ID | Case | Expected |
|---|---|---|
| AD-AL-07 | Token never leaks | Token value absent from logs, exception text, event rows, messages and `repr` of the config, including on failure |
| AD-AL-08 | Not configured | No token or channel: notifier reports DISABLED once, sends nothing, raises nothing, desk runs normally |
| AD-AL-09 | Bad token | `invalid_auth` is recorded as ALERT_FAILED with the reason, not retried, and shown as one local incident |

### Delivery
| ID | Case | Expected |
|---|---|---|
| AD-AL-10 | Timeout or 5xx | Retried up to 3 times with growing waits, then recorded ALERT_FAILED. Nothing raised |
| AD-AL-11 | Rate limited (429) | Waits as long as Retry-After says, then sends |
| AD-AL-12 | Channel not found | Permanent error: recorded, no retry loop, local incident raised |
| AD-AL-13 | Restart | After a restart the cursor resumes: no event posted twice, none skipped |
| AD-AL-14 | Outbox | A state change and its alert event commit together. A rollback leaves no alert |
| AD-AL-15 | Order | Critical alerts go before info when a burst is queued |

### Noise control
| ID | Case | Expected |
|---|---|---|
| AD-AL-16 | Same alert repeats | Same key (check, account, result) inside the window posts once, then a reply "repeated n times" |
| AD-AL-17 | Different key | A different check or account is a separate alert |
| AD-AL-18 | Burst | Above N messages a minute, the rest are collapsed into one summary line with the count |
| AD-AL-19 | Recovery | When the check clears, a RESOLVED reply appears in the original alert's thread |

### Workflow chat (depends on decision Q7)
| ID | Case | Expected |
|---|---|---|
| AD-AL-20 | One thread per workflow | The first message starts a thread; later steps are replies to it, stored by thread id |
| AD-AL-21 | Summaries only | Each task or handoff is one line, with no raw payload and no private fields |
| AD-AL-22 | Simulation separation | Simulation workflows are labelled as simulations, never mixed with the desk's |

### Safety
| ID | Case | Expected |
|---|---|---|
| AD-AL-23 | Send-only | The module has no inbound handler and no route that acts on a message |
| AD-AL-24 | No order path | The order-path guard test still passes; the notifier imports no order code |
| AD-AL-25 | Verdicts unchanged | With the transport failing, BLOCKED stays BLOCKED and a cycle still ends the same way |
| AD-AL-26 | Test message | An admin-only test action sends one message marked TEST. (Needs a route in the routers, which are Account 1's files: a `REQUEST A2->A1` on the board) |

### Real channel (UNVERIFIED until the owner provides the token)
| ID | Case | Expected |
|---|---|---|
| AD-AL-27 | Real test message | One TEST message sent from staging appears in channel `C0CFKMTJNUD`; its screenshot or ID recorded in the report. Run once, with the owner's go-ahead |
| AD-AL-28 | Real alert from a forced check | A simulated BLOCKED pre-market result produces the real alert once, and the matching RESOLVED reply |

## 4. What blocks the real checks
- AD-AL-27 and 28 need the owner to create the Slack bot or webhook with post rights to the channel and store its token in the staging environment. This session has no Slack tool, so it cannot post to or look at the channel.
- AD-AL-26 needs a route added to Account 1's routers.

## 5. Open decisions (also on the review board)
1. Q7: how much agent chat to mirror (proposed above).
2. Severity levels and who is on call for a BLOCKED result.
3. Rate limit N, dedupe window, and the retry waits.
4. Environment variable names.

## 6. Reuse by other work
The VM health monitor (`docs/infra_monitoring/PRD.md`) and the Kite login-needed alert (R13) should call the same notifier rather than add a second Slack path.
