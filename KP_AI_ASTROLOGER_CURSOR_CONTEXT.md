# KP AI Astrologer — Cursor Project Context

**Purpose of this document:**  
This is the master context file for Cursor, Codex, Claude Code, GPT-5.5, or any coding agent working on this project. Read this file before making any code, architecture, database, or prediction-logic changes.

This project is not a normal cricket prediction model. It is an explainable AI research system that combines KP astrology, selected Vedic astrology concepts, historical cricket match observations, rule discovery, agent memory, backtesting, and live prediction.

---

## 1. Project Goal

Build an AI-powered cricket prediction system called **KP AI Astrologer**.

The system should:

1. Generate astrology charts for cricket matches using match start time and venue.
2. Generate Moon timeline and Ascendant timeline at NL / SL / SSL / SSSL levels where possible.
3. Use KP astrology and selected Vedic astrology rules as the starting knowledge framework.
4. Use historical match data to discover and validate cricket-specific astrology patterns.
5. Test multiple hypotheses about how astrology maps to cricket.
6. Use an AI prediction agent to reason from:
   - current astrology chart,
   - current timeline period,
   - rulebook,
   - historical match evidence,
   - similar past matches,
   - live score movement,
   - failed prediction memory,
   - rule confidence.
7. Produce explainable predictions, not black-box predictions.
8. Log every prediction and compare it with actual result.
9. Generate post-match learning reports.
10. Update rule confidence and research hypotheses over time.
11. Eventually work with live score APIs and run during live matches.

The end goal is not just “predict winner”. The deeper goal is to build a self-improving research system that learns how cricket events, momentum, wickets, scoring phases, team advantage, and final results may correlate with KP/Vedic astrology periods.

---

## 2. Important Philosophy

Do **not** build a disposable toy MVP.

The user does not want a basic one-file demo that later needs to be thrown away.

The correct approach is:

```text
Build the final architecture from day one.
Implement one real vertical slice first.
Improve each component without rebuilding from zero.
```

Meaning:

- Build the final folder structure early.
- Build the final database schema direction early.
- Build memory, logs, rule IDs, prediction IDs, and backtesting from the beginning.
- Implement only the first end-to-end path initially.
- Avoid temporary hardcoded systems that will become useless later.

Bad approach:

```text
Simple app.py + CSV + one rule + no memory + no backtest
```

Good approach:

```text
Final architecture + one working end-to-end prediction/backtest slice
```

---

## 3. Core Insight Behind the Project

The user is not an astrologer and does not claim to know the final correct astrology method.

The system must therefore be designed as a **research and discovery engine**, not as a fixed-rule astrology bot.

The user has a basic method:

- Create Muhurta/event chart at match start.
- Generate Moon timeline.
- Generate Ascendant timeline.
- Study Moon NL / SL / SSL / SSSL periods.
- Study Ascendant timeline periods.
- Compare periods against live match events.
- Observe whether periods favour Ascendant, Descendant, batting side, bowling side, or event type.
- Learn from historical matches.

The system should not assume the correct mapping upfront.

It must test and compare multiple theories.

---

## 4. Major Hypotheses to Test

Create a file later called `project_memory/RESEARCH_HYPOTHESES.md` and track these formally.

### 4.1 Ascendant / Descendant Mapping Hypotheses

The system must test multiple possibilities:

1. Ascendant = team listed first, Descendant = team listed second.
2. Ascendant = toss winner, Descendant = opponent.
3. Ascendant = batting first team, Descendant = bowling first team.
4. Ascendant = current batting side, Descendant = current bowling side.
5. Ascendant = favourite, Descendant = underdog.
6. Ascendant = home team, Descendant = away team.
7. Ascendant = manually selected team by user.
8. Ascendant / Descendant may change meaning depending on match phase or innings.

Do not hardcode one mapping as final. Build experiment framework to compare them.

### 4.2 Direct Team Prediction vs Event-Type Prediction

Very important project insight:

Astrology may not directly predict:

```text
Asc team wins / Desc team wins
```

It may first predict cricket event types, such as:

- wicket pressure,
- scoring acceleration,
- slowdown,
- collapse,
- recovery,
- partnership,
- volatility,
- tactical shift,
- dropped catch / mistake,
- dominance phase.

Then the system should infer which side benefits:

