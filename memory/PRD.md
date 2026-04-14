# nivesh.ai — AI Financial Advisor Platform (v2.0)

## Architecture (Refactored)
```
backend/
├── server.py          # Thin routing layer only
├── models.py          # Pydantic models with strict enums & validation
├── repository.py      # MongoDB abstraction (User, Session, Portfolio, Holding repos)
├── middleware.py       # Rate limiting (60/min), env validation
├── services/
│   ├── __init__.py    # Portfolio intelligence: health score, risk analysis, recommendations
│   └── ai_engine.py   # AI layer: prompt strategy, guardrails, structured outputs
└── instruments_data.py # Indian stocks/MFs autocomplete database
```

## Product Intelligence (NEW)
- **Health Score**: Composite 0-100 (diversification 30% + risk 25% + cost 20% + performance 25%) with A+/A/B/C/D/F grades
- **Risk Analysis**: Concentration HHI, sector exposure, equity overweight, dead positions
- **Smart Recommendations**: Rule-based (Regular→Direct switch, dead positions, debt allocation, loss harvesting)
- **AI Insights**: GPT-5.2 powered (Priority Matrix, Overlap Heatmap, Cost Leakage, Action Funnel)

## Security
- Rate limiting: 120 req/min (API), 20 req/min (AI endpoints)
- Session refresh on each request
- Env validation on startup
- AI guardrails (no return guarantees)

## Backlog
- [ ] Real-time market prices (NSE API)
- [ ] Token refresh mechanism
- [ ] ML-based portfolio scoring
- [ ] Automated weekly reports