```text
Planet period → likely event type → batting/bowling impact → Asc/Desc/team advantage
```

Example:

```text
Moon SSL Saturn → pressure / slowdown / wicket risk
If current batting side struggles → bowling side benefits
If bowling side = Desc → Desc gains momentum
```

This model may be more powerful than forcing every planet into Asc/Desc directly.

The system must test both:

- Model A: astrology directly favours Asc/Desc.
- Model B: astrology predicts event type first, then maps to side advantage.

### 4.3 Timeline Hypotheses

Test:

1. Moon timeline predicts live momentum.
2. Ascendant timeline predicts faster local changes.
3. Moon timeline + Asc timeline together are stronger than either alone.
4. SL is too broad; SSL/SSSL may be better for short-term live match phases.
5. Moon timeline may work better for momentum, while Asc timeline may work better for micro-events.
6. Cusp 1/7 may show fixed promise, but timeline may show temporary swings.

### 4.4 Target Prediction Hypotheses

The system should test different target outputs:

1. Final winner.
2. 5-over momentum.
3. 3-over momentum.
4. Wicket probability.
5. Run-rate acceleration / slowdown.
6. Collapse / recovery phase.
7. Batting side advantage.
8. Bowling side advantage.
9. Ascendant advantage.
10. Descendant advantage.

Do not assume final winner is the only useful target.

---

## 5. Astrology Knowledge Approach

The system should not rely only on the built-in knowledge of ChatGPT, DeepSeek, Claude, Gemini, etc.

AI models can help create the syllabus and interpret rules, but the system should track source authority.

### 5.1 Knowledge Sources

Suggested astrology knowledge base:

#### KP Priority Sources

- KP Reader I — Casting the Horoscope
- KP Reader II — Fundamental Principles of Astrology
- KP Reader III — Predictive Stellar Astrology
- KP Reader V — Transits
- KP Reader VI — Horary Astrology
- KP Horary / Advanced Stellar Astrology if available

#### Vedic Foundation Sources

- Brihat Parashara Hora Shastra
- Brihat Jataka
- Phaladeepika
- Saravali
- Jataka Parijata
- Uttara Kalamrita
- Prashna / Muhurta texts where relevant

### 5.2 Rule Authority Levels

Every rule should have metadata:

```text
verified_from_book
AI_suggested
historically_tested
user_observation
data_mined_candidate
validated_rule
deprecated_rule
exception_rule
```

Do not let the system present AI-suggested rules as final truth.

### 5.3 Priority Hierarchy

Suggested authority order:

1. Verified KP book rule.
2. Verified Vedic rule.
3. Repeated historical cricket evidence.
4. User observation.
5. AI model suggestion.

For cricket-specific predictions, historical cricket evidence may be highly important because classical astrology texts do not directly explain modern T20 cricket.

---

## 6. Need for Data Science / Rule Mining

The user initially preferred not to build a black-box data science model, but through discussion we concluded:

The system **does need data science-style analysis**, but mainly for:

- rule discovery,
- rule confidence scoring,
- similarity search,
- validation,
- backtesting,
- exception detection,
- hypothesis comparison.

It does **not** need to start with a black-box model like XGBoost or neural networks.

Initial focus should be explainable rule mining.

Example rule:

```json
{
  "rule_id": "AUTO_RULE_042",
  "condition": "moon_ssl=Saturn AND saturn_support=Desc",
  "outcome": "Desc momentum",
  "matches_tested": 87,
  "success_rate": 0.69,
  "confidence": "medium-high",
  "status": "candidate_rule"
}
```

Rule confidence must come from evidence, not from the LLM “feeling” confident.

---

## 7. Key System Components

The final system should have these engines:

1. **Astrology Chart Engine**
   - Generates match Muhurta/event chart.
   - Computes planets, cusps, Moon longitude, Ascendant, KP star/sub/sub-sub.

2. **Timeline Engine**
   - Generates Moon NL / SL / SSL / SSSL timeline.
   - Generates Ascendant timeline.
   - Uses precise longitude transitions, not fixed arbitrary intervals.

3. **Rulebook Engine**
   - Loads KP/Vedic/cricket rulebook.
   - Tracks rule metadata and authority.
   - Retrieves relevant rules for current match context.

4. **Historical Match Engine**
   - Stores and retrieves historical matches.
   - Finds similar matches.
   - Supports match-level and period-level retrieval.

5. **Rule Mining Engine**
   - Mines candidate rules from historical data.
   - Computes frequency, conditional patterns, and success rates.
   - Updates rule confidence.

6. **Experiment Engine**
   - Tests Asc/Desc mapping theories.
   - Tests planet-to-team vs planet-to-event models.
   - Tests timeline levels.
   - Tests target types.

7. **Prediction Agent**
   - Combines current match state, rulebook, historical evidence, live score, similar matches, and failure memory.
   - Produces structured prediction with reasoning and confidence.

8. **Examiner Agent**
   - Challenges the prediction.
   - Checks contradictions.
   - Ensures no unsupported claim is made.
   - Flags weak sample size, overfitting, or mixed logic.

9. **Learning Agent**
   - Runs after match.
   - Compares prediction vs actual result.
   - Generates learning report.
   - Suggests rule confidence updates.
   - Records exceptions and failures.

10. **Backtesting Engine**
    - Tests current system against historical data.
    - Reports accuracy by target, phase, mapping theory, and rule version.

11. **Dashboard**
    - Initially Streamlit.
    - Later may become React/FastAPI.
    - Shows match inputs, timeline, prediction, evidence, similar matches, learning reports, backtest results.

12. **Live Score Engine**
    - Later integration.
    - Fetches live score every minute or ball-by-ball.
    - Maps score events to astrology periods.

---

## 8. Agent Definition

An agent in this project is:

```text
LLM + tools + memory + goal + feedback loop
```

The prediction agent should not be a random chatbot. It must have tools and structured memory.

Before every prediction, it should:

1. Load current match state.
2. Load current astrology period.
3. Retrieve relevant rules.
4. Retrieve rule confidence.
5. Retrieve similar historical matches.
6. Retrieve failed predictions with similar conditions.
7. Retrieve post-match learning notes.
8. Consider live score confirmation.
9. Produce prediction.
10. Save prediction, evidence, and reasoning.

---

## 9. Coding Agent vs Prediction Agent

There are two different kinds of agents:

### 9.1 Coding Agent

Examples: Cursor, Codex, Claude Code, GPT-5.5.

Job:

- write code,
- fix bugs,
- improve architecture,
- create database schema,
- refactor modules,
- build tests,
- implement roadmap,
- run backtests,
- update project memory.

### 9.2 Prediction Agent

Job:

- read chart,
- read rules,
- read historical matches,
- find similar cases,
- reason about current match,
- predict event/team advantage,
- save prediction,
- learn from actual result.

Do not confuse these two.

The coding agent improves the software.  
The prediction agent improves cricket prediction reasoning.

---

## 10. Memory Design

Do not rely on Cursor chat history or ChatGPT memory.

Memory must live inside the project folder.

### 10.1 Coding Agent Memory

Create:

```text
project_memory/
    START_HERE_FOR_AGENTS.md
    PROJECT_SPEC.md
    CURRENT_STATE.md
    DECISION_LOG.md
    ROADMAP.md
    TODO.md
    BUG_LOG.md
    CHANGELOG.md
    DATA_SCHEMA.md
    BACKTESTING_GUIDE.md
    RULE_CHANGE_LOG.md
    RESEARCH_HYPOTHESES.md
```

Coding agents must read `START_HERE_FOR_AGENTS.md` first.

### 10.2 Prediction Agent Memory

Create:

```text
prediction_memory/
    PREDICTION_AGENT_SYSTEM_PROMPT.md
    rulebook/
        kp_rules.md
        vedic_rules.md
        cricket_rules.md
        rule_confidence.json
    experiments/
        asc_desc_mapping_tests.csv
        planet_event_mapping_tests.csv
        timeline_level_tests.csv
    logs/
        prediction_logs.csv
        live_match_logs.csv
        post_match_learning.csv
    reports/
        match_learning_reports/
        weekly_rule_reports/
        failed_prediction_reports/
    vector_memory/
```

Prediction memory must include:

- historical matches,
- rulebook,
- rule confidence,
- similar match evidence,
- prediction logs,
- failed prediction memory,
- post-match learning reports,
- backtest results.

### 10.3 Memory Rule

Every agent must follow:

```text
Before acting, read memory.
While acting, use memory.
After acting, update memory.
```

---

## 11. Proposed Folder Structure

```text
KP_cricket_predictor/
│
├── app/
│   └── app.py
│
├── agents/
│   ├── prediction_agent.py
│   ├── research_agent.py
│   ├── learning_agent.py
│   ├── examiner_agent.py
│   └── backtest_agent.py
│
├── tools/
│   ├── astrology_tools.py
│   ├── timeline_tools.py
│   ├── rulebook_tools.py
│   ├── historical_match_tools.py
│   ├── rule_mining_tools.py
│   ├── experiment_tools.py
│   ├── live_score_tools.py
│   └── memory_tools.py
│
├── scripts/
│   ├── chart_generator.py
│   ├── muhurta_timeline.py
│   ├── generate_nakshatra_sub_lords.py
│   ├── backtest_agent.py
│   ├── update_rule_confidence.py
│   ├── run_mapping_experiments.py
│   └── memory_health_check.py
│
├── data/
│   ├── raw/
│   ├── processed/
│   ├── historical_matches.csv
│   ├── match_timelines.csv
│   ├── prediction_logs.csv
│   └── backtest_results.csv
│
├── database/
│   ├── kp_cricket.db
│   ├── schema.sql
│   └── migrations/
│
├── knowledge_base/
│   ├── kp/
│   ├── vedic/
│   ├── cricket_rules/
│   └── observations/
│
├── prediction_memory/
│   ├── PREDICTION_AGENT_SYSTEM_PROMPT.md
│   ├── rulebook/
│   ├── experiments/
│   ├── logs/
│   ├── reports/
│   └── vector_memory/
│
├── project_memory/
│   ├── START_HERE_FOR_AGENTS.md
│   ├── PROJECT_SPEC.md
│   ├── CURRENT_STATE.md
│   ├── DECISION_LOG.md
│   ├── ROADMAP.md
│   ├── TODO.md
│   ├── BUG_LOG.md
│   ├── CHANGELOG.md
│   ├── DATA_SCHEMA.md
│   ├── BACKTESTING_GUIDE.md
│   ├── RULE_CHANGE_LOG.md
│   └── RESEARCH_HYPOTHESES.md
│
├── tests/
│   ├── test_chart_engine.py
│   ├── test_timeline_engine.py
│   ├── test_rulebook.py
│   ├── test_similarity.py
│   ├── test_backtesting.py
│   └── test_prediction_agent.py
│
├── .env.example
├── requirements.txt
├── README.md
└── pyproject.toml
```

---

## 12. Database Direction

The user asked whether to build locally or directly in cloud.

Recommended approach:

```text
Build locally first, but design cloud-ready from day one.
```

Start with SQLite locally if needed, but design schema so PostgreSQL migration is easy.

Use environment variables:

```text
DATABASE_URL=sqlite:///database/kp_cricket.db
OPENAI_API_KEY=...
CRICKET_API_KEY=...
```

Later:

```text
DATABASE_URL=postgresql://...
```

### 12.1 Suggested Tables

Create schema for:

```text
matches
teams
venues
match_charts
planet_positions
cusp_data
moon_timeline_periods
asc_timeline_periods
ball_events
period_summaries
rulebook_rules
rule_confidence
mapping_experiments
predictions
prediction_evidence
learning_reports
backtest_runs
backtest_results
failed_prediction_cases
```

Not every table must be fully used on day one, but design the structure early.

---

## 13. First Real Vertical Slice

Do not build a toy agent. Build the first real vertical slice of the final system.

First vertical slice:

```text
Historical match
→ astrology data
→ timeline periods
→ rulebook
→ similar match retrieval
→ rule confidence lookup
→ prediction agent
→ prediction log
→ actual result comparison
→ learning report
→ backtest summary
```

Minimum working version should:

1. Load one or more historical matches.
2. Load chart/timeline data for those matches.
3. Load rulebook.
4. Retrieve similar matches.
5. Generate a prediction using the prediction agent.
6. Store prediction and evidence.
7. Compare against actual result.
8. Generate a learning report.
9. Add result to backtest report.

This is not a throwaway MVP. It is the first working path of the final system.

---

## 14. Backtesting Requirements

Backtesting is central. The system must measure whether changes improve prediction.

Backtest should report:

- total matches tested,
- final winner accuracy,
- period momentum accuracy,
- wicket-period accuracy,
- run-rate direction accuracy,
- pre-match accuracy,
- after toss accuracy,
- after 5 overs accuracy,
- after 10 overs accuracy,
- confidence calibration,
- accuracy by Asc/Desc mapping theory,
- accuracy by planet,
- accuracy by Moon SL/SSL/SSSL,
- accuracy by match format,
- best rules,
- worst rules,
- failed prediction clusters.

Every prediction logic change must have before/after backtest results.

---

## 15. Rule Change Policy

Coding agents must not freely change prediction logic.

Every prediction logic change must:

1. Be documented in `project_memory/RULE_CHANGE_LOG.md`.
2. Have a reason.
3. Have a rule ID.
4. Be backtested.
5. Show before/after results.
6. Be reversible.

Example log:

```text
Rule change 004:

Old rule:
Moon SSL Saturn generally favours Desc.

New rule:
Moon SSL Saturn indicates pressure/slowdown/wicket risk first. The side affected depends on batting/bowling context and house linkage.

Reason:
Historical analysis showed Saturn periods often hurt batting side, not always Asc side.

Backtest:
Before: 56.2%
After: 59.8%

Status:
Accepted.
```

---

## 16. Prediction Output Format

Prediction agent should output structured answer:

```text
Current Match State:
- Match
- Current score
- Current innings/over
- Current batting side
- Current bowling side
- Asc/Desc mapping used

Current Astrology:
- Moon NL/SL/SSL/SSSL
- Asc NL/SL/SSL/SSSL
- relevant cusps
- relevant planet significations

Rulebook View:
- rules used
- rule IDs
- source authority

Historical Evidence:
- number of similar matches
- similar match outcomes
- period-level evidence
- rule confidence

Failure Memory:
- similar failed predictions
- known exceptions

Live Score Confirmation:
- whether live score confirms or contradicts astrology

Prediction:
- likely event type
- batting/bowling advantage
- Asc/Desc advantage
- final winner view if applicable
- confidence

Next Watch:
- next important period
- what would strengthen/reverse prediction
```

---

## 17. Local vs Cloud Strategy

Recommended path:

```text
Local end-state skeleton
→ local backtesting and learning
→ cloud database
→ cloud storage
→ hosted dashboard
→ live automated prediction system
```

Do not directly start with full cloud unless there is a strong reason.

But keep code cloud-ready:

- use `.env`,
- keep app/agents/tools/data separate,
- avoid hardcoded paths,
- use database abstraction,
- prepare for PostgreSQL migration,
- keep long-term files structured.

---

## 18. Cursor / Coding Agent Instructions

Any coding agent must follow these rules:

1. Read this file first.
2. Read `project_memory/START_HERE_FOR_AGENTS.md` if it exists.
3. Do not create a disposable MVP.
4. Build final modular architecture from the beginning.
5. Implement one vertical slice at a time.
6. Do not hardcode one Asc/Desc mapping as final.
7. Do not change prediction rules without updating `RULE_CHANGE_LOG.md`.
8. Any prediction logic change requires backtesting.
9. Keep UI separate from logic.
10. Keep astrology calculations separate from agent reasoning.
11. Keep LLM prompts/templates versioned.
12. Store predictions, evidence, and learning reports.
13. Add tests for new modules.
14. Update `CURRENT_STATE.md` after meaningful code changes.
15. Update `TODO.md` with remaining work.
16. Prefer small, reviewable changes.
17. Never delete existing project memory unless explicitly asked.
18. When uncertain, create a documented hypothesis instead of assuming.

---

## 19. Immediate Next Steps for GPT-5.5 / Cursor Planning

The next planning session should produce:

1. Database schema v1.
2. Folder structure implementation plan.
3. Memory files templates.
4. First vertical slice implementation plan.
5. Data schema for historical matches.
6. Rulebook JSON/Markdown schema.
7. Backtest framework design.
8. Prediction context pack format.
9. Agent prompt templates.
10. Cursor task list in build order.

---

## 20. Summary

This project should be built as an explainable, evidence-based AI research system for cricket astrology prediction.

The core principle:

```text
Astrology rules provide theory.
Historical matches provide evidence.
Rule mining provides confidence.
Agents provide reasoning.
Backtesting provides truth-checking.
Memory prevents forgetting.
Live matches provide new learning.
```

The system should not pretend to know the final correct method upfront.

It should test hypotheses, store evidence, learn from failures, and gradually improve.

