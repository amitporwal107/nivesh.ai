/* @ds-bundle: {"format":3,"namespace":"NiveshCopilotDesignSystem_21f531","components":[],"sourceHashes":{"app/atoms.jsx":"b9434577203c","app/data.jsx":"5c536b2c4a83","app/desktop.jsx":"ebc844bf84e3","app/engine.jsx":"3801c9b58e2c","app/mobile.jsx":"4b5f61fd3702","app/tweaks-panel.jsx":"6591467622ed","app/widgets.jsx":"8e14ec317a2c","ui_kits/copilot/screens-chat.jsx":"577027512e3a"},"inlinedExternals":[],"unexposedExports":[]} */

(() => {

const __ds_ns = (window.NiveshCopilotDesignSystem_21f531 = window.NiveshCopilotDesignSystem_21f531 || {});

const __ds_scope = {};

(__ds_ns.__errors = __ds_ns.__errors || []);

// app/atoms.jsx
try { (() => {
// ─── Nivesh Copilot · shared atoms ─────────────────────────────────────────
const {
  useState: useStateA
} = React;

// Score ring — mint gradient stroke, serif number (the hero visual)
function NVScoreRing({
  size = 132,
  score = 86,
  animate = true
}) {
  const r = (size - 18) / 2;
  const c = 2 * Math.PI * r;
  const cx = size / 2;
  const doAnim = animate && !window.__NV_RING_STATIC;
  const [shown, setShown] = useStateA(doAnim ? 0 : score);
  React.useEffect(() => {
    if (!doAnim) {
      setShown(score);
      return;
    }
    let raf, start;
    const dur = 900;
    const step = ts => {
      if (!start) start = ts;
      const p = Math.min(1, (ts - start) / dur);
      const e = 1 - Math.pow(1 - p, 3);
      setShown(Math.round(score * e));
      if (p < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [score, animate]);
  const dash = c * (shown / 100);
  return /*#__PURE__*/React.createElement("svg", {
    width: size,
    height: size,
    viewBox: `0 0 ${size} ${size}`
  }, /*#__PURE__*/React.createElement("defs", null, /*#__PURE__*/React.createElement("linearGradient", {
    id: `ring-${size}`,
    x1: "0",
    y1: "0",
    x2: "1",
    y2: "1"
  }, /*#__PURE__*/React.createElement("stop", {
    offset: "0",
    stopColor: "var(--mint)"
  }), /*#__PURE__*/React.createElement("stop", {
    offset: "1",
    stopColor: "var(--mint-2)"
  }))), /*#__PURE__*/React.createElement("circle", {
    cx: cx,
    cy: cx,
    r: r,
    fill: "none",
    stroke: "var(--bg-3)",
    strokeWidth: "10"
  }), /*#__PURE__*/React.createElement("circle", {
    cx: cx,
    cy: cx,
    r: r,
    fill: "none",
    stroke: `url(#ring-${size})`,
    strokeWidth: "10",
    strokeDasharray: `${dash} ${c - dash}`,
    strokeLinecap: "round",
    transform: `rotate(-90 ${cx} ${cx})`
  }), /*#__PURE__*/React.createElement("text", {
    x: cx,
    y: cx - 2,
    textAnchor: "middle",
    dominantBaseline: "middle",
    fill: "var(--ink)",
    fontFamily: "var(--display)",
    fontSize: size * 0.34,
    letterSpacing: "-0.04em"
  }, shown), /*#__PURE__*/React.createElement("text", {
    x: cx,
    y: cx + size * 0.2,
    textAnchor: "middle",
    fill: "var(--ink-3)",
    fontFamily: "var(--mono)",
    fontSize: "10",
    letterSpacing: "2"
  }, "/ 100"));
}

// Severity-ranked action row (drill-in). onPick fires the linked scenario.
function NVChatRow({
  severity,
  num,
  title,
  sub,
  value,
  delta,
  onPick
}) {
  const c = severity;
  const [hover, setHover] = useStateA(false);
  return /*#__PURE__*/React.createElement("div", {
    onClick: onPick,
    onMouseEnter: () => setHover(true),
    onMouseLeave: () => setHover(false),
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 16,
      padding: '14px 18px',
      borderRadius: 12,
      background: 'var(--bg-1)',
      border: `1px solid ${hover ? 'var(--line-3)' : 'var(--line)'}`,
      cursor: onPick ? 'pointer' : 'default',
      transition: 'all .15s ease',
      minHeight: 44
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      width: 36,
      height: 36,
      borderRadius: 10,
      background: `var(--${c}-soft)`,
      border: `1px solid var(--${c}-line)`,
      display: 'grid',
      placeItems: 'center',
      color: `var(--${c})`,
      fontFamily: 'var(--mono)',
      fontSize: 11,
      fontWeight: 600,
      letterSpacing: '.04em',
      flex: 'none'
    }
  }, num), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      minWidth: 0
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 14.5,
      fontWeight: 500,
      letterSpacing: '-0.005em'
    }
  }, title), /*#__PURE__*/React.createElement("div", {
    className: "nv-mono",
    style: {
      fontSize: 11,
      color: 'var(--ink-3)',
      marginTop: 2,
      letterSpacing: '.04em',
      textTransform: 'uppercase'
    }
  }, sub)), value && /*#__PURE__*/React.createElement("div", {
    className: "nv-num",
    style: {
      fontSize: 18,
      color: `var(--${c})`,
      fontWeight: 500
    }
  }, value), delta && /*#__PURE__*/React.createElement("div", {
    className: "nv-mono nv-num",
    style: {
      fontSize: 11,
      color: 'var(--ink-3)',
      letterSpacing: '.04em',
      textAlign: 'right'
    }
  }, delta), /*#__PURE__*/React.createElement("span", {
    style: {
      color: hover ? `var(--${c})` : 'var(--ink-3)',
      fontSize: 20,
      transition: 'color .15s ease'
    }
  }, "\u203A"));
}

// 3-dot typing pulse with routed-agent label
function NVTyping({
  agent
}) {
  const a = window.AGENTS[agent] || {
    label: 'Copilot',
    accent: 'mint',
    verb: 'is thinking'
  };
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 14,
      alignItems: 'flex-start'
    }
  }, /*#__PURE__*/React.createElement("span", {
    className: "nv-mark",
    style: {
      flex: 'none',
      marginTop: 2
    }
  }, "\u0928"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 12,
      paddingTop: 6
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      display: 'inline-flex',
      gap: 5
    }
  }, [0, 1, 2].map(i => /*#__PURE__*/React.createElement("span", {
    key: i,
    style: {
      width: 7,
      height: 7,
      borderRadius: '50%',
      background: `var(--${a.accent})`,
      animation: `nvpulse 1.1s ${i * 0.18}s infinite ease-in-out`
    }
  }))), /*#__PURE__*/React.createElement("span", {
    className: "nv-mono",
    style: {
      fontSize: 11,
      letterSpacing: '.1em',
      textTransform: 'uppercase',
      color: 'var(--ink-3)'
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      color: `var(--${a.accent})`
    }
  }, a.label), " ", a.verb, "\u2026")));
}

// Route pill — appears once intent classified
function NVRoutePill({
  agent,
  confidence
}) {
  const a = window.AGENTS[agent] || {
    label: 'Copilot',
    accent: 'mint'
  };
  return /*#__PURE__*/React.createElement("span", {
    className: `nv-pill nv-pill-${a.accent}`,
    title: `confidence ${confidence}`
  }, /*#__PURE__*/React.createElement("span", {
    className: "nv-dot",
    style: {
      background: `var(--${a.accent})`
    }
  }), a.label.toUpperCase(), " \xB7 ", (confidence * 100).toFixed(0), "%");
}

// thumbs feedback (FR-CHAT-014)
function NVFeedback({
  compact
}) {
  const [v, setV] = useStateA(0);
  const Btn = ({
    dir,
    glyph
  }) => /*#__PURE__*/React.createElement("button", {
    onClick: () => setV(v === dir ? 0 : dir),
    title: dir === 1 ? 'Helpful' : 'Not helpful',
    style: {
      width: compact ? 26 : 28,
      height: compact ? 26 : 28,
      borderRadius: 8,
      cursor: 'pointer',
      display: 'grid',
      placeItems: 'center',
      fontSize: 12,
      transition: 'all .15s ease',
      background: v === dir ? 'var(--mint-soft)' : 'transparent',
      border: `1px solid ${v === dir ? 'var(--mint-line)' : 'var(--line)'}`,
      color: v === dir ? 'var(--mint)' : 'var(--ink-3)'
    }
  }, glyph);
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 6,
      alignItems: 'center'
    }
  }, /*#__PURE__*/React.createElement(Btn, {
    dir: 1,
    glyph: "\u25B2"
  }), /*#__PURE__*/React.createElement(Btn, {
    dir: -1,
    glyph: "\u25BC"
  }));
}

// signal tile (used by portfolio_overview)
function NVSignal({
  label,
  value,
  delta,
  color
}) {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      padding: '10px 12px',
      borderRadius: 10,
      background: 'var(--bg-1)',
      border: '1px solid var(--line)'
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "nv-mono",
    style: {
      fontSize: 10,
      letterSpacing: '.1em',
      color: 'var(--ink-3)',
      textTransform: 'uppercase'
    }
  }, label), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'baseline',
      gap: 6,
      marginTop: 4
    }
  }, /*#__PURE__*/React.createElement("span", {
    className: "nv-serif nv-num",
    style: {
      fontSize: 30,
      letterSpacing: '-0.03em'
    }
  }, value), /*#__PURE__*/React.createElement("span", {
    className: "nv-mono",
    style: {
      fontSize: 10,
      color: `var(--${color})`
    }
  }, "/100")), /*#__PURE__*/React.createElement("div", {
    className: "nv-mono",
    style: {
      fontSize: 10,
      color: 'var(--ink-3)',
      letterSpacing: '.02em',
      marginTop: 2
    }
  }, delta));
}

// eyebrow caption — mono uppercase wide-tracked
function NVEyebrow({
  children,
  style
}) {
  return /*#__PURE__*/React.createElement("div", {
    className: "nv-mono",
    style: {
      fontSize: 10.5,
      letterSpacing: '.16em',
      color: 'var(--ink-3)',
      textTransform: 'uppercase',
      ...style
    }
  }, children);
}

// horizontal proportion bar (sector rotation / overlap)
function NVBar({
  pct,
  color = 'mint',
  track = 'var(--bg-3)',
  h = 6
}) {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      height: h,
      borderRadius: 999,
      background: track,
      overflow: 'hidden',
      flex: 1
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      width: `${Math.max(2, Math.min(100, pct))}%`,
      height: '100%',
      borderRadius: 999,
      background: `var(--${color})`
    }
  }));
}
Object.assign(window, {
  NVScoreRing,
  NVChatRow,
  NVTyping,
  NVRoutePill,
  NVFeedback,
  NVSignal,
  NVEyebrow,
  NVBar
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "app/atoms.jsx", error: String((e && e.message) || e) }); }

// app/data.jsx
try { (() => {
// ─── Nivesh Copilot · scripted scenario catalog ───────────────────────────
// All canned responses. Each scenario maps a prompt → routed agent → streamed
// synthesis + prose (with per-persona voice) → one structured widget → follow-ups.
// Exported to window for the engine + screens to consume.

// Agent registry — label + accent token + typing verb (FR-CHAT-003)
const AGENTS = {
  portfolio_analyst: {
    label: 'Portfolio Analyst',
    accent: 'mint',
    verb: 'is reading your holdings'
  },
  risk_analyst: {
    label: 'Risk Analyst',
    accent: 'danger',
    verb: 'is stress-testing'
  },
  tax_advisor: {
    label: 'Tax Advisor',
    accent: 'mint',
    verb: 'is scanning lots'
  },
  mf_analyst: {
    label: 'Fund Analyst',
    accent: 'indigo',
    verb: 'is comparing scorecards'
  },
  stock_analyst: {
    label: 'Stock Analyst',
    accent: 'indigo',
    verb: 'is screening'
  },
  goal_planner: {
    label: 'Goal Planner',
    accent: 'indigo',
    verb: 'is running Monte Carlo'
  },
  recommendation: {
    label: 'Recommendations',
    accent: 'amber',
    verb: 'is ranking actions'
  },
  market_analyst: {
    label: 'Market Analyst',
    accent: 'amber',
    verb: 'is reading the tape'
  },
  advisor_book: {
    label: 'Client Book',
    accent: 'indigo',
    verb: 'is querying your book'
  }
};

// helper: synthesis segments → {t, a?}; a = accent token name
const S = (t, a) => ({
  t,
  a
});

// ── The 10 scenarios (8 agents × 10 widgets) ──────────────────────────────
const SCENARIOS = {
  fix_first: {
    q: "Read my portfolio. What's the one thing I should fix first?",
    agent: 'portfolio_analyst',
    confidence: 0.94,
    synth: [S('Your portfolio is '), S('healthy', 'mint'), S(" — but financials are eating a third of every rupee you've invested.")],
    prose: "You score 86. Three issues account for almost all of that 14-point gap — concentration first, then a hidden overlap between funds, then a tax window that closes in March. I've ordered them by ₹ impact.",
    proseBeginner: "Good news — your money is in decent shape, scoring 86 out of 100. But one type of company (banks and finance) makes up too big a slice. Fixing that, plus two smaller things, closes most of the gap. I've put them in order of how many rupees each one is worth.",
    proseTrader: "Composite 86. The drag is single-factor: financials at 32% vs a 24% target, beta 1.12, and a 71% holdings overlap across three large-caps inflating your effective concentration. Tax-loss window is the only time-boxed item. Ranked by ₹ impact below.",
    widget: {
      type: 'portfolio_overview',
      data: {
        score: 86,
        grade: 'A',
        signals: [{
          label: 'Concentration',
          value: 58,
          delta: 'down 4 wow',
          color: 'amber'
        }, {
          label: 'Diversification',
          value: 78,
          delta: 'flat',
          color: 'mint'
        }, {
          label: 'Risk',
          value: 92,
          delta: 'up 2',
          color: 'mint'
        }, {
          label: 'Performance',
          value: 81,
          delta: 'up 1.4%',
          color: 'mint'
        }, {
          label: 'Goals',
          value: 74,
          delta: '2 of 3 on track',
          color: 'indigo'
        }, {
          label: 'Tax',
          value: 88,
          delta: '₹38k available',
          color: 'mint'
        }],
        actions: [{
          severity: 'amber',
          num: '01',
          title: 'Trim financials from 32% → 24%',
          sub: 'Sell HDFC Bank · ₹1.8L',
          value: '-2.3 pt risk',
          delta: '+₹0.4L/yr exp.',
          scenario: 'reduce_financials'
        }, {
          severity: 'indigo',
          num: '02',
          title: 'Consolidate 3 large-cap funds · 71% overlap',
          sub: 'Move Axis BC → Parag Flexi',
          value: '₹14k fees/yr',
          delta: 'cleaner book',
          scenario: 'fund_overlap'
        }, {
          severity: 'mint',
          num: '03',
          title: 'Harvest ₹38,400 losses before Mar 31',
          sub: '3 lots flagged · auto-rebuy +31d',
          value: '₹11,520 saved',
          delta: 'tax · LTCG',
          scenario: 'tax_harvest'
        }]
      }
    },
    followUps: [{
      id: 'reduce_financials',
      t: 'How do I reduce financials exposure?'
    }, {
      id: 'retirement',
      t: "What's my goal progress?"
    }, {
      id: 'stress_test',
      t: 'Stress-test the portfolio'
    }]
  },
  reduce_financials: {
    q: 'How do I reduce financials exposure?',
    agent: 'recommendation',
    confidence: 0.91,
    synth: [S('Sell down '), S('two positions', 'amber'), S(' and your financials drop from 32% to a target 24% — a cleaner, lower-beta book.')],
    prose: "Two moves do it without disturbing your winners. Each row shows the trade, why, and its rupee effect. Trades are educational — execution stays in your broker.",
    proseBeginner: "You don't need to sell everything. Two small sales bring banks down to a healthier slice. Below is exactly what to sell, why, and what it's worth — but actually buying or selling happens in your broker app, not here.",
    proseTrader: "Two-leg de-risk: pare HDFCBANK and ICICIBANK, redeploy into your existing Nifty 50 index sleeve to keep market exposure flat while cutting single-name idiosyncratic risk. Net beta 1.12 → 0.98.",
    widget: {
      type: 'rebalance_plan',
      data: {
        actions: [{
          isin: 'INE040A01034',
          name: 'HDFC Bank',
          direction: 'SELL',
          amount: '₹1.80 L',
          reason: 'Largest single name · 11.4% of equity'
        }, {
          isin: 'INE090A01021',
          name: 'ICICI Bank',
          direction: 'SELL',
          amount: '₹0.95 L',
          reason: 'Sector double-up with HDFC'
        }, {
          isin: 'INE composite',
          name: 'UTI Nifty 50 Index',
          direction: 'BUY',
          amount: '₹2.75 L',
          reason: 'Keep market exposure, drop single-name risk'
        }],
        net: 'Financials 32% → 24% · beta 1.12 → 0.98'
      }
    },
    followUps: [{
      id: 'stress_test',
      t: 'What does this do to my risk?'
    }, {
      id: 'fund_overlap',
      t: 'Any overlap I should clean too?'
    }]
  },
  tax_harvest: {
    q: 'Harvest my losses before March 31',
    agent: 'tax_advisor',
    confidence: 0.96,
    synth: [S('You can book '), S('₹11,520', 'mint'), S(' in tax savings by harvesting three loss-making lots before the March 31 window shuts.')],
    prose: "These lots are underwater and offset realised gains elsewhere. You can rebuy after 31 days to keep the position. Educational only — not tax filing advice.",
    proseBeginner: "Three of your holdings are currently at a loss. Selling them now lets you lower this year's tax bill, and you can buy them back after a month if you still want them. This isn't tax filing — just a heads-up on the deadline.",
    proseTrader: "Three lots with unrealised STCG losses; harvesting offsets ₹38.4k of booked gains at your slab. Wash-sale isn't codified in IN — rebuy permissible, but stagger +31d to avoid FIFO ambiguity on cost basis.",
    widget: {
      type: 'tax_harvest',
      data: {
        totalSavings: '₹11,520',
        lots: [{
          isin: 'INE733E01010',
          name: 'NTPC Green Energy',
          loss: '₹18,200',
          by: 'Mar 31'
        }, {
          isin: 'INE0J1Y01017',
          name: 'LIC of India',
          loss: '₹13,400',
          by: 'Mar 31'
        }, {
          isin: 'INE298J01013',
          name: 'Avenue Supermarts',
          loss: '₹6,800',
          by: 'Mar 31'
        }]
      }
    },
    followUps: [{
      id: 'fix_first',
      t: 'Back to my portfolio score'
    }, {
      id: 'reduce_financials',
      t: 'What should I buy with the proceeds?'
    }]
  },
  compare_funds: {
    q: 'Compare my large-cap funds',
    agent: 'mf_analyst',
    confidence: 0.89,
    synth: [S('Parag Parikh leads on every V3 axis — '), S('Axis Bluechip', 'danger'), S(' is the one to question.')],
    prose: "Quality, Health and Exit scores from NIDP, plus 3-year XIRR. Axis Bluechip trails on Health and Exit while charging more — a consolidation candidate.",
    proseBeginner: "Here's a side-by-side of your big funds, scored out of 100 on quality, health, and whether it's time to exit. The Parag Parikh fund looks strongest. Axis Bluechip is the weak link.",
    proseTrader: "V3 scorecard delta: PPFAS dominates Q/H/E with a 14.2% 3Y XIRR. Axis BC's exit score 61 + sub-benchmark XIRR flags it for rotation into the index or PPFAS overflow.",
    widget: {
      type: 'fund_comparison',
      data: {
        funds: [{
          code: '122639',
          name: 'Parag Parikh Flexi Cap',
          quality: 92,
          health: 88,
          exit: 90,
          xirr: '14.2%'
        }, {
          code: '120505',
          name: 'Mirae Asset Large Cap',
          quality: 84,
          health: 81,
          exit: 79,
          xirr: '12.6%'
        }, {
          code: '120465',
          name: 'Axis Bluechip',
          quality: 71,
          health: 64,
          exit: 61,
          xirr: '9.8%'
        }]
      }
    },
    followUps: [{
      id: 'fund_overlap',
      t: 'Do these funds overlap?'
    }, {
      id: 'reduce_financials',
      t: 'Where should the money go?'
    }]
  },
  watch_stocks: {
    q: 'Which stocks in my watchlist should I act on?',
    agent: 'stock_analyst',
    confidence: 0.87,
    synth: [S('Two names screen as '), S('buys', 'mint'), S(', one is flashing a '), S('reduce', 'danger'), S(' on the NIDP composite.')],
    prose: "Scores blend V3 fundamentals with technicals. Signals are screener output, not orders.",
    proseBeginner: "I scored the stocks you're watching out of 100. Green means they look good to add, red means consider trimming. These are signals to research — not instructions.",
    proseTrader: "NIDP composite = fundamental Z-score × technical overlay. TITAN RSI 38 (oversold reclaim), TATAMOTORS MACD bull-cross. ZOMATO RSI 74 + extended from 50-EMA → reduce.",
    widget: {
      type: 'stock_screener',
      data: {
        stocks: [{
          symbol: 'TITAN',
          name: 'Titan Company',
          score: 88,
          signal: 'BUY'
        }, {
          symbol: 'TATAMOTORS',
          name: 'Tata Motors',
          score: 82,
          signal: 'BUY'
        }, {
          symbol: 'INFY',
          name: 'Infosys',
          score: 67,
          signal: 'HOLD'
        }, {
          symbol: 'ZOMATO',
          name: 'Eternal (Zomato)',
          score: 41,
          signal: 'REDUCE'
        }]
      }
    },
    followUps: [{
      id: 'sector_rotation',
      t: 'Which sectors are rotating?'
    }, {
      id: 'stress_test',
      t: 'How risky is my equity sleeve?'
    }]
  },
  sector_rotation: {
    q: 'How is sector rotation looking for my book?',
    agent: 'market_analyst',
    confidence: 0.85,
    synth: [S('Money is rotating out of '), S('financials', 'amber'), S(' into '), S('healthcare and energy', 'mint'), S(' — your book is on the wrong side of two of them.')],
    prose: "Current vs. model-target weights across your sectors. FII flows turned net-buyers in healthcare this week.",
    proseBeginner: "Big investors are moving money between industries. You're overweight banks (which are cooling) and light on healthcare and energy (which are heating up). The table shows where you are vs. a balanced target.",
    proseTrader: "Sector momentum (1M): NIFTY FIN −2.1%, PHARMA +4.6%, ENERGY +3.2%. FII net +₹4.2k Cr into healthcare WoW. You're +8pp financials, −3pp pharma vs model.",
    widget: {
      type: 'sector_rotation',
      data: {
        sectors: [{
          name: 'Financials',
          current: 32,
          target: 24,
          delta: -8
        }, {
          name: 'Technology',
          current: 18,
          target: 18,
          delta: 0
        }, {
          name: 'Healthcare',
          current: 6,
          target: 11,
          delta: 5
        }, {
          name: 'Energy',
          current: 7,
          target: 10,
          delta: 3
        }, {
          name: 'Consumer',
          current: 14,
          target: 14,
          delta: 0
        }]
      }
    },
    followUps: [{
      id: 'reduce_financials',
      t: 'Help me cut financials'
    }, {
      id: 'watch_stocks',
      t: 'Which stocks fit the rotation?'
    }]
  },
  fund_overlap: {
    q: 'Do my mutual funds overlap?',
    agent: 'mf_analyst',
    confidence: 0.92,
    synth: [S('Three of your large-caps are '), S('71% the same fund', 'indigo'), S(' wearing different names — you\'re paying three fees for one bet.')],
    prose: "High overlap means duplicated risk and triplicated expense ratios. Consolidating into one keeps the exposure and cuts ₹14k/yr in fees.",
    proseBeginner: "Two of your funds hold mostly the same companies — 71% identical. That means you're paying for three funds but really only own one idea. Combining them saves fees without changing what you own.",
    proseTrader: "Holdings-overlap matrix: Axis BC ∩ Mirae LC = 71%, top-10 names identical ex-weighting. Triplicated TER ≈ 1.1% blended. Collapse to PPFAS + index to decorrelate.",
    widget: {
      type: 'overlap_reveal',
      data: {
        pairs: [{
          a: 'Axis Bluechip',
          b: 'Mirae Large Cap',
          pct: 71,
          common: ['HDFC Bank', 'Reliance', 'ICICI Bank', 'Infosys', '+18 more']
        }, {
          a: 'Mirae Large Cap',
          b: 'SBI Bluechip',
          pct: 58,
          common: ['HDFC Bank', 'TCS', 'Reliance', '+11 more']
        }]
      }
    },
    followUps: [{
      id: 'compare_funds',
      t: 'Which one should I keep?'
    }, {
      id: 'fix_first',
      t: 'Back to the full picture'
    }]
  },
  retirement: {
    q: 'Am I on track for retirement?',
    agent: 'goal_planner',
    confidence: 0.9,
    synth: [S('Retirement is '), S('81% likely', 'mint'), S(' — but your child-education goal is '), S('short by ₹6,400/mo', 'amber'), S('.')],
    prose: "Monte Carlo across 10,000 paths. Two of three goals clear comfortably; the education goal needs a SIP top-up to reach an 80% confidence band.",
    proseBeginner: "Out of 10,000 possible futures, you reach retirement in 81% of them — that's a good place to be. But saving for your child's education is a bit behind. Adding ₹6,400 a month fixes it.",
    proseTrader: "MC sim 10k paths, 6% real return assumption. Retirement P(success)=0.81 at current SIP. Education goal underfunded; required SIP delta +₹6.4k/mo to hit 0.80 confidence.",
    widget: {
      type: 'goal_tracker',
      data: {
        goals: [{
          name: 'Retirement · 2048',
          target: '₹3.2 Cr',
          corpus: '₹24.8 L',
          probability: 81,
          sip: '₹42,000'
        }, {
          name: 'Child education · 2034',
          target: '₹68 L',
          corpus: '₹9.1 L',
          probability: 63,
          sip: '₹18,400'
        }, {
          name: 'Home down-payment · 2029',
          target: '₹35 L',
          corpus: '₹19.6 L',
          probability: 88,
          sip: '₹22,000'
        }]
      }
    },
    followUps: [{
      id: 'sip_size',
      t: 'Size the education SIP for me'
    }, {
      id: 'fix_first',
      t: 'Back to my portfolio score'
    }]
  },
  stress_test: {
    q: 'Stress-test my portfolio',
    agent: 'risk_analyst',
    confidence: 0.93,
    synth: [S('A 2020-style crash takes you down '), S('-31%', 'danger'), S(' — recoverable in about 9 months at your allocation.')],
    prose: "Three historical scenarios applied to your current book. Your drawdown is steep but recovery is well inside your horizon. VaR (95) is ₹2.1L on a one-month view.",
    proseBeginner: "If the market crashed like it did in 2020, your savings could drop about a third for a while — but history says it would bounce back in under a year. Scary in the moment, fine over time given when you need the money.",
    proseTrader: "Scenario shock: COVID-20 −31% / 274d hist recovery, GFC-08 −38%, Taper-13 −14%. Portfolio beta 1.12 amplifies. VaR95 1M = ₹2.1L, max DD −31% vs Nifty −38%.",
    widget: {
      type: 'stress_test',
      data: {
        scenarios: [{
          name: 'COVID crash · 2020',
          drop: -31,
          days: 274
        }, {
          name: 'Global Financial Crisis · 2008',
          drop: -38,
          days: 511
        }, {
          name: 'Taper tantrum · 2013',
          drop: -14,
          days: 96
        }]
      }
    },
    followUps: [{
      id: 'reduce_financials',
      t: 'How do I lower the drawdown?'
    }, {
      id: 'retirement',
      t: 'Does this threaten my goals?'
    }]
  },
  sip_size: {
    q: 'Size a SIP to reach ₹2 Cr',
    agent: 'goal_planner',
    confidence: 0.88,
    synth: [S('A '), S('₹46,500/mo', 'mint'), S(' SIP for 18 years gets you to ₹2 Cr — your current ₹42k leaves a small gap.')],
    prose: "Back-calculated at a 11% assumed CAGR. Bumping your SIP by ₹4,500/mo closes the shortfall; a 10% annual step-up gets there two years sooner.",
    proseBeginner: "To reach ₹2 crore in 18 years, you'd save about ₹46,500 every month. You're already doing ₹42,000 — so just ₹4,500 more a month gets you there. Increasing it a little each year helps even more.",
    proseTrader: "Target-corpus back-calc: FV ₹2Cr, n=216m, assumed 11% CAGR → PMT ₹46.5k/mo. Current ₹42k → ₹4.5k/mo shortfall. 10% annual step-up pulls maturity in by ~24m.",
    widget: {
      type: 'sip_plan',
      data: {
        sip: '₹46,500',
        duration: 216,
        projected: '₹2.04 Cr',
        shortfall: '₹4,500/mo',
        current: '₹42,000'
      }
    },
    followUps: [{
      id: 'retirement',
      t: 'Show all my goals'
    }, {
      id: 'fix_first',
      t: 'Is my portfolio built for this?'
    }]
  },
  // Advisor-mode cross-client query (FR-CHAT-013 / AC-20)
  advisor_rebalance: {
    q: 'Which of my clients needs rebalancing most?',
    agent: 'advisor_book',
    confidence: 0.9,
    advisor: true,
    synth: [S('Three clients are off-target — '), S('Meera Iyer', 'danger'), S(' is the most urgent, 11 points past her drift band.')],
    prose: "Ranked across your 38-client book by drift from each client's stated allocation. Top three shown.",
    widget: {
      type: 'client_book',
      data: {
        clients: [{
          name: 'Meera Iyer',
          value: '₹1.2 Cr',
          drift: '+11 pts',
          risk: 'High',
          flag: 'danger'
        }, {
          name: 'Rohan Desai',
          value: '₹84 L',
          drift: '+7 pts',
          risk: 'Med',
          flag: 'amber'
        }, {
          name: 'Sana Khan',
          value: '₹2.1 Cr',
          drift: '+5 pts',
          risk: 'Med',
          flag: 'amber'
        }]
      }
    },
    followUps: [{
      id: 'advisor_rebalance',
      t: 'Draft a note to Meera'
    }]
  }
};

// fallback when free-typed text matches nothing
const FALLBACK_ID = 'fix_first';

// keyword router for free-typed input (mimics intent_node)
function routeText(text) {
  const q = text.toLowerCase();
  const has = (...ks) => ks.some(k => q.includes(k));
  if (has('tax', 'harvest', 'ltcg', 'loss')) return 'tax_harvest';
  if (has('overlap', 'duplicate', 'same fund')) return 'fund_overlap';
  if (has('compare', 'scorecard', 'best fund')) return 'compare_funds';
  if (has('stock', 'watchlist', 'rsi', 'macd', 'titan', 'buy ')) return 'watch_stocks';
  if (has('sector', 'rotation', 'fii', 'macro', 'nifty', 'market')) return 'sector_rotation';
  if (has('retire', 'goal', 'on track', 'education')) return 'retirement';
  if (has('sip', '2 cr', 'corpus', 'monthly')) return 'sip_size';
  if (has('stress', 'crash', 'drawdown', 'var', 'risk')) return 'stress_test';
  if (has('financ', 'reduce', 'trim', 'rebalance', 'sell', 'allocation')) return 'reduce_financials';
  if (has('client', 'book', 'my clients')) return 'advisor_rebalance';
  return FALLBACK_ID;
}

// ── Suggested-prompt catalog (FR-CHAT-006) — 5 categories ──────────────────
const CATEGORIES = [{
  id: 'portfolio_health',
  label: 'Portfolio health'
}, {
  id: 'performance',
  label: 'Performance'
}, {
  id: 'risk_diversification',
  label: 'Risk & diversification'
}, {
  id: 'tax',
  label: 'Tax'
}, {
  id: 'goal_planning',
  label: 'Goal planning'
}];
const PROMPTS = [{
  id: 'fix_first',
  cat: 'portfolio_health',
  t: "What's the one thing I should fix first?"
}, {
  id: 'fund_overlap',
  cat: 'portfolio_health',
  t: 'Do my mutual funds overlap?'
}, {
  id: 'reduce_financials',
  cat: 'portfolio_health',
  t: 'How do I reduce my financials exposure?'
}, {
  id: 'compare_funds',
  cat: 'performance',
  t: 'Compare my large-cap funds'
}, {
  id: 'watch_stocks',
  cat: 'performance',
  t: 'Which watchlist stocks should I act on?'
}, {
  id: 'stress_test',
  cat: 'risk_diversification',
  t: 'Stress-test my portfolio'
}, {
  id: 'sector_rotation',
  cat: 'risk_diversification',
  t: 'How is sector rotation looking?'
}, {
  id: 'tax_harvest',
  cat: 'tax',
  t: 'Can I harvest any losses before March 31?'
}, {
  id: 'retirement',
  cat: 'goal_planning',
  t: 'Am I on track for retirement?'
}, {
  id: 'sip_size',
  cat: 'goal_planning',
  t: 'Size a SIP to reach ₹2 Cr'
}];

// ── Chat history (FR-CHAT-010) ─────────────────────────────────────────────
const HISTORY = {
  Today: [{
    id: 'h1',
    title: 'Portfolio health · Nov 26',
    active: true
  }, {
    id: 'h2',
    title: 'Should I rebalance financials?'
  }, {
    id: 'h3',
    title: 'Tax loss before March'
  }],
  'This week': [{
    id: 'h4',
    title: 'Mid-cap exposure'
  }, {
    id: 'h5',
    title: 'Reading my CAS'
  }, {
    id: 'h6',
    title: 'Goals · retirement gap'
  }],
  Older: [{
    id: 'h7',
    title: 'First look at my book'
  }, {
    id: 'h8',
    title: 'What is XIRR?'
  }]
};
const PERSONAS = [{
  id: 'balanced',
  label: 'Balanced'
}, {
  id: 'beginner_investor',
  label: 'Beginner'
}, {
  id: 'active_trader',
  label: 'Active trader'
}];
const DISCLAIMER = 'AI-generated for educational purposes. Not SEBI-registered investment advice.';
const USER = {
  name: 'Aarav Kumar',
  initials: 'AK',
  value: '₹24.8 L',
  holdings: 47,
  persona: 'Balanced investor'
};
const ADVISOR = {
  name: 'Priya Nair',
  initials: 'PN',
  value: '38 clients',
  holdings: 0,
  persona: 'MFD · ARN-90214'
};

// Per-persona synthesis headlines — same verdict, different altitude.
// Falls back to scenario.synth when a variant isn't defined.
const SYNTH_VARIANTS = {
  fix_first: {
    beginner_investor: [S('Your money is in '), S('good shape', 'mint'), S(' — but one slice (banks and finance) has grown too big.')],
    active_trader: [S('Composite '), S('86', 'mint'), S(' — the only real drag is a 32% financials tilt plus a 71% fund overlap inflating concentration.')]
  },
  reduce_financials: {
    beginner_investor: [S('Two small sales bring banks down to a '), S('healthier', 'mint'), S(' slice — without touching your winners.')],
    active_trader: [S('Two-leg de-risk pares HDFCBANK + ICICIBANK into the index — net beta 1.12 → '), S('0.98', 'mint'), S('.')]
  },
  tax_harvest: {
    beginner_investor: [S('Three holdings are at a loss — selling now can save you '), S('₹11,520', 'mint'), S(' in tax before March.')],
    active_trader: [S('Three lots offset ₹38.4k of booked STCG — '), S('₹11,520', 'mint'), S(' saved at slab, rebuy +31d.')]
  },
  compare_funds: {
    beginner_investor: [S('Your Parag Parikh fund looks '), S('strongest', 'mint'), S(' — Axis Bluechip is the weak link.')],
    active_trader: [S('PPFAS dominates the V3 scorecard at 14.2% 3Y XIRR — Axis BC '), S('exit score 61', 'danger'), S(' flags it.')]
  },
  watch_stocks: {
    beginner_investor: [S('Two stocks look '), S('good to add', 'mint'), S(', one you might trim — here are the scores.')],
    active_trader: [S('TITAN + TATAMOTORS screen long on the composite; ZOMATO RSI 74 is a '), S('reduce', 'danger'), S('.')]
  },
  sector_rotation: {
    beginner_investor: [S('Money is moving out of banks into '), S('healthcare and energy', 'mint'), S(' — and you\u2019re on the wrong side.')],
    active_trader: [S('1M momentum: FIN \u22122.1%, PHARMA +4.6% — you\u2019re '), S('+8pp financials', 'amber'), S(' vs model.')]
  },
  fund_overlap: {
    beginner_investor: [S('Two of your funds hold mostly the '), S('same companies', 'indigo'), S(' — you\u2019re paying twice for one idea.')],
    active_trader: [S('Axis BC \u2229 Mirae LC = '), S('71%', 'indigo'), S(', top-10 identical — triplicated TER \u2248 1.1%.')]
  },
  retirement: {
    beginner_investor: [S('You reach retirement in '), S('most futures', 'mint'), S(' — but your child-education saving is a little behind.')],
    active_trader: [S('Retirement P(success) '), S('0.81', 'mint'), S(' at current SIP — education underfunded, +\u20b96.4k/mo to hit 0.80.')]
  },
  stress_test: {
    beginner_investor: [S('A 2020-style crash could drop you about a third — but history says it bounces back in '), S('under a year', 'mint'), S('.')],
    active_trader: [S('COVID-20 shock '), S('\u221231%', 'danger'), S(' / 274d, beta 1.12 amplifies — VaR95 1M \u20b92.1L.')]
  },
  sip_size: {
    beginner_investor: [S('Save about \u20b946,500 a month for 18 years and you hit '), S('\u20b92 Cr', 'mint'), S(' — just \u20b94,500 more than now.')],
    active_trader: [S('PMT \u20b946.5k/mo, n=216, 11% CAGR \u2192 FV '), S('\u20b92 Cr', 'mint'), S('; \u20b94.5k/mo shortfall vs current.')]
  }
};

// resolve the right prose for the active persona
function proseFor(sc, persona) {
  if (persona === 'beginner_investor' && sc.proseBeginner) return sc.proseBeginner;
  if (persona === 'active_trader' && sc.proseTrader) return sc.proseTrader;
  return sc.prose;
}

// resolve the right synthesis headline for the active persona
function synthFor(sc, persona, id) {
  const v = SYNTH_VARIANTS[id];
  if (v && v[persona]) return v[persona];
  return sc.synth;
}
Object.assign(window, {
  AGENTS,
  SCENARIOS,
  PROMPTS,
  CATEGORIES,
  HISTORY,
  PERSONAS,
  SYNTH_VARIANTS,
  DISCLAIMER,
  USER,
  ADVISOR,
  FALLBACK_ID,
  routeText,
  proseFor,
  synthFor
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "app/data.jsx", error: String((e && e.message) || e) }); }

// app/desktop.jsx
try { (() => {
// ─── Nivesh Copilot · Desktop chat (NVChatDesktop) ─────────────────────────
const {
  useState: useStateD,
  useRef: useRefD,
  useEffect: useEffectD
} = React;

// ── synthesis headline — 3 layout treatments (the explored dimension) ──
function SynthBlock({
  msg,
  layout,
  streaming
}) {
  const a = window.AGENTS[msg.agent];
  const words = msg.synthWords.slice(0, msg.vSynth);
  const synthEl = words.map((w, i) => /*#__PURE__*/React.createElement("span", {
    key: i,
    style: {
      color: w.a ? `var(--${w.a})` : 'inherit'
    }
  }, w.w));
  const caret = streaming && msg.phase === 'stream_synth' ? /*#__PURE__*/React.createElement("span", {
    className: "nv-caret"
  }) : null;
  if (layout === 'editorial') {
    return /*#__PURE__*/React.createElement("div", {
      style: {
        borderLeft: `2px solid var(--${a.accent})`,
        paddingLeft: 20
      }
    }, /*#__PURE__*/React.createElement("div", {
      className: "nv-mono",
      style: {
        fontSize: 10.5,
        letterSpacing: '.16em',
        textTransform: 'uppercase',
        color: `var(--${a.accent})`,
        marginBottom: 10
      }
    }, a.label), /*#__PURE__*/React.createElement("div", {
      className: "nv-serif",
      style: {
        fontSize: 33,
        lineHeight: 1.16,
        letterSpacing: '-0.02em',
        maxWidth: 760
      }
    }, synthEl, caret));
  }
  if (layout === 'eyebrow') {
    return /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 9,
        marginBottom: 10
      }
    }, /*#__PURE__*/React.createElement("span", {
      className: "nv-mark",
      style: {
        width: 22,
        height: 22,
        fontSize: 13
      }
    }, "\u0928"), /*#__PURE__*/React.createElement("span", {
      className: "nv-mono",
      style: {
        fontSize: 10.5,
        letterSpacing: '.16em',
        textTransform: 'uppercase',
        color: 'var(--ink-3)'
      }
    }, a.label)), /*#__PURE__*/React.createElement("div", {
      className: "nv-serif",
      style: {
        fontSize: 33,
        lineHeight: 1.16,
        letterSpacing: '-0.02em',
        maxWidth: 760
      }
    }, synthEl, caret));
  }
  // default: mark beside headline
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 14
    }
  }, /*#__PURE__*/React.createElement("span", {
    className: "nv-mark",
    style: {
      flex: 'none',
      marginTop: 4
    }
  }, "\u0928"), /*#__PURE__*/React.createElement("div", {
    className: "nv-serif",
    style: {
      fontSize: 32,
      lineHeight: 1.15,
      letterSpacing: '-0.02em',
      maxWidth: 720,
      flex: 1
    }
  }, synthEl, caret));
}
function GroundingWarning() {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 10,
      padding: '10px 14px',
      borderRadius: 10,
      background: 'var(--amber-soft)',
      border: '1px solid var(--amber-line)',
      marginTop: 14
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      color: 'var(--amber)',
      fontSize: 14
    }
  }, "\u26A0"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 13,
      color: 'var(--ink-2)'
    }
  }, "Some figures may not match the latest data \u2014 shown from your last sync."));
}
function FollowUps({
  ups,
  onPick,
  disabled
}) {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexWrap: 'wrap',
      gap: 8,
      marginTop: 16
    }
  }, ups.map(u => /*#__PURE__*/React.createElement("button", {
    key: u.id + u.t,
    disabled: disabled,
    onClick: () => onPick(u),
    style: {
      fontFamily: 'var(--sans)',
      fontSize: 13,
      padding: '8px 14px',
      borderRadius: 999,
      minHeight: 36,
      border: '1px solid var(--line-2)',
      background: 'var(--bg-1)',
      color: 'var(--ink-2)',
      cursor: disabled ? 'default' : 'pointer',
      opacity: disabled ? .5 : 1,
      transition: 'all .15s ease'
    },
    onMouseEnter: e => {
      if (!disabled) e.currentTarget.style.borderColor = 'var(--line-3)';
    },
    onMouseLeave: e => {
      e.currentTarget.style.borderColor = 'var(--line-2)';
    }
  }, u.t)));
}

// the assistant turn — handles every phase
function AssistantTurn({
  msg,
  layout,
  streaming,
  onPick,
  onRetry
}) {
  if (msg.phase === 'routing') return /*#__PURE__*/React.createElement(window.NVTyping, {
    agent: msg.agent
  });
  if (msg.phase === 'error') {
    return /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        gap: 14
      }
    }, /*#__PURE__*/React.createElement("span", {
      className: "nv-mark",
      style: {
        flex: 'none',
        marginTop: 2
      }
    }, "\u0928"), /*#__PURE__*/React.createElement("div", {
      style: {
        padding: '16px 18px',
        borderRadius: 12,
        background: 'var(--danger-soft)',
        border: '1px solid var(--danger-line)',
        maxWidth: 460
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 14.5,
        fontWeight: 500,
        color: 'var(--ink)'
      }
    }, "Something went wrong \u2014 the copilot couldn't complete that."), /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 13,
        color: 'var(--ink-3)',
        marginTop: 4
      }
    }, "The NIDP stream dropped mid-response."), /*#__PURE__*/React.createElement("button", {
      className: "nv-btn",
      onClick: onRetry,
      style: {
        marginTop: 12,
        padding: '7px 14px',
        fontSize: 12.5
      }
    }, "\u21BB Retry")));
  }
  if (msg.phase === 'no_portfolio') {
    return /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        gap: 14
      }
    }, /*#__PURE__*/React.createElement("span", {
      className: "nv-mark",
      style: {
        flex: 'none',
        marginTop: 2
      }
    }, "\u0928"), /*#__PURE__*/React.createElement("div", {
      className: "nv-card",
      style: {
        padding: '24px 26px',
        maxWidth: 520
      }
    }, /*#__PURE__*/React.createElement("div", {
      className: "nv-serif",
      style: {
        fontSize: 24,
        letterSpacing: '-0.02em'
      }
    }, "I can't read a portfolio yet."), /*#__PURE__*/React.createElement("p", {
      style: {
        fontSize: 14,
        color: 'var(--ink-2)',
        lineHeight: 1.6,
        marginTop: 10
      }
    }, "Connect your holdings and I'll score them, rank what to fix, and ground every answer in your real data \u2014 not generic advice."), /*#__PURE__*/React.createElement("button", {
      className: "nv-btn nv-btn-primary",
      style: {
        marginTop: 16
      }
    }, "\uFF0B Connect your portfolio")));
  }
  const done = msg.phase === 'done';
  const proseWords = msg.proseWords.slice(0, msg.vProse).map(w => w.w).join('');
  const showProse = ['stream_prose', 'widget_skeleton', 'done'].includes(msg.phase);
  const showWidget = msg.phase === 'widget_skeleton' || done;
  return /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement(SynthBlock, {
    msg: msg,
    layout: layout,
    streaming: streaming
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      paddingLeft: layout === 'mark' ? 42 : layout === 'editorial' ? 22 : 0,
      marginTop: 14
    }
  }, showProse && /*#__PURE__*/React.createElement("p", {
    "aria-live": "polite",
    style: {
      fontSize: 15,
      color: 'var(--ink-2)',
      lineHeight: 1.6,
      maxWidth: 680,
      margin: 0
    }
  }, proseWords, msg.cached && done && /*#__PURE__*/React.createElement("span", {
    className: "nv-mono",
    style: {
      fontSize: 10,
      color: 'var(--amber)',
      marginLeft: 8,
      letterSpacing: '.08em',
      verticalAlign: 'middle'
    }
  }, "[CACHED]"), streaming && msg.phase === 'stream_prose' && /*#__PURE__*/React.createElement("span", {
    className: "nv-caret"
  })), showWidget && /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 18
    }
  }, msg.phase === 'widget_skeleton' ? /*#__PURE__*/React.createElement(window.NVWidgetSkeleton, null) : /*#__PURE__*/React.createElement(window.NVWidget, {
    type: msg.widget.type,
    data: msg.widget.data,
    onPick: sid => sid && onPick({
      id: sid
    })
  })), done && !msg.grounding && /*#__PURE__*/React.createElement(GroundingWarning, null), done && /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement(FollowUps, {
    ups: msg.followUps,
    onPick: u => onPick({
      id: u.id,
      text: u.t
    }),
    disabled: streaming
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 14,
      marginTop: 16
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "nv-hr",
    style: {
      flex: 1
    }
  }), /*#__PURE__*/React.createElement(window.NVFeedback, null)))));
}

// ── welcome / empty state ──
function Welcome({
  cfg,
  onPick,
  activeCat
}) {
  const u = cfg.advisor ? window.ADVISOR : window.USER;
  const prompts = window.PROMPTS.filter(p => !activeCat || p.cat === activeCat).slice(0, 6);
  return /*#__PURE__*/React.createElement("div", {
    style: {
      maxWidth: 760,
      margin: '0 auto',
      width: '100%',
      paddingTop: 40
    }
  }, /*#__PURE__*/React.createElement("span", {
    className: "nv-mark",
    style: {
      width: 40,
      height: 40,
      fontSize: 24,
      borderRadius: 12
    }
  }, "\u0928"), /*#__PURE__*/React.createElement("div", {
    className: "nv-serif",
    style: {
      fontSize: 38,
      letterSpacing: '-0.02em',
      lineHeight: 1.1,
      marginTop: 22
    }
  }, cfg.advisor ? /*#__PURE__*/React.createElement(React.Fragment, null, "Good morning, ", u.name.split(' ')[0], ". Ask about ", /*#__PURE__*/React.createElement("span", {
    style: {
      color: 'var(--indigo)'
    }
  }, "your book"), ".") : /*#__PURE__*/React.createElement(React.Fragment, null, "Good morning, ", u.name.split(' ')[0], ". Let's read your ", /*#__PURE__*/React.createElement("span", {
    style: {
      color: 'var(--mint)'
    }
  }, "portfolio"), ".")), /*#__PURE__*/React.createElement("p", {
    style: {
      fontSize: 15,
      color: 'var(--ink-2)',
      lineHeight: 1.6,
      marginTop: 12,
      maxWidth: 560
    }
  }, cfg.advisor ? '38 clients · ₹46 Cr AUM. I can rank drift, flag risk, and draft client notes — grounded in NIDP.' : `${u.value} across ${u.holdings} holdings · ${u.persona}. I'll ground every answer in your real data.`), /*#__PURE__*/React.createElement(window.NVEyebrow, {
    style: {
      marginTop: 34,
      marginBottom: 14
    }
  }, activeCat ? `${window.CATEGORIES.find(c => c.id === activeCat).label} · suggested` : 'Suggested prompts'), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'grid',
      gridTemplateColumns: '1fr 1fr',
      gap: 10
    }
  }, (cfg.advisor ? [{
    id: 'advisor_rebalance',
    t: 'Which client needs rebalancing most?'
  }] : prompts).map(p => /*#__PURE__*/React.createElement("button", {
    key: p.id,
    onClick: () => onPick({
      id: p.id,
      text: p.t
    }),
    style: {
      textAlign: 'left',
      fontFamily: 'var(--sans)',
      fontSize: 14.5,
      color: 'var(--ink)',
      cursor: 'pointer',
      padding: '15px 17px',
      borderRadius: 12,
      background: 'var(--bg-1)',
      border: '1px solid var(--line)',
      boxShadow: 'var(--shadow-card)',
      transition: 'all .15s ease',
      display: 'flex',
      alignItems: 'center',
      gap: 10,
      minHeight: 56
    },
    onMouseEnter: e => {
      e.currentTarget.style.borderColor = 'var(--line-3)';
    },
    onMouseLeave: e => {
      e.currentTarget.style.borderColor = 'var(--line)';
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      flex: 1
    }
  }, p.t), /*#__PURE__*/React.createElement("span", {
    style: {
      color: 'var(--ink-4)',
      fontSize: 18
    }
  }, "\u203A")))));
}

// ── status bar ──
function StatusBar({
  cfg
}) {
  const u = cfg.advisor ? window.ADVISOR : window.USER;
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 10,
      padding: '16px 0',
      flexWrap: 'wrap'
    }
  }, cfg.advisor && /*#__PURE__*/React.createElement("span", {
    className: "nv-pill nv-pill-indigo"
  }, /*#__PURE__*/React.createElement("span", {
    className: "nv-dot",
    style: {
      background: 'var(--indigo)'
    }
  }), "CLIENT BOOK"), cfg.nidp ? /*#__PURE__*/React.createElement("span", {
    className: "nv-pill nv-pill-mint"
  }, /*#__PURE__*/React.createElement("span", {
    className: "nv-dot",
    style: {
      background: 'var(--mint)'
    }
  }), "NIDP CONNECTED") : /*#__PURE__*/React.createElement("span", {
    className: "nv-pill nv-pill-amber"
  }, /*#__PURE__*/React.createElement("span", {
    className: "nv-dot",
    style: {
      background: 'var(--amber)'
    }
  }), "NIDP DISCONNECTED"), /*#__PURE__*/React.createElement("span", {
    className: "nv-mono",
    style: {
      fontSize: 11,
      color: 'var(--ink-3)',
      letterSpacing: '.04em'
    }
  }, cfg.nidp ? `last sync · 2m ago · ${u.holdings || 47} holdings` : 'using last sync · 41m ago'), /*#__PURE__*/React.createElement("span", {
    style: {
      marginLeft: 'auto',
      display: 'flex',
      gap: 6
    }
  }, /*#__PURE__*/React.createElement("button", {
    className: "nv-btn",
    style: {
      padding: '6px 11px',
      fontSize: 12
    }
  }, cfg.nidp ? 'Re-sync' : 'Reconnect'), /*#__PURE__*/React.createElement("button", {
    className: "nv-btn",
    style: {
      padding: '6px 11px',
      fontSize: 12
    }
  }, "Share")));
}

// ── composer ──
function Composer({
  cfg,
  streaming,
  onSend,
  activeCat,
  setCat
}) {
  const [text, setText] = useStateD('');
  const ref = useRefD(null);
  const over = text.length > 400;
  const send = () => {
    const v = text.trim();
    if (!v || streaming || v.length > 500) return;
    onSend({
      text: v
    });
    setText('');
    if (ref.current) ref.current.style.height = 'auto';
  };
  return /*#__PURE__*/React.createElement("div", {
    style: {
      maxWidth: 980,
      margin: '0 auto',
      width: '100%'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 6,
      marginBottom: 10,
      flexWrap: 'wrap'
    }
  }, window.CATEGORIES.map(c => /*#__PURE__*/React.createElement("button", {
    key: c.id,
    onClick: () => setCat(activeCat === c.id ? null : c.id),
    className: "nv-mono",
    style: {
      fontSize: 10.5,
      letterSpacing: '.06em',
      textTransform: 'uppercase',
      padding: '6px 11px',
      borderRadius: 999,
      minHeight: 32,
      cursor: 'pointer',
      transition: 'all .15s ease',
      border: `1px solid ${activeCat === c.id ? 'var(--mint-line)' : 'var(--line-2)'}`,
      background: activeCat === c.id ? 'var(--mint-soft)' : 'transparent',
      color: activeCat === c.id ? 'var(--mint)' : 'var(--ink-3)'
    }
  }, c.label))), /*#__PURE__*/React.createElement("div", {
    className: "nv-glass",
    style: {
      padding: '12px 14px 12px 16px',
      display: 'flex',
      alignItems: 'flex-end',
      gap: 12,
      borderRadius: 16
    }
  }, /*#__PURE__*/React.createElement("button", {
    title: "Attach (coming soon)",
    style: {
      color: 'var(--ink-3)',
      fontSize: 20,
      background: 'none',
      border: 0,
      cursor: 'not-allowed',
      padding: '4px 2px',
      lineHeight: 1
    }
  }, "\uFF0B"), /*#__PURE__*/React.createElement("textarea", {
    ref: ref,
    rows: 1,
    value: text,
    maxLength: 520,
    onChange: e => {
      setText(e.target.value);
      e.target.style.height = 'auto';
      e.target.style.height = Math.min(120, e.target.scrollHeight) + 'px';
    },
    onKeyDown: e => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        send();
      }
    },
    placeholder: cfg.advisor ? 'Ask about your clients…' : 'Ask anything · "what if I sell HDFC Bank?"',
    style: {
      flex: 1,
      resize: 'none',
      background: 'transparent',
      border: 0,
      outline: 'none',
      color: 'var(--ink)',
      fontFamily: 'var(--sans)',
      fontSize: 14.5,
      lineHeight: 1.5,
      maxHeight: 120,
      paddingTop: 7
    }
  }), over && /*#__PURE__*/React.createElement("span", {
    className: "nv-mono",
    style: {
      fontSize: 10.5,
      color: text.length > 500 ? 'var(--danger)' : 'var(--ink-3)'
    }
  }, text.length, "/500"), /*#__PURE__*/React.createElement("button", {
    onClick: send,
    disabled: streaming || !text.trim(),
    className: "nv-btn nv-btn-primary",
    style: {
      padding: '9px 14px',
      fontSize: 13,
      opacity: streaming || !text.trim() ? .5 : 1,
      cursor: streaming || !text.trim() ? 'default' : 'pointer'
    }
  }, "\u2197 Send")), /*#__PURE__*/React.createElement("div", {
    className: "nv-mono",
    style: {
      fontSize: 9.5,
      color: 'var(--ink-4)',
      textAlign: 'center',
      marginTop: 9,
      letterSpacing: '.04em'
    }
  }, window.DISCLAIMER));
}
function NVChatDesktop({
  cfg
}) {
  const {
    messages,
    streaming,
    submit,
    retry,
    newSession,
    seed
  } = window.useCopilot();
  const [activeCat, setCat] = useStateD(null);
  const threadRef = useRefD(null);
  useEffectD(() => {
    if (!cfg.seedId) newSession();
  }, [cfg.advisor, cfg.portfolio]);
  useEffectD(() => {
    if (cfg.seedId) seed({
      id: cfg.seedId
    }, {
      persona: cfg.persona,
      nidpDown: !cfg.nidp,
      noPortfolio: !cfg.portfolio,
      forceError: cfg.seedError
    });
  }, [cfg.seedId, cfg.persona, cfg.nidp, cfg.portfolio, cfg.seedError, cfg.advisor, cfg.theme]);
  useEffectD(() => {
    if (cfg.seedId) return; // export harness controls scroll
    const el = threadRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages]);
  const handle = req => submit(req, {
    persona: cfg.persona,
    nidpDown: !cfg.nidp,
    noPortfolio: !cfg.portfolio,
    forceError: cfg.forceError
  });
  const u = cfg.advisor ? window.ADVISOR : window.USER;
  const empty = messages.length === 0;
  return /*#__PURE__*/React.createElement("div", {
    className: "nv-frame",
    style: {
      width: '100%',
      height: '100%',
      display: 'flex',
      overflow: 'hidden'
    }
  }, /*#__PURE__*/React.createElement("aside", {
    style: {
      width: 240,
      borderRight: '1px solid var(--line)',
      padding: '20px 14px',
      display: 'flex',
      flexDirection: 'column',
      gap: 2,
      background: 'var(--bg-0)',
      flex: 'none'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 10,
      padding: '4px 8px 16px'
    }
  }, /*#__PURE__*/React.createElement("span", {
    className: "nv-mark"
  }, "\u0928"), /*#__PURE__*/React.createElement("span", {
    className: "nv-serif",
    style: {
      fontSize: 18
    }
  }, "Nivesh")), /*#__PURE__*/React.createElement("button", {
    onClick: newSession,
    className: "nv-btn",
    style: {
      justifyContent: 'flex-start',
      padding: '9px 12px',
      fontSize: 13,
      marginBottom: 8,
      whiteSpace: 'nowrap'
    }
  }, "\uFF0B New chat"), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      overflowY: 'auto',
      margin: '0 -4px',
      padding: '0 4px'
    }
  }, Object.entries(window.HISTORY).map(([grp, items]) => /*#__PURE__*/React.createElement("div", {
    key: grp
  }, /*#__PURE__*/React.createElement(window.NVEyebrow, {
    style: {
      fontSize: 9.5,
      padding: '14px 10px 6px'
    }
  }, grp), items.map(it => /*#__PURE__*/React.createElement("div", {
    key: it.id,
    className: "nv-hist",
    style: {
      padding: '9px 12px',
      fontSize: 13,
      borderRadius: 8,
      cursor: 'pointer',
      color: it.active && !empty ? 'var(--ink)' : 'var(--ink-2)',
      background: it.active && !empty ? 'var(--bg-2)' : 'transparent',
      border: `1px solid ${it.active && !empty ? 'var(--line)' : 'transparent'}`,
      whiteSpace: 'nowrap',
      overflow: 'hidden',
      textOverflow: 'ellipsis'
    }
  }, it.title))))), /*#__PURE__*/React.createElement("div", {
    style: {
      padding: '12px 8px 4px',
      borderTop: '1px solid var(--line)',
      display: 'flex',
      alignItems: 'center',
      gap: 10,
      marginTop: 8
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      width: 30,
      height: 30,
      borderRadius: 8,
      background: 'var(--bg-3)',
      display: 'grid',
      placeItems: 'center',
      fontFamily: 'var(--mono)',
      fontSize: 11,
      color: 'var(--ink-2)',
      flex: 'none'
    }
  }, u.initials), /*#__PURE__*/React.createElement("div", {
    style: {
      minWidth: 0
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 12.5,
      fontWeight: 500,
      whiteSpace: 'nowrap',
      overflow: 'hidden',
      textOverflow: 'ellipsis'
    }
  }, u.name), /*#__PURE__*/React.createElement("div", {
    className: "nv-mono",
    style: {
      fontSize: 9.5,
      color: 'var(--ink-3)'
    }
  }, u.value, " \xB7 ", cfg.advisor ? 'MFD' : 'Verified')))), /*#__PURE__*/React.createElement("main", {
    style: {
      flex: 1,
      display: 'flex',
      flexDirection: 'column',
      minWidth: 0
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      padding: '0 56px',
      borderBottom: '1px solid var(--line)',
      flex: 'none'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      maxWidth: 980,
      margin: '0 auto'
    }
  }, /*#__PURE__*/React.createElement(StatusBar, {
    cfg: cfg
  }))), /*#__PURE__*/React.createElement("div", {
    ref: threadRef,
    style: {
      flex: 1,
      overflowY: 'auto',
      padding: '8px 56px 28px'
    }
  }, empty ? /*#__PURE__*/React.createElement(Welcome, {
    cfg: cfg,
    onPick: handle,
    activeCat: activeCat
  }) : /*#__PURE__*/React.createElement("div", {
    style: {
      maxWidth: 980,
      margin: '0 auto',
      display: 'flex',
      flexDirection: 'column',
      gap: cfg.density === 'compact' ? 20 : 30,
      paddingTop: 18
    }
  }, messages.map(m => m.kind === 'user' ? /*#__PURE__*/React.createElement("div", {
    key: m.id,
    style: {
      alignSelf: 'flex-end',
      maxWidth: 540,
      padding: '12px 18px',
      background: 'var(--bg-2)',
      border: '1px solid var(--line)',
      borderRadius: '18px 18px 4px 18px'
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 14.5
    }
  }, m.text)) : /*#__PURE__*/React.createElement(AssistantTurn, {
    key: m.id,
    msg: m,
    layout: cfg.synthLayout,
    streaming: streaming,
    onPick: handle,
    onRetry: () => retry({
      persona: cfg.persona,
      nidpDown: !cfg.nidp
    })
  })))), /*#__PURE__*/React.createElement("div", {
    style: {
      padding: '14px 56px 18px',
      flex: 'none'
    }
  }, /*#__PURE__*/React.createElement(Composer, {
    cfg: cfg,
    streaming: streaming,
    onSend: handle,
    activeCat: activeCat,
    setCat: setCat
  }))));
}
Object.assign(window, {
  NVChatDesktop
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "app/desktop.jsx", error: String((e && e.message) || e) }); }

// app/engine.jsx
try { (() => {
// ─── Nivesh Copilot · streaming engine (useCopilot) ────────────────────────
// Drives the scripted SSE-like flow: route → token stream → widget → done.
const {
  useState: useStateE,
  useRef: useRefE,
  useCallback: useCbE,
  useEffect: useEffectE
} = React;
let _mid = 0;
const nextId = () => `m${++_mid}`;

// segment[] {t,a} → word[] {w, a}
function flattenSynth(segs) {
  const out = [];
  segs.forEach(s => {
    s.t.split(/(\s+)/).forEach(tok => {
      if (tok.length) out.push({
        w: tok,
        a: s.a
      });
    });
  });
  return out;
}
const flattenProse = txt => txt.split(/(\s+)/).filter(t => t.length).map(w => ({
  w,
  a: null
}));
function useCopilot() {
  const [messages, setMessages] = useStateE([]);
  const [streaming, setStreaming] = useStateE(false);
  const timers = useRefE([]);
  const lastReq = useRefE(null);
  const clearTimers = () => {
    timers.current.forEach(clearTimeout);
    timers.current = [];
  };
  useEffectE(() => clearTimers, []);
  const after = (ms, fn) => {
    const id = setTimeout(fn, ms);
    timers.current.push(id);
    return id;
  };

  // update the streaming (last) assistant message
  const patchLast = patch => setMessages(ms => {
    const i = ms.length - 1;
    if (i < 0) return ms;
    const next = ms.slice();
    next[i] = {
      ...next[i],
      ...(typeof patch === 'function' ? patch(next[i]) : patch)
    };
    return next;
  });
  const newSession = useCbE(() => {
    clearTimers();
    setStreaming(false);
    setMessages([]);
  }, []);

  // opts: { persona, nidpDown, noPortfolio, forceError }
  const submit = useCbE((req, opts = {}) => {
    if (streaming) return;
    const {
      text,
      id
    } = req;
    const key = id || window.routeText(text);
    const sc = window.SCENARIOS[key];
    const display = text || sc && sc.q || '';
    lastReq.current = {
      req,
      opts
    };

    // user bubble
    setMessages(ms => [...ms, {
      kind: 'user',
      id: nextId(),
      text: display
    }]);

    // ── no-portfolio guard (AC-16)
    if (opts.noPortfolio) {
      setStreaming(true);
      after(650, () => {
        setMessages(ms => [...ms, {
          kind: 'assistant',
          id: nextId(),
          phase: 'no_portfolio',
          agent: 'portfolio_analyst',
          confidence: 1
        }]);
        setStreaming(false);
      });
      return;
    }

    // ── forced error (AC-18 retry path)
    if (opts.forceError) {
      setStreaming(true);
      after(900, () => {
        setMessages(ms => [...ms, {
          kind: 'assistant',
          id: nextId(),
          phase: 'error',
          agent: sc.agent,
          confidence: sc.confidence
        }]);
        setStreaming(false);
      });
      return;
    }
    const synthWords = flattenSynth(window.synthFor(sc, opts.persona, key));
    const proseWords = flattenProse(window.proseFor(sc, opts.persona));
    const grounding = opts.nidpDown ? false : sc.grounding !== false;

    // assistant placeholder — routing
    const aId = nextId();
    setStreaming(true);
    setMessages(ms => [...ms, {
      kind: 'assistant',
      id: aId,
      phase: 'routing',
      agent: sc.agent,
      confidence: sc.confidence,
      synthWords,
      proseWords,
      vSynth: 0,
      vProse: 0,
      widget: sc.widget,
      followUps: sc.followUps || [],
      grounding,
      cached: !!opts.nidpDown,
      disclaimer: window.DISCLAIMER,
      scenarioId: key
    }]);

    // route → stream
    after(820, () => {
      patchLast({
        phase: 'stream_synth'
      });
      let i = 0;
      const tickSynth = () => {
        i += 1;
        patchLast({
          vSynth: i
        });
        if (i < synthWords.length) after(48, tickSynth);else after(180, startProse);
      };
      const startProse = () => {
        patchLast({
          phase: 'stream_prose'
        });
        let j = 0;
        const tickProse = () => {
          j += 1;
          patchLast({
            vProse: j
          });
          if (j < proseWords.length) after(22, tickProse);else after(160, afterProse);
        };
        tickProse();
      };
      const afterProse = () => {
        if (sc.widget && sc.widget.type !== 'none') {
          patchLast({
            phase: 'widget_skeleton'
          });
          after(620, () => {
            patchLast({
              phase: 'done'
            });
            setStreaming(false);
          });
        } else {
          patchLast({
            phase: 'done'
          });
          setStreaming(false);
        }
      };
      tickSynth();
    });
  }, [streaming]);

  // retry — drop trailing error + its user bubble, resend
  const retry = useCbE((opts = {}) => {
    if (!lastReq.current) return;
    setMessages(ms => {
      const out = ms.slice();
      if (out.length && out[out.length - 1].phase === 'error') out.pop();
      if (out.length && out[out.length - 1].kind === 'user') out.pop();
      return out;
    });
    const {
      req
    } = lastReq.current;
    after(60, () => submit(req, {
      ...opts,
      forceError: false
    }));
  }, [submit]);

  // instant render of a finished turn (no animation) — used by the export harness
  const seed = useCbE((req, opts = {}) => {
    clearTimers();
    setStreaming(false);
    const {
      text,
      id
    } = req;
    const key = id || window.routeText(text);
    const sc = window.SCENARIOS[key];
    const display = text || sc && sc.q || '';
    const msgs = [{
      kind: 'user',
      id: nextId(),
      text: display
    }];
    if (opts.noPortfolio) {
      msgs.push({
        kind: 'assistant',
        id: nextId(),
        phase: 'no_portfolio',
        agent: 'portfolio_analyst',
        confidence: 1
      });
    } else if (opts.forceError) {
      msgs.push({
        kind: 'assistant',
        id: nextId(),
        phase: 'error',
        agent: sc.agent,
        confidence: sc.confidence
      });
    } else {
      const synthWords = flattenSynth(window.synthFor(sc, opts.persona, key));
      const proseWords = flattenProse(window.proseFor(sc, opts.persona));
      msgs.push({
        kind: 'assistant',
        id: nextId(),
        phase: 'done',
        agent: sc.agent,
        confidence: sc.confidence,
        synthWords,
        proseWords,
        vSynth: synthWords.length,
        vProse: proseWords.length,
        widget: sc.widget,
        followUps: sc.followUps || [],
        grounding: opts.nidpDown ? false : sc.grounding !== false,
        cached: !!opts.nidpDown,
        disclaimer: window.DISCLAIMER,
        scenarioId: key
      });
    }
    setMessages(msgs);
  }, []);
  return {
    messages,
    streaming,
    submit,
    retry,
    newSession,
    seed
  };
}
Object.assign(window, {
  useCopilot
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "app/engine.jsx", error: String((e && e.message) || e) }); }

// app/mobile.jsx
try { (() => {
// ─── Nivesh Copilot · Mobile chat (NVChatMobile) ───────────────────────────
const {
  useState: useStateM,
  useRef: useRefM,
  useEffect: useEffectM
} = React;
function MobileTurn({
  msg,
  streaming,
  onPick,
  onRetry
}) {
  const a = window.AGENTS[msg.agent];
  if (msg.phase === 'routing') {
    return /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        gap: 10,
        alignItems: 'center'
      }
    }, /*#__PURE__*/React.createElement("span", {
      className: "nv-mark",
      style: {
        width: 26,
        height: 26,
        fontSize: 15,
        flex: 'none'
      }
    }, "\u0928"), /*#__PURE__*/React.createElement("span", {
      style: {
        display: 'inline-flex',
        gap: 4
      }
    }, [0, 1, 2].map(i => /*#__PURE__*/React.createElement("span", {
      key: i,
      style: {
        width: 6,
        height: 6,
        borderRadius: '50%',
        background: `var(--${a.accent})`,
        animation: `nvpulse 1.1s ${i * 0.18}s infinite ease-in-out`
      }
    }))), /*#__PURE__*/React.createElement("span", {
      className: "nv-mono",
      style: {
        fontSize: 10,
        letterSpacing: '.08em',
        textTransform: 'uppercase',
        color: `var(--${a.accent})`
      }
    }, a.label));
  }
  if (msg.phase === 'error') {
    return /*#__PURE__*/React.createElement("div", {
      style: {
        padding: '14px 16px',
        borderRadius: 12,
        background: 'var(--danger-soft)',
        border: '1px solid var(--danger-line)'
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 13.5,
        fontWeight: 500
      }
    }, "Something went wrong."), /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 12,
        color: 'var(--ink-3)',
        marginTop: 3
      }
    }, "The stream dropped mid-response."), /*#__PURE__*/React.createElement("button", {
      className: "nv-btn",
      onClick: onRetry,
      style: {
        marginTop: 10,
        padding: '7px 13px',
        fontSize: 12
      }
    }, "\u21BB Retry"));
  }
  if (msg.phase === 'no_portfolio') {
    return /*#__PURE__*/React.createElement("div", {
      className: "nv-card",
      style: {
        padding: '18px 18px'
      }
    }, /*#__PURE__*/React.createElement("div", {
      className: "nv-serif",
      style: {
        fontSize: 20,
        letterSpacing: '-0.02em'
      }
    }, "No portfolio yet."), /*#__PURE__*/React.createElement("p", {
      style: {
        fontSize: 13,
        color: 'var(--ink-2)',
        lineHeight: 1.55,
        marginTop: 8
      }
    }, "Connect your holdings and I'll ground every answer in your real data."), /*#__PURE__*/React.createElement("button", {
      className: "nv-btn nv-btn-primary",
      style: {
        marginTop: 12,
        fontSize: 13,
        width: '100%',
        justifyContent: 'center'
      }
    }, "\uFF0B Connect portfolio"));
  }
  const done = msg.phase === 'done';
  const synthEl = msg.synthWords.slice(0, msg.vSynth).map((w, i) => /*#__PURE__*/React.createElement("span", {
    key: i,
    style: {
      color: w.a ? `var(--${w.a})` : 'inherit'
    }
  }, w.w));
  const proseTxt = msg.proseWords.slice(0, msg.vProse).map(w => w.w).join('');
  const showProse = ['stream_prose', 'widget_skeleton', 'done'].includes(msg.phase);
  const showWidget = msg.phase === 'widget_skeleton' || done;
  return /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 10
    }
  }, /*#__PURE__*/React.createElement("span", {
    className: "nv-mark",
    style: {
      width: 26,
      height: 26,
      fontSize: 15,
      flex: 'none',
      marginTop: 2
    }
  }, "\u0928"), /*#__PURE__*/React.createElement("div", {
    className: "nv-serif",
    style: {
      fontSize: 22,
      lineHeight: 1.18,
      letterSpacing: '-0.02em',
      flex: 1
    }
  }, synthEl, streaming && msg.phase === 'stream_synth' && /*#__PURE__*/React.createElement("span", {
    className: "nv-caret"
  }))), /*#__PURE__*/React.createElement("div", {
    style: {
      paddingLeft: 36,
      marginTop: 10
    }
  }, showProse && /*#__PURE__*/React.createElement("p", {
    "aria-live": "polite",
    style: {
      fontSize: 13.5,
      color: 'var(--ink-2)',
      lineHeight: 1.55,
      margin: 0
    }
  }, proseTxt, msg.cached && done && /*#__PURE__*/React.createElement("span", {
    className: "nv-mono",
    style: {
      fontSize: 9,
      color: 'var(--amber)',
      marginLeft: 6,
      letterSpacing: '.06em'
    }
  }, "[CACHED]"), streaming && msg.phase === 'stream_prose' && /*#__PURE__*/React.createElement("span", {
    className: "nv-caret"
  })), showWidget && /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 14
    }
  }, msg.phase === 'widget_skeleton' ? /*#__PURE__*/React.createElement(window.NVWidgetSkeleton, null) : /*#__PURE__*/React.createElement(window.NVWidget, {
    type: msg.widget.type,
    data: msg.widget.data,
    onPick: sid => sid && onPick({
      id: sid
    })
  })), done && !msg.grounding && /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 8,
      alignItems: 'center',
      padding: '9px 12px',
      borderRadius: 10,
      background: 'var(--amber-soft)',
      border: '1px solid var(--amber-line)',
      marginTop: 12
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      color: 'var(--amber)'
    }
  }, "\u26A0"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 12,
      color: 'var(--ink-2)'
    }
  }, "Figures may not match latest data.")), done && /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexWrap: 'wrap',
      gap: 7,
      marginTop: 14
    }
  }, msg.followUps.map(u => /*#__PURE__*/React.createElement("button", {
    key: u.id + u.t,
    disabled: streaming,
    onClick: () => onPick({
      id: u.id,
      text: u.t
    }),
    style: {
      fontFamily: 'var(--sans)',
      fontSize: 12,
      padding: '8px 12px',
      borderRadius: 999,
      minHeight: 36,
      border: '1px solid var(--line-2)',
      background: 'var(--bg-1)',
      color: 'var(--ink-2)',
      cursor: 'pointer'
    }
  }, u.t))), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 12,
      marginTop: 12
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "nv-hr",
    style: {
      flex: 1
    }
  }), /*#__PURE__*/React.createElement(window.NVFeedback, {
    compact: true
  })))));
}
function NVChatMobile({
  cfg
}) {
  const {
    messages,
    streaming,
    submit,
    retry,
    newSession,
    seed
  } = window.useCopilot();
  const [text, setText] = useStateM('');
  const [sheet, setSheet] = useStateM(false);
  const threadRef = useRefM(null);
  const u = cfg.advisor ? window.ADVISOR : window.USER;
  useEffectM(() => {
    if (!cfg.seedId) newSession();
  }, [cfg.advisor, cfg.portfolio]);
  useEffectM(() => {
    if (cfg.seedId) seed({
      id: cfg.seedId
    }, {
      persona: cfg.persona,
      nidpDown: !cfg.nidp,
      noPortfolio: !cfg.portfolio,
      forceError: cfg.seedError
    });
  }, [cfg.seedId, cfg.persona, cfg.nidp, cfg.portfolio, cfg.seedError, cfg.advisor, cfg.theme]);
  useEffectM(() => {
    if (cfg.seedId) return;
    const el = threadRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages]);
  const handle = req => submit(req, {
    persona: cfg.persona,
    nidpDown: !cfg.nidp,
    noPortfolio: !cfg.portfolio,
    forceError: cfg.forceError
  });
  const send = () => {
    const v = text.trim();
    if (!v || streaming) return;
    handle({
      text: v
    });
    setText('');
  };
  const empty = messages.length === 0;
  const prompts = window.PROMPTS.slice(0, 4);
  return /*#__PURE__*/React.createElement("div", {
    className: "nv-frame",
    style: {
      width: '100%',
      height: '100%',
      overflow: 'hidden',
      display: 'flex',
      flexDirection: 'column'
    }
  }, /*#__PURE__*/React.createElement("span", {
    className: "nv-notch"
  }), /*#__PURE__*/React.createElement("div", {
    className: "nv-statusbar"
  }, /*#__PURE__*/React.createElement("span", null, "9:41"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 12
    }
  }, "\u25CF \u25CF \u25CF")), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      padding: '6px 18px 12px',
      gap: 10,
      flex: 'none'
    }
  }, /*#__PURE__*/React.createElement("button", {
    onClick: () => setSheet(true),
    style: {
      color: 'var(--ink-2)',
      fontSize: 20,
      background: 'none',
      border: 0,
      cursor: 'pointer',
      padding: 0
    }
  }, "\u2261"), /*#__PURE__*/React.createElement("span", {
    className: "nv-serif",
    style: {
      fontSize: 17
    }
  }, "Copilot"), cfg.nidp ? /*#__PURE__*/React.createElement("span", {
    className: "nv-pill nv-pill-mint",
    style: {
      marginLeft: 'auto',
      fontSize: 9
    }
  }, /*#__PURE__*/React.createElement("span", {
    className: "nv-dot",
    style: {
      background: 'var(--mint)'
    }
  }), "LIVE") : /*#__PURE__*/React.createElement("span", {
    className: "nv-pill nv-pill-amber",
    style: {
      marginLeft: 'auto',
      fontSize: 9
    }
  }, /*#__PURE__*/React.createElement("span", {
    className: "nv-dot",
    style: {
      background: 'var(--amber)'
    }
  }), "CACHED")), /*#__PURE__*/React.createElement("div", {
    ref: threadRef,
    style: {
      flex: 1,
      overflowY: 'auto',
      padding: '4px 16px 12px'
    }
  }, empty ? /*#__PURE__*/React.createElement("div", {
    style: {
      paddingTop: 12
    }
  }, /*#__PURE__*/React.createElement("span", {
    className: "nv-mark",
    style: {
      width: 34,
      height: 34,
      fontSize: 20,
      borderRadius: 11
    }
  }, "\u0928"), /*#__PURE__*/React.createElement("div", {
    className: "nv-serif",
    style: {
      fontSize: 26,
      letterSpacing: '-0.02em',
      lineHeight: 1.14,
      marginTop: 14
    }
  }, "Let's read your ", /*#__PURE__*/React.createElement("span", {
    style: {
      color: 'var(--mint)'
    }
  }, "portfolio"), "."), /*#__PURE__*/React.createElement("p", {
    style: {
      fontSize: 13,
      color: 'var(--ink-2)',
      marginTop: 8,
      lineHeight: 1.5
    }
  }, u.value, " \xB7 ", u.holdings, " holdings"), /*#__PURE__*/React.createElement(window.NVEyebrow, {
    style: {
      marginTop: 24,
      marginBottom: 10
    }
  }, "Suggested"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 8
    }
  }, (cfg.advisor ? [{
    id: 'advisor_rebalance',
    t: 'Which client needs rebalancing?'
  }] : prompts).map(p => /*#__PURE__*/React.createElement("button", {
    key: p.id,
    onClick: () => handle({
      id: p.id,
      text: p.t
    }),
    style: {
      textAlign: 'left',
      fontFamily: 'var(--sans)',
      fontSize: 13.5,
      color: 'var(--ink)',
      cursor: 'pointer',
      padding: '13px 15px',
      borderRadius: 12,
      background: 'var(--bg-1)',
      border: '1px solid var(--line)',
      display: 'flex',
      alignItems: 'center',
      gap: 8,
      minHeight: 48
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      flex: 1
    }
  }, p.t), /*#__PURE__*/React.createElement("span", {
    style: {
      color: 'var(--ink-4)'
    }
  }, "\u203A"))))) : /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 22,
      paddingTop: 8
    }
  }, messages.map(m => m.kind === 'user' ? /*#__PURE__*/React.createElement("div", {
    key: m.id,
    style: {
      alignSelf: 'flex-end',
      maxWidth: 280,
      padding: '10px 14px',
      background: 'var(--bg-2)',
      border: '1px solid var(--line)',
      borderRadius: '14px 14px 3px 14px'
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 13
    }
  }, m.text)) : /*#__PURE__*/React.createElement(MobileTurn, {
    key: m.id,
    msg: m,
    streaming: streaming,
    onPick: handle,
    onRetry: () => retry({
      persona: cfg.persona,
      nidpDown: !cfg.nidp
    })
  })))), /*#__PURE__*/React.createElement("div", {
    style: {
      padding: '8px 16px 20px',
      flex: 'none'
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "nv-glass",
    style: {
      padding: '9px 10px 9px 14px',
      display: 'flex',
      alignItems: 'center',
      gap: 8,
      borderRadius: 999
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      color: 'var(--ink-3)',
      fontSize: 18
    }
  }, "\uFF0B"), /*#__PURE__*/React.createElement("input", {
    value: text,
    maxLength: 500,
    onChange: e => setText(e.target.value),
    onKeyDown: e => {
      if (e.key === 'Enter') send();
    },
    placeholder: cfg.advisor ? 'Ask about clients…' : 'Ask anything…',
    style: {
      flex: 1,
      background: 'transparent',
      border: 0,
      outline: 'none',
      color: 'var(--ink)',
      fontFamily: 'var(--sans)',
      fontSize: 13.5
    }
  }), /*#__PURE__*/React.createElement("button", {
    onClick: send,
    disabled: streaming || !text.trim(),
    className: "nv-btn nv-btn-primary",
    style: {
      padding: '7px 11px',
      fontSize: 12,
      borderRadius: 999,
      opacity: streaming || !text.trim() ? .5 : 1
    }
  }, "\u2197"))), /*#__PURE__*/React.createElement("div", {
    className: "nv-homebar"
  }), sheet && /*#__PURE__*/React.createElement("div", {
    onClick: () => setSheet(false),
    style: {
      position: 'absolute',
      inset: 0,
      background: 'rgba(0,0,0,.5)',
      zIndex: 30,
      display: 'flex',
      alignItems: 'flex-end'
    }
  }, /*#__PURE__*/React.createElement("div", {
    onClick: e => e.stopPropagation(),
    style: {
      width: '100%',
      maxHeight: '70%',
      overflowY: 'auto',
      background: 'var(--bg-1)',
      borderTop: '1px solid var(--line-2)',
      borderRadius: '20px 20px 0 0',
      padding: '8px 16px 28px'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      width: 36,
      height: 4,
      borderRadius: 2,
      background: 'var(--ink-4)',
      margin: '8px auto 14px'
    }
  }), /*#__PURE__*/React.createElement("button", {
    onClick: () => {
      newSession();
      setSheet(false);
    },
    className: "nv-btn",
    style: {
      width: '100%',
      justifyContent: 'flex-start',
      fontSize: 13,
      marginBottom: 8
    }
  }, "\uFF0B New chat"), Object.entries(window.HISTORY).map(([grp, items]) => /*#__PURE__*/React.createElement("div", {
    key: grp
  }, /*#__PURE__*/React.createElement(window.NVEyebrow, {
    style: {
      fontSize: 9.5,
      padding: '12px 6px 6px'
    }
  }, grp), items.map(it => /*#__PURE__*/React.createElement("div", {
    key: it.id,
    onClick: () => setSheet(false),
    style: {
      padding: '11px 10px',
      fontSize: 13.5,
      color: 'var(--ink-2)',
      borderRadius: 8,
      cursor: 'pointer'
    }
  }, it.title)))))));
}
Object.assign(window, {
  NVChatMobile
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "app/mobile.jsx", error: String((e && e.message) || e) }); }

// app/tweaks-panel.jsx
try { (() => {
// @ds-adherence-ignore -- omelette starter scaffold (raw elements/hex/px by design)

/* BEGIN USAGE */
// tweaks-panel.jsx
// Reusable Tweaks shell + form-control helpers.
// Exports (to window): useTweaks, TweaksPanel, TweakSection, TweakRow, TweakSlider,
//   TweakToggle, TweakRadio, TweakSelect, TweakText, TweakNumber, TweakColor, TweakButton.
//
// Owns the host protocol (listens for __activate_edit_mode / __deactivate_edit_mode,
// posts __edit_mode_available / __edit_mode_set_keys / __edit_mode_dismissed) so
// individual prototypes don't re-roll it. Ships a consistent set of controls so you
// don't hand-draw <input type="range">, segmented radios, steppers, etc.
//
// Usage (in an HTML file that loads React + Babel):
//
//   const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
//     "primaryColor": "#D97757",
//     "palette": ["#D97757", "#29261b", "#f6f4ef"],
//     "fontSize": 16,
//     "density": "regular",
//     "dark": false
//   }/*EDITMODE-END*/;
//
//   function App() {
//     const [t, setTweak] = useTweaks(TWEAK_DEFAULTS);
//     return (
//       <div style={{ fontSize: t.fontSize, color: t.primaryColor }}>
//         Hello
//         <TweaksPanel>
//           <TweakSection label="Typography" />
//           <TweakSlider label="Font size" value={t.fontSize} min={10} max={32} unit="px"
//                        onChange={(v) => setTweak('fontSize', v)} />
//           <TweakRadio  label="Density" value={t.density}
//                        options={['compact', 'regular', 'comfy']}
//                        onChange={(v) => setTweak('density', v)} />
//           <TweakSection label="Theme" />
//           <TweakColor  label="Primary" value={t.primaryColor}
//                        options={['#D97757', '#2A6FDB', '#1F8A5B', '#7A5AE0']}
//                        onChange={(v) => setTweak('primaryColor', v)} />
//           <TweakColor  label="Palette" value={t.palette}
//                        options={[['#D97757', '#29261b', '#f6f4ef'],
//                                  ['#475569', '#0f172a', '#f1f5f9']]}
//                        onChange={(v) => setTweak('palette', v)} />
//           <TweakToggle label="Dark mode" value={t.dark}
//                        onChange={(v) => setTweak('dark', v)} />
//         </TweaksPanel>
//       </div>
//     );
//   }
//
// TweakRadio is the segmented control for 2–3 short options (auto-falls-back to
// TweakSelect past ~16/~10 chars per label); reach for TweakSelect directly when
// options are many or long. For color tweaks always curate 3-4 options rather than
// a free picker; an option can also be a whole 2–5 color palette (the stored value
// is the array). The Tweak* controls are a floor, not a ceiling — build custom
// controls inside the panel if a tweak calls for UI they don't cover.
/* END USAGE */
// ─────────────────────────────────────────────────────────────────────────────

const __TWEAKS_STYLE = `
  .twk-panel{position:fixed;right:16px;bottom:16px;z-index:2147483646;width:280px;
    max-height:calc(100vh - 32px);display:flex;flex-direction:column;
    transform:scale(var(--dc-inv-zoom,1));transform-origin:bottom right;
    background:rgba(250,249,247,.78);color:#29261b;
    -webkit-backdrop-filter:blur(24px) saturate(160%);backdrop-filter:blur(24px) saturate(160%);
    border:.5px solid rgba(255,255,255,.6);border-radius:14px;
    box-shadow:0 1px 0 rgba(255,255,255,.5) inset,0 12px 40px rgba(0,0,0,.18);
    font:11.5px/1.4 ui-sans-serif,system-ui,-apple-system,sans-serif;overflow:hidden}
  .twk-hd{display:flex;align-items:center;justify-content:space-between;
    padding:10px 8px 10px 14px;cursor:move;user-select:none}
  .twk-hd b{font-size:12px;font-weight:600;letter-spacing:.01em}
  .twk-x{appearance:none;border:0;background:transparent;color:rgba(41,38,27,.55);
    width:22px;height:22px;border-radius:6px;cursor:default;font-size:13px;line-height:1}
  .twk-x:hover{background:rgba(0,0,0,.06);color:#29261b}
  .twk-body{padding:2px 14px 14px;display:flex;flex-direction:column;gap:10px;
    overflow-y:auto;overflow-x:hidden;min-height:0;
    scrollbar-width:thin;scrollbar-color:rgba(0,0,0,.15) transparent}
  .twk-body::-webkit-scrollbar{width:8px}
  .twk-body::-webkit-scrollbar-track{background:transparent;margin:2px}
  .twk-body::-webkit-scrollbar-thumb{background:rgba(0,0,0,.15);border-radius:4px;
    border:2px solid transparent;background-clip:content-box}
  .twk-body::-webkit-scrollbar-thumb:hover{background:rgba(0,0,0,.25);
    border:2px solid transparent;background-clip:content-box}
  .twk-row{display:flex;flex-direction:column;gap:5px}
  .twk-row-h{flex-direction:row;align-items:center;justify-content:space-between;gap:10px}
  .twk-lbl{display:flex;justify-content:space-between;align-items:baseline;
    color:rgba(41,38,27,.72)}
  .twk-lbl>span:first-child{font-weight:500}
  .twk-val{color:rgba(41,38,27,.5);font-variant-numeric:tabular-nums}

  .twk-sect{font-size:10px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;
    color:rgba(41,38,27,.45);padding:10px 0 0}
  .twk-sect:first-child{padding-top:0}

  .twk-field{appearance:none;box-sizing:border-box;width:100%;min-width:0;height:26px;padding:0 8px;
    border:.5px solid rgba(0,0,0,.1);border-radius:7px;
    background:rgba(255,255,255,.6);color:inherit;font:inherit;outline:none}
  .twk-field:focus{border-color:rgba(0,0,0,.25);background:rgba(255,255,255,.85)}
  select.twk-field{padding-right:22px;
    background-image:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='10' height='6' viewBox='0 0 10 6'><path fill='rgba(0,0,0,.5)' d='M0 0h10L5 6z'/></svg>");
    background-repeat:no-repeat;background-position:right 8px center}

  .twk-slider{appearance:none;-webkit-appearance:none;width:100%;height:4px;margin:6px 0;
    border-radius:999px;background:rgba(0,0,0,.12);outline:none}
  .twk-slider::-webkit-slider-thumb{-webkit-appearance:none;appearance:none;
    width:14px;height:14px;border-radius:50%;background:#fff;
    border:.5px solid rgba(0,0,0,.12);box-shadow:0 1px 3px rgba(0,0,0,.2);cursor:default}
  .twk-slider::-moz-range-thumb{width:14px;height:14px;border-radius:50%;
    background:#fff;border:.5px solid rgba(0,0,0,.12);box-shadow:0 1px 3px rgba(0,0,0,.2);cursor:default}

  .twk-seg{position:relative;display:flex;padding:2px;border-radius:8px;
    background:rgba(0,0,0,.06);user-select:none}
  .twk-seg-thumb{position:absolute;top:2px;bottom:2px;border-radius:6px;
    background:rgba(255,255,255,.9);box-shadow:0 1px 2px rgba(0,0,0,.12);
    transition:left .15s cubic-bezier(.3,.7,.4,1),width .15s}
  .twk-seg.dragging .twk-seg-thumb{transition:none}
  .twk-seg button{appearance:none;position:relative;z-index:1;flex:1;border:0;
    background:transparent;color:inherit;font:inherit;font-weight:500;min-height:22px;
    border-radius:6px;cursor:default;padding:4px 6px;line-height:1.2;
    overflow-wrap:anywhere}

  .twk-toggle{position:relative;width:32px;height:18px;border:0;border-radius:999px;
    background:rgba(0,0,0,.15);transition:background .15s;cursor:default;padding:0}
  .twk-toggle[data-on="1"]{background:#34c759}
  .twk-toggle i{position:absolute;top:2px;left:2px;width:14px;height:14px;border-radius:50%;
    background:#fff;box-shadow:0 1px 2px rgba(0,0,0,.25);transition:transform .15s}
  .twk-toggle[data-on="1"] i{transform:translateX(14px)}

  .twk-num{display:flex;align-items:center;box-sizing:border-box;min-width:0;height:26px;padding:0 0 0 8px;
    border:.5px solid rgba(0,0,0,.1);border-radius:7px;background:rgba(255,255,255,.6)}
  .twk-num-lbl{font-weight:500;color:rgba(41,38,27,.6);cursor:ew-resize;
    user-select:none;padding-right:8px}
  .twk-num input{flex:1;min-width:0;height:100%;border:0;background:transparent;
    font:inherit;font-variant-numeric:tabular-nums;text-align:right;padding:0 8px 0 0;
    outline:none;color:inherit;-moz-appearance:textfield}
  .twk-num input::-webkit-inner-spin-button,.twk-num input::-webkit-outer-spin-button{
    -webkit-appearance:none;margin:0}
  .twk-num-unit{padding-right:8px;color:rgba(41,38,27,.45)}

  .twk-btn{appearance:none;height:26px;padding:0 12px;border:0;border-radius:7px;
    background:rgba(0,0,0,.78);color:#fff;font:inherit;font-weight:500;cursor:default}
  .twk-btn:hover{background:rgba(0,0,0,.88)}
  .twk-btn.secondary{background:rgba(0,0,0,.06);color:inherit}
  .twk-btn.secondary:hover{background:rgba(0,0,0,.1)}

  .twk-swatch{appearance:none;-webkit-appearance:none;width:56px;height:22px;
    border:.5px solid rgba(0,0,0,.1);border-radius:6px;padding:0;cursor:default;
    background:transparent;flex-shrink:0}
  .twk-swatch::-webkit-color-swatch-wrapper{padding:0}
  .twk-swatch::-webkit-color-swatch{border:0;border-radius:5.5px}
  .twk-swatch::-moz-color-swatch{border:0;border-radius:5.5px}

  .twk-chips{display:flex;gap:6px}
  .twk-chip{position:relative;appearance:none;flex:1;min-width:0;height:46px;
    padding:0;border:0;border-radius:6px;overflow:hidden;cursor:default;
    box-shadow:0 0 0 .5px rgba(0,0,0,.12),0 1px 2px rgba(0,0,0,.06);
    transition:transform .12s cubic-bezier(.3,.7,.4,1),box-shadow .12s}
  .twk-chip:hover{transform:translateY(-1px);
    box-shadow:0 0 0 .5px rgba(0,0,0,.18),0 4px 10px rgba(0,0,0,.12)}
  .twk-chip[data-on="1"]{box-shadow:0 0 0 1.5px rgba(0,0,0,.85),
    0 2px 6px rgba(0,0,0,.15)}
  .twk-chip>span{position:absolute;top:0;bottom:0;right:0;width:34%;
    display:flex;flex-direction:column;box-shadow:-1px 0 0 rgba(0,0,0,.1)}
  .twk-chip>span>i{flex:1;box-shadow:0 -1px 0 rgba(0,0,0,.1)}
  .twk-chip>span>i:first-child{box-shadow:none}
  .twk-chip svg{position:absolute;top:6px;left:6px;width:13px;height:13px;
    filter:drop-shadow(0 1px 1px rgba(0,0,0,.3))}
`;

// ── useTweaks ───────────────────────────────────────────────────────────────
// Single source of truth for tweak values. setTweak persists via the host
// (__edit_mode_set_keys → host rewrites the EDITMODE block on disk).
function useTweaks(defaults) {
  const [values, setValues] = React.useState(defaults);
  // Accepts either setTweak('key', value) or setTweak({ key: value, ... }) so a
  // useState-style call doesn't write a "[object Object]" key into the persisted
  // JSON block.
  const setTweak = React.useCallback((keyOrEdits, val) => {
    const edits = typeof keyOrEdits === 'object' && keyOrEdits !== null ? keyOrEdits : {
      [keyOrEdits]: val
    };
    setValues(prev => ({
      ...prev,
      ...edits
    }));
    window.parent.postMessage({
      type: '__edit_mode_set_keys',
      edits
    }, '*');
    // Same-window signal so in-page listeners (deck-stage rail thumbnails)
    // can react — the parent message only reaches the host, not peers.
    window.dispatchEvent(new CustomEvent('tweakchange', {
      detail: edits
    }));
  }, []);
  return [values, setTweak];
}

// ── TweaksPanel ─────────────────────────────────────────────────────────────
// Floating shell. Registers the protocol listener BEFORE announcing
// availability — if the announce ran first, the host's activate could land
// before our handler exists and the toolbar toggle would silently no-op.
// The close button posts __edit_mode_dismissed so the host's toolbar toggle
// flips off in lockstep; the host echoes __deactivate_edit_mode back which
// is what actually hides the panel.
function TweaksPanel({
  title = 'Tweaks',
  children
}) {
  const [open, setOpen] = React.useState(false);
  const dragRef = React.useRef(null);
  const offsetRef = React.useRef({
    x: 16,
    y: 16
  });
  const PAD = 16;
  const clampToViewport = React.useCallback(() => {
    const panel = dragRef.current;
    if (!panel) return;
    const w = panel.offsetWidth,
      h = panel.offsetHeight;
    const maxRight = Math.max(PAD, window.innerWidth - w - PAD);
    const maxBottom = Math.max(PAD, window.innerHeight - h - PAD);
    offsetRef.current = {
      x: Math.min(maxRight, Math.max(PAD, offsetRef.current.x)),
      y: Math.min(maxBottom, Math.max(PAD, offsetRef.current.y))
    };
    panel.style.right = offsetRef.current.x + 'px';
    panel.style.bottom = offsetRef.current.y + 'px';
  }, []);
  React.useEffect(() => {
    if (!open) return;
    clampToViewport();
    if (typeof ResizeObserver === 'undefined') {
      window.addEventListener('resize', clampToViewport);
      return () => window.removeEventListener('resize', clampToViewport);
    }
    const ro = new ResizeObserver(clampToViewport);
    ro.observe(document.documentElement);
    return () => ro.disconnect();
  }, [open, clampToViewport]);
  React.useEffect(() => {
    const onMsg = e => {
      const t = e?.data?.type;
      if (t === '__activate_edit_mode') setOpen(true);else if (t === '__deactivate_edit_mode') setOpen(false);
    };
    window.addEventListener('message', onMsg);
    window.parent.postMessage({
      type: '__edit_mode_available'
    }, '*');
    return () => window.removeEventListener('message', onMsg);
  }, []);
  const dismiss = () => {
    setOpen(false);
    window.parent.postMessage({
      type: '__edit_mode_dismissed'
    }, '*');
  };
  const onDragStart = e => {
    const panel = dragRef.current;
    if (!panel) return;
    const r = panel.getBoundingClientRect();
    const sx = e.clientX,
      sy = e.clientY;
    const startRight = window.innerWidth - r.right;
    const startBottom = window.innerHeight - r.bottom;
    const move = ev => {
      offsetRef.current = {
        x: startRight - (ev.clientX - sx),
        y: startBottom - (ev.clientY - sy)
      };
      clampToViewport();
    };
    const up = () => {
      window.removeEventListener('mousemove', move);
      window.removeEventListener('mouseup', up);
    };
    window.addEventListener('mousemove', move);
    window.addEventListener('mouseup', up);
  };
  if (!open) return null;
  return /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("style", null, __TWEAKS_STYLE), /*#__PURE__*/React.createElement("div", {
    ref: dragRef,
    className: "twk-panel",
    "data-omelette-chrome": "",
    style: {
      right: offsetRef.current.x,
      bottom: offsetRef.current.y
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "twk-hd",
    onMouseDown: onDragStart
  }, /*#__PURE__*/React.createElement("b", null, title), /*#__PURE__*/React.createElement("button", {
    className: "twk-x",
    "aria-label": "Close tweaks",
    onMouseDown: e => e.stopPropagation(),
    onClick: dismiss
  }, "\u2715")), /*#__PURE__*/React.createElement("div", {
    className: "twk-body"
  }, children)));
}

// ── Layout helpers ──────────────────────────────────────────────────────────

function TweakSection({
  label,
  children
}) {
  return /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("div", {
    className: "twk-sect"
  }, label), children);
}
function TweakRow({
  label,
  value,
  children,
  inline = false
}) {
  return /*#__PURE__*/React.createElement("div", {
    className: inline ? 'twk-row twk-row-h' : 'twk-row'
  }, /*#__PURE__*/React.createElement("div", {
    className: "twk-lbl"
  }, /*#__PURE__*/React.createElement("span", null, label), value != null && /*#__PURE__*/React.createElement("span", {
    className: "twk-val"
  }, value)), children);
}

// ── Controls ────────────────────────────────────────────────────────────────

function TweakSlider({
  label,
  value,
  min = 0,
  max = 100,
  step = 1,
  unit = '',
  onChange
}) {
  return /*#__PURE__*/React.createElement(TweakRow, {
    label: label,
    value: `${value}${unit}`
  }, /*#__PURE__*/React.createElement("input", {
    type: "range",
    className: "twk-slider",
    min: min,
    max: max,
    step: step,
    value: value,
    onChange: e => onChange(Number(e.target.value))
  }));
}
function TweakToggle({
  label,
  value,
  onChange
}) {
  return /*#__PURE__*/React.createElement("div", {
    className: "twk-row twk-row-h"
  }, /*#__PURE__*/React.createElement("div", {
    className: "twk-lbl"
  }, /*#__PURE__*/React.createElement("span", null, label)), /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "twk-toggle",
    "data-on": value ? '1' : '0',
    role: "switch",
    "aria-checked": !!value,
    onClick: () => onChange(!value)
  }, /*#__PURE__*/React.createElement("i", null)));
}
function TweakRadio({
  label,
  value,
  options,
  onChange
}) {
  const trackRef = React.useRef(null);
  const [dragging, setDragging] = React.useState(false);
  // The active value is read by pointer-move handlers attached for the lifetime
  // of a drag — ref it so a stale closure doesn't fire onChange for every move.
  const valueRef = React.useRef(value);
  valueRef.current = value;

  // Segments wrap mid-word once per-segment width runs out. The track is
  // ~248px (280 panel − 28 body pad − 4 seg pad), each button loses 12px
  // to its own padding, and 11.5px system-ui averages ~6.3px/char — so 2
  // options fit ~16 chars each, 3 fit ~10. Past that (or >3 options), fall
  // back to a dropdown rather than wrap.
  const labelLen = o => String(typeof o === 'object' ? o.label : o).length;
  const maxLen = options.reduce((m, o) => Math.max(m, labelLen(o)), 0);
  const fitsAsSegments = maxLen <= ({
    2: 16,
    3: 10
  }[options.length] ?? 0);
  if (!fitsAsSegments) {
    // <select> emits strings — map back to the original option value so the
    // fallback stays type-preserving (numbers, booleans) like the segment path.
    const resolve = s => {
      const m = options.find(o => String(typeof o === 'object' ? o.value : o) === s);
      return m === undefined ? s : typeof m === 'object' ? m.value : m;
    };
    return /*#__PURE__*/React.createElement(TweakSelect, {
      label: label,
      value: value,
      options: options,
      onChange: s => onChange(resolve(s))
    });
  }
  const opts = options.map(o => typeof o === 'object' ? o : {
    value: o,
    label: o
  });
  const idx = Math.max(0, opts.findIndex(o => o.value === value));
  const n = opts.length;
  const segAt = clientX => {
    const r = trackRef.current.getBoundingClientRect();
    const inner = r.width - 4;
    const i = Math.floor((clientX - r.left - 2) / inner * n);
    return opts[Math.max(0, Math.min(n - 1, i))].value;
  };
  const onPointerDown = e => {
    setDragging(true);
    const v0 = segAt(e.clientX);
    if (v0 !== valueRef.current) onChange(v0);
    const move = ev => {
      if (!trackRef.current) return;
      const v = segAt(ev.clientX);
      if (v !== valueRef.current) onChange(v);
    };
    const up = () => {
      setDragging(false);
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  };
  return /*#__PURE__*/React.createElement(TweakRow, {
    label: label
  }, /*#__PURE__*/React.createElement("div", {
    ref: trackRef,
    role: "radiogroup",
    onPointerDown: onPointerDown,
    className: dragging ? 'twk-seg dragging' : 'twk-seg'
  }, /*#__PURE__*/React.createElement("div", {
    className: "twk-seg-thumb",
    style: {
      left: `calc(2px + ${idx} * (100% - 4px) / ${n})`,
      width: `calc((100% - 4px) / ${n})`
    }
  }), opts.map(o => /*#__PURE__*/React.createElement("button", {
    key: o.value,
    type: "button",
    role: "radio",
    "aria-checked": o.value === value
  }, o.label))));
}
function TweakSelect({
  label,
  value,
  options,
  onChange
}) {
  return /*#__PURE__*/React.createElement(TweakRow, {
    label: label
  }, /*#__PURE__*/React.createElement("select", {
    className: "twk-field",
    value: value,
    onChange: e => onChange(e.target.value)
  }, options.map(o => {
    const v = typeof o === 'object' ? o.value : o;
    const l = typeof o === 'object' ? o.label : o;
    return /*#__PURE__*/React.createElement("option", {
      key: v,
      value: v
    }, l);
  })));
}
function TweakText({
  label,
  value,
  placeholder,
  onChange
}) {
  return /*#__PURE__*/React.createElement(TweakRow, {
    label: label
  }, /*#__PURE__*/React.createElement("input", {
    className: "twk-field",
    type: "text",
    value: value,
    placeholder: placeholder,
    onChange: e => onChange(e.target.value)
  }));
}
function TweakNumber({
  label,
  value,
  min,
  max,
  step = 1,
  unit = '',
  onChange
}) {
  const clamp = n => {
    if (min != null && n < min) return min;
    if (max != null && n > max) return max;
    return n;
  };
  const startRef = React.useRef({
    x: 0,
    val: 0
  });
  const onScrubStart = e => {
    e.preventDefault();
    startRef.current = {
      x: e.clientX,
      val: value
    };
    const decimals = (String(step).split('.')[1] || '').length;
    const move = ev => {
      const dx = ev.clientX - startRef.current.x;
      const raw = startRef.current.val + dx * step;
      const snapped = Math.round(raw / step) * step;
      onChange(clamp(Number(snapped.toFixed(decimals))));
    };
    const up = () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  };
  return /*#__PURE__*/React.createElement("div", {
    className: "twk-num"
  }, /*#__PURE__*/React.createElement("span", {
    className: "twk-num-lbl",
    onPointerDown: onScrubStart
  }, label), /*#__PURE__*/React.createElement("input", {
    type: "number",
    value: value,
    min: min,
    max: max,
    step: step,
    onChange: e => onChange(clamp(Number(e.target.value)))
  }), unit && /*#__PURE__*/React.createElement("span", {
    className: "twk-num-unit"
  }, unit));
}

// Relative-luminance contrast pick — checkmarks drawn over a swatch need to
// read on both #111 and #fafafa without per-option configuration. Hex input
// only (#rgb / #rrggbb); named or rgb()/hsl() colors fall through to "light".
function __twkIsLight(hex) {
  const h = String(hex).replace('#', '');
  const x = h.length === 3 ? h.replace(/./g, c => c + c) : h.padEnd(6, '0');
  const n = parseInt(x.slice(0, 6), 16);
  if (Number.isNaN(n)) return true;
  const r = n >> 16 & 255,
    g = n >> 8 & 255,
    b = n & 255;
  return r * 299 + g * 587 + b * 114 > 148000;
}
const __TwkCheck = ({
  light
}) => /*#__PURE__*/React.createElement("svg", {
  viewBox: "0 0 14 14",
  "aria-hidden": "true"
}, /*#__PURE__*/React.createElement("path", {
  d: "M3 7.2 5.8 10 11 4.2",
  fill: "none",
  strokeWidth: "2.2",
  strokeLinecap: "round",
  strokeLinejoin: "round",
  stroke: light ? 'rgba(0,0,0,.78)' : '#fff'
}));

// TweakColor — curated color/palette picker. Each option is either a single
// hex string or an array of 1-5 hex strings; the card adapts — a lone color
// renders solid, a palette renders colors[0] as the hero (left ~2/3) with the
// rest stacked in a sharp column on the right. onChange emits the
// option in the shape it was passed (string stays string, array stays array).
// Without options it falls back to the native color input for back-compat.
function TweakColor({
  label,
  value,
  options,
  onChange
}) {
  if (!options || !options.length) {
    return /*#__PURE__*/React.createElement("div", {
      className: "twk-row twk-row-h"
    }, /*#__PURE__*/React.createElement("div", {
      className: "twk-lbl"
    }, /*#__PURE__*/React.createElement("span", null, label)), /*#__PURE__*/React.createElement("input", {
      type: "color",
      className: "twk-swatch",
      value: value,
      onChange: e => onChange(e.target.value)
    }));
  }
  // Native <input type=color> emits lowercase hex per the HTML spec, so
  // compare case-insensitively. String() guards JSON.stringify(undefined),
  // which returns the primitive undefined (no .toLowerCase).
  const key = o => String(JSON.stringify(o)).toLowerCase();
  const cur = key(value);
  return /*#__PURE__*/React.createElement(TweakRow, {
    label: label
  }, /*#__PURE__*/React.createElement("div", {
    className: "twk-chips",
    role: "radiogroup"
  }, options.map((o, i) => {
    const colors = Array.isArray(o) ? o : [o];
    const [hero, ...rest] = colors;
    const sup = rest.slice(0, 4);
    const on = key(o) === cur;
    return /*#__PURE__*/React.createElement("button", {
      key: i,
      type: "button",
      className: "twk-chip",
      role: "radio",
      "aria-checked": on,
      "data-on": on ? '1' : '0',
      "aria-label": colors.join(', '),
      title: colors.join(' · '),
      style: {
        background: hero
      },
      onClick: () => onChange(o)
    }, sup.length > 0 && /*#__PURE__*/React.createElement("span", null, sup.map((c, j) => /*#__PURE__*/React.createElement("i", {
      key: j,
      style: {
        background: c
      }
    }))), on && /*#__PURE__*/React.createElement(__TwkCheck, {
      light: __twkIsLight(hero)
    }));
  })));
}
function TweakButton({
  label,
  onClick,
  secondary = false
}) {
  return /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: secondary ? 'twk-btn secondary' : 'twk-btn',
    onClick: onClick
  }, label);
}
Object.assign(window, {
  useTweaks,
  TweaksPanel,
  TweakSection,
  TweakRow,
  TweakSlider,
  TweakToggle,
  TweakRadio,
  TweakSelect,
  TweakText,
  TweakNumber,
  TweakColor,
  TweakButton
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "app/tweaks-panel.jsx", error: String((e && e.message) || e) }); }

// app/widgets.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
// ─── Nivesh Copilot · structured widgets (FR-CHAT-008) ─────────────────────
// 10 WidgetType components + advisor client_book. NVWidget routes by type.
const {
  NVScoreRing: SRing,
  NVSignal: Sig,
  NVChatRow: Row,
  NVEyebrow: Eb,
  NVBar: Bar
} = window;
const wcard = {
  background: 'var(--bg-1)',
  border: '1px solid var(--line)',
  borderRadius: 'var(--radius-md)',
  boxShadow: 'var(--shadow-card)',
  overflow: 'hidden'
};
const whead = {
  padding: '13px 18px',
  borderBottom: '1px solid var(--line)',
  display: 'flex',
  alignItems: 'center',
  gap: 10,
  background: 'var(--bg-0)'
};
const sigPillColor = s => ({
  BUY: 'mint',
  HOLD: 'indigo',
  REDUCE: 'danger',
  SELL: 'danger'
})[s] || 'indigo';
function WHead({
  label,
  right
}) {
  return /*#__PURE__*/React.createElement("div", {
    style: whead
  }, /*#__PURE__*/React.createElement(Eb, null, label), right && /*#__PURE__*/React.createElement("span", {
    style: {
      marginLeft: 'auto'
    }
  }, right));
}

// 1 ── portfolio_overview
function WPortfolioOverview({
  data,
  onPick
}) {
  return /*#__PURE__*/React.createElement("div", {
    style: wcard
  }, /*#__PURE__*/React.createElement(WHead, {
    label: "Portfolio overview",
    right: /*#__PURE__*/React.createElement("span", {
      className: "nv-pill nv-pill-mint"
    }, "GRADE ", data.grade)
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'grid',
      gridTemplateColumns: '170px 1fr',
      borderBottom: '1px solid var(--line)'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      padding: '20px 14px',
      borderRight: '1px solid var(--line)',
      display: 'grid',
      placeItems: 'center',
      background: 'var(--bg-0)'
    }
  }, /*#__PURE__*/React.createElement(SRing, {
    size: 124,
    score: data.score
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      padding: 16,
      display: 'grid',
      gridTemplateColumns: 'repeat(3, 1fr)',
      gap: 12
    }
  }, data.signals.map(s => /*#__PURE__*/React.createElement(Sig, _extends({
    key: s.label
  }, s))))), data.actions && /*#__PURE__*/React.createElement("div", {
    style: {
      padding: 16
    }
  }, /*#__PURE__*/React.createElement(Eb, {
    style: {
      marginBottom: 10
    }
  }, "Top 3 actions \xB7 ranked by \u20B9 impact"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 8
    }
  }, data.actions.map(a => /*#__PURE__*/React.createElement(Row, _extends({
    key: a.num
  }, a, {
    onPick: onPick ? () => onPick(a.scenario) : undefined
  }))))));
}

// 2 ── rebalance_plan
function WRebalancePlan({
  data
}) {
  return /*#__PURE__*/React.createElement("div", {
    style: wcard
  }, /*#__PURE__*/React.createElement(WHead, {
    label: "Rebalance plan",
    right: /*#__PURE__*/React.createElement("span", {
      className: "nv-mono",
      style: {
        fontSize: 10.5,
        color: 'var(--ink-3)',
        letterSpacing: '.04em'
      }
    }, data.net)
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      padding: 12,
      display: 'flex',
      flexDirection: 'column',
      gap: 8
    }
  }, data.actions.map(a => {
    const buy = a.direction === 'BUY';
    const c = buy ? 'mint' : 'danger';
    return /*#__PURE__*/React.createElement("div", {
      key: a.name,
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 14,
        padding: '12px 14px',
        borderRadius: 11,
        background: 'var(--bg-1)',
        border: '1px solid var(--line)'
      }
    }, /*#__PURE__*/React.createElement("span", {
      className: `nv-pill nv-pill-${c}`,
      style: {
        flex: 'none',
        width: 54,
        justifyContent: 'center'
      }
    }, a.direction), /*#__PURE__*/React.createElement("div", {
      style: {
        flex: 1,
        minWidth: 0
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 14,
        fontWeight: 500
      }
    }, a.name), /*#__PURE__*/React.createElement("div", {
      className: "nv-mono",
      style: {
        fontSize: 10.5,
        color: 'var(--ink-3)',
        marginTop: 2,
        letterSpacing: '.03em',
        textTransform: 'uppercase'
      }
    }, a.reason)), /*#__PURE__*/React.createElement("div", {
      className: "nv-num nv-serif",
      style: {
        fontSize: 19,
        color: `var(--${c})`
      }
    }, a.amount));
  })));
}

// 3 ── tax_harvest
function WTaxHarvest({
  data
}) {
  return /*#__PURE__*/React.createElement("div", {
    style: wcard
  }, /*#__PURE__*/React.createElement(WHead, {
    label: "Tax-loss harvest",
    right: /*#__PURE__*/React.createElement("span", {
      style: {
        display: 'flex',
        alignItems: 'baseline',
        gap: 6
      }
    }, /*#__PURE__*/React.createElement("span", {
      className: "nv-mono",
      style: {
        fontSize: 9.5,
        color: 'var(--ink-3)',
        letterSpacing: '.1em'
      }
    }, "EST. SAVING"), /*#__PURE__*/React.createElement("span", {
      className: "nv-serif nv-num",
      style: {
        fontSize: 22,
        color: 'var(--mint)'
      }
    }, data.totalSavings))
  }), /*#__PURE__*/React.createElement("table", {
    style: {
      width: '100%',
      borderCollapse: 'collapse'
    }
  }, /*#__PURE__*/React.createElement("caption", {
    className: "nv-mono",
    style: {
      captionSide: 'top',
      textAlign: 'left',
      padding: '0 18px',
      height: 0,
      overflow: 'hidden',
      opacity: 0
    }
  }, "Loss-making lots eligible to harvest before March 31"), /*#__PURE__*/React.createElement("tbody", null, data.lots.map((l, i) => /*#__PURE__*/React.createElement("tr", {
    key: l.isin,
    style: {
      borderTop: i ? '1px solid var(--line)' : 0
    }
  }, /*#__PURE__*/React.createElement("td", {
    style: {
      padding: '13px 18px'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 14,
      fontWeight: 500
    }
  }, l.name), /*#__PURE__*/React.createElement("div", {
    className: "nv-mono",
    style: {
      fontSize: 10,
      color: 'var(--ink-4)',
      marginTop: 2
    }
  }, l.isin)), /*#__PURE__*/React.createElement("td", {
    className: "nv-num nv-serif",
    style: {
      padding: '13px 18px',
      textAlign: 'right',
      fontSize: 18,
      color: 'var(--danger)',
      whiteSpace: 'nowrap'
    }
  }, "\u2212", l.loss), /*#__PURE__*/React.createElement("td", {
    className: "nv-mono",
    style: {
      padding: '13px 18px',
      textAlign: 'right',
      fontSize: 10.5,
      color: 'var(--amber)',
      letterSpacing: '.06em',
      whiteSpace: 'nowrap'
    }
  }, "BY ", l.by.toUpperCase()))))));
}

// 4 ── fund_comparison
function WFundComparison({
  data
}) {
  const cols = [['quality', 'QUAL'], ['health', 'HLTH'], ['exit', 'EXIT']];
  const cell = v => v >= 80 ? 'mint' : v >= 70 ? 'indigo' : 'danger';
  return /*#__PURE__*/React.createElement("div", {
    style: wcard
  }, /*#__PURE__*/React.createElement(WHead, {
    label: "Fund comparison \xB7 V3 scorecard"
  }), /*#__PURE__*/React.createElement("table", {
    style: {
      width: '100%',
      borderCollapse: 'collapse'
    }
  }, /*#__PURE__*/React.createElement("caption", {
    className: "nv-mono",
    style: {
      captionSide: 'top',
      height: 0,
      overflow: 'hidden',
      opacity: 0
    }
  }, "V3 quality, health, exit scores and 3-year XIRR per fund"), /*#__PURE__*/React.createElement("thead", null, /*#__PURE__*/React.createElement("tr", null, /*#__PURE__*/React.createElement("th", {
    style: {
      textAlign: 'left',
      padding: '8px 18px'
    }
  }, /*#__PURE__*/React.createElement(Eb, null, "Fund")), cols.map(([, h]) => /*#__PURE__*/React.createElement("th", {
    key: h,
    style: {
      padding: '8px 10px',
      textAlign: 'center'
    }
  }, /*#__PURE__*/React.createElement(Eb, null, h))), /*#__PURE__*/React.createElement("th", {
    style: {
      padding: '8px 18px',
      textAlign: 'right'
    }
  }, /*#__PURE__*/React.createElement(Eb, null, "3Y XIRR")))), /*#__PURE__*/React.createElement("tbody", null, data.funds.map(f => /*#__PURE__*/React.createElement("tr", {
    key: f.code,
    style: {
      borderTop: '1px solid var(--line)'
    }
  }, /*#__PURE__*/React.createElement("td", {
    style: {
      padding: '12px 18px'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 13.5,
      fontWeight: 500
    }
  }, f.name), /*#__PURE__*/React.createElement("div", {
    className: "nv-mono",
    style: {
      fontSize: 10,
      color: 'var(--ink-4)',
      marginTop: 2
    }
  }, f.code)), cols.map(([k]) => /*#__PURE__*/React.createElement("td", {
    key: k,
    className: "nv-num nv-serif",
    style: {
      padding: '12px 10px',
      textAlign: 'center',
      fontSize: 19,
      color: `var(--${cell(f[k])})`
    }
  }, f[k])), /*#__PURE__*/React.createElement("td", {
    className: "nv-num nv-serif",
    style: {
      padding: '12px 18px',
      textAlign: 'right',
      fontSize: 19
    }
  }, f.xirr))))));
}

// 5 ── stock_screener
function WStockScreener({
  data
}) {
  return /*#__PURE__*/React.createElement("div", {
    style: wcard
  }, /*#__PURE__*/React.createElement(WHead, {
    label: "Stock screener \xB7 NIDP composite"
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      padding: 12,
      display: 'flex',
      flexDirection: 'column',
      gap: 8
    }
  }, data.stocks.map(s => {
    const c = s.score >= 80 ? 'mint' : s.score >= 60 ? 'indigo' : 'danger';
    return /*#__PURE__*/React.createElement("div", {
      key: s.symbol,
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 14,
        padding: '11px 14px',
        borderRadius: 11,
        background: 'var(--bg-1)',
        border: '1px solid var(--line)'
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        flex: 1,
        minWidth: 0
      }
    }, /*#__PURE__*/React.createElement("div", {
      className: "nv-mono",
      style: {
        fontSize: 12,
        fontWeight: 600,
        letterSpacing: '.04em'
      }
    }, s.symbol), /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 11.5,
        color: 'var(--ink-3)',
        marginTop: 1
      }
    }, s.name)), /*#__PURE__*/React.createElement("div", {
      style: {
        width: 90,
        display: 'flex',
        alignItems: 'center',
        gap: 8
      }
    }, /*#__PURE__*/React.createElement(Bar, {
      pct: s.score,
      color: c
    }), /*#__PURE__*/React.createElement("span", {
      className: "nv-num nv-serif",
      style: {
        fontSize: 17,
        color: `var(--${c})`,
        width: 26,
        textAlign: 'right'
      }
    }, s.score)), /*#__PURE__*/React.createElement("span", {
      className: `nv-pill nv-pill-${sigPillColor(s.signal)}`,
      style: {
        width: 70,
        justifyContent: 'center',
        flex: 'none'
      }
    }, s.signal));
  })));
}

// 6 ── sector_rotation
function WSectorRotation({
  data
}) {
  const max = Math.max(...data.sectors.map(s => Math.max(s.current, s.target)));
  return /*#__PURE__*/React.createElement("div", {
    style: wcard
  }, /*#__PURE__*/React.createElement(WHead, {
    label: "Sector rotation \xB7 current \u2192 target"
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      padding: '16px 18px',
      display: 'flex',
      flexDirection: 'column',
      gap: 14
    }
  }, data.sectors.map(s => {
    const dc = s.delta < 0 ? 'danger' : s.delta > 0 ? 'mint' : 'ink-3';
    return /*#__PURE__*/React.createElement("div", {
      key: s.name,
      style: {
        display: 'grid',
        gridTemplateColumns: '120px 1fr 58px',
        alignItems: 'center',
        gap: 12
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: 13,
        fontWeight: 500
      }
    }, s.name), /*#__PURE__*/React.createElement("div", {
      style: {
        position: 'relative',
        height: 8
      }
    }, /*#__PURE__*/React.createElement(Bar, {
      pct: s.current / max * 100,
      color: s.delta < 0 ? 'amber' : 'indigo',
      h: 8
    }), /*#__PURE__*/React.createElement("span", {
      style: {
        position: 'absolute',
        top: -3,
        left: `calc(${s.target / max * 100}% - 1px)`,
        width: 2,
        height: 14,
        background: 'var(--mint)',
        borderRadius: 2
      },
      title: `target ${s.target}%`
    })), /*#__PURE__*/React.createElement("span", {
      className: "nv-mono nv-num",
      style: {
        fontSize: 11,
        color: `var(--${dc})`,
        textAlign: 'right',
        letterSpacing: '.02em'
      }
    }, s.delta > 0 ? '+' : '', s.delta === 0 ? 'on tgt' : `${s.delta}pp`));
  }), /*#__PURE__*/React.createElement("div", {
    className: "nv-mono",
    style: {
      fontSize: 9.5,
      color: 'var(--ink-4)',
      letterSpacing: '.06em',
      marginTop: 2,
      display: 'flex',
      gap: 16
    }
  }, /*#__PURE__*/React.createElement("span", null, /*#__PURE__*/React.createElement("span", {
    style: {
      color: 'var(--indigo)'
    }
  }, "\u25AC"), " CURRENT"), /*#__PURE__*/React.createElement("span", null, /*#__PURE__*/React.createElement("span", {
    style: {
      color: 'var(--mint)'
    }
  }, "\u2502"), " TARGET"))));
}

// 7 ── overlap_reveal
function WOverlapReveal({
  data
}) {
  return /*#__PURE__*/React.createElement("div", {
    style: wcard
  }, /*#__PURE__*/React.createElement(WHead, {
    label: "Overlap reveal"
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      padding: 14,
      display: 'flex',
      flexDirection: 'column',
      gap: 12
    }
  }, data.pairs.map((p, i) => /*#__PURE__*/React.createElement("div", {
    key: i,
    style: {
      padding: '14px 16px',
      borderRadius: 12,
      background: 'var(--bg-1)',
      border: '1px solid var(--line)'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 10
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 13.5,
      fontWeight: 500
    }
  }, p.a), /*#__PURE__*/React.createElement("span", {
    style: {
      color: 'var(--ink-4)'
    }
  }, "\u2194"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 13.5,
      fontWeight: 500
    }
  }, p.b), /*#__PURE__*/React.createElement("span", {
    className: "nv-serif nv-num",
    style: {
      marginLeft: 'auto',
      fontSize: 26,
      color: 'var(--indigo)'
    }
  }, p.pct, "%")), /*#__PURE__*/React.createElement("div", {
    style: {
      margin: '10px 0'
    }
  }, /*#__PURE__*/React.createElement(Bar, {
    pct: p.pct,
    color: "indigo",
    h: 6
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexWrap: 'wrap',
      gap: 6
    }
  }, p.common.map(n => /*#__PURE__*/React.createElement("span", {
    key: n,
    className: "nv-mono",
    style: {
      fontSize: 10,
      padding: '3px 8px',
      borderRadius: 999,
      border: '1px solid var(--line-2)',
      color: 'var(--ink-3)',
      letterSpacing: '.02em'
    }
  }, n)))))));
}

// 8 ── goal_tracker
function WGoalTracker({
  data
}) {
  return /*#__PURE__*/React.createElement("div", {
    style: wcard
  }, /*#__PURE__*/React.createElement(WHead, {
    label: "Goal tracker \xB7 Monte Carlo"
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      padding: 14,
      display: 'flex',
      flexDirection: 'column',
      gap: 10
    }
  }, data.goals.map(g => {
    const c = g.probability >= 80 ? 'mint' : g.probability >= 70 ? 'indigo' : 'amber';
    return /*#__PURE__*/React.createElement("div", {
      key: g.name,
      style: {
        padding: '13px 16px',
        borderRadius: 12,
        background: 'var(--bg-1)',
        border: '1px solid var(--line)'
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        alignItems: 'baseline',
        gap: 10
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: 13.5,
        fontWeight: 500
      }
    }, g.name), /*#__PURE__*/React.createElement("span", {
      className: "nv-mono",
      style: {
        fontSize: 10.5,
        color: 'var(--ink-3)',
        marginLeft: 'auto',
        letterSpacing: '.04em'
      }
    }, g.corpus, " / ", g.target)), /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        marginTop: 10
      }
    }, /*#__PURE__*/React.createElement(Bar, {
      pct: g.probability,
      color: c,
      h: 8
    }), /*#__PURE__*/React.createElement("span", {
      className: "nv-num nv-serif",
      style: {
        fontSize: 18,
        color: `var(--${c})`,
        width: 40
      }
    }, g.probability, "%"), /*#__PURE__*/React.createElement("span", {
      className: "nv-mono",
      style: {
        fontSize: 10,
        color: 'var(--ink-3)',
        letterSpacing: '.04em',
        whiteSpace: 'nowrap'
      }
    }, "SIP ", g.sip)));
  })));
}

// 9 ── stress_test
function WStressTest({
  data
}) {
  const max = Math.max(...data.scenarios.map(s => Math.abs(s.drop)));
  return /*#__PURE__*/React.createElement("div", {
    style: wcard
  }, /*#__PURE__*/React.createElement(WHead, {
    label: "Stress test \xB7 historical scenarios"
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      padding: '16px 18px',
      display: 'flex',
      flexDirection: 'column',
      gap: 16
    }
  }, data.scenarios.map(s => /*#__PURE__*/React.createElement("div", {
    key: s.name
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'baseline',
      gap: 8,
      marginBottom: 7
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 13,
      fontWeight: 500
    }
  }, s.name), /*#__PURE__*/React.createElement("span", {
    className: "nv-serif nv-num",
    style: {
      marginLeft: 'auto',
      fontSize: 20,
      color: 'var(--danger)'
    }
  }, s.drop, "%"), /*#__PURE__*/React.createElement("span", {
    className: "nv-mono",
    style: {
      fontSize: 10,
      color: 'var(--ink-3)',
      letterSpacing: '.04em'
    }
  }, "~", s.days, "d recovery")), /*#__PURE__*/React.createElement(Bar, {
    pct: Math.abs(s.drop) / max * 100,
    color: "danger",
    h: 8,
    track: "var(--bg-3)"
  })))));
}

// 10 ── sip_plan
function WSipPlan({
  data
}) {
  const cells = [['Required SIP', data.sip, 'mint'], ['Duration', `${data.duration / 12 | 0} yrs`, 'ink'], ['Projected corpus', data.projected, 'ink'], ['Monthly shortfall', data.shortfall, 'amber']];
  return /*#__PURE__*/React.createElement("div", {
    style: wcard
  }, /*#__PURE__*/React.createElement(WHead, {
    label: "SIP plan \xB7 target back-calc",
    right: /*#__PURE__*/React.createElement("span", {
      className: "nv-mono",
      style: {
        fontSize: 10,
        color: 'var(--ink-3)',
        letterSpacing: '.04em'
      }
    }, "NOW \xB7 ", data.current, "/mo")
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      padding: 16,
      display: 'grid',
      gridTemplateColumns: 'repeat(2, 1fr)',
      gap: 10
    }
  }, cells.map(([l, v, c]) => /*#__PURE__*/React.createElement("div", {
    key: l,
    style: {
      padding: '14px 16px',
      borderRadius: 11,
      background: 'var(--bg-1)',
      border: '1px solid var(--line)'
    }
  }, /*#__PURE__*/React.createElement(Eb, null, l), /*#__PURE__*/React.createElement("div", {
    className: "nv-serif nv-num",
    style: {
      fontSize: 26,
      marginTop: 6,
      color: c === 'ink' ? 'var(--ink)' : `var(--${c})`
    }
  }, v)))));
}

// advisor client_book
function WClientBook({
  data
}) {
  return /*#__PURE__*/React.createElement("div", {
    style: wcard
  }, /*#__PURE__*/React.createElement(WHead, {
    label: "Client book \xB7 drift from target"
  }), /*#__PURE__*/React.createElement("table", {
    style: {
      width: '100%',
      borderCollapse: 'collapse'
    }
  }, /*#__PURE__*/React.createElement("caption", {
    className: "nv-mono",
    style: {
      captionSide: 'top',
      height: 0,
      overflow: 'hidden',
      opacity: 0
    }
  }, "Clients ranked by allocation drift"), /*#__PURE__*/React.createElement("tbody", null, data.clients.map((c, i) => /*#__PURE__*/React.createElement("tr", {
    key: c.name,
    style: {
      borderTop: i ? '1px solid var(--line)' : 0
    }
  }, /*#__PURE__*/React.createElement("td", {
    style: {
      padding: '13px 18px'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 14,
      fontWeight: 500
    }
  }, c.name), /*#__PURE__*/React.createElement("div", {
    className: "nv-mono",
    style: {
      fontSize: 10.5,
      color: 'var(--ink-3)',
      marginTop: 2,
      letterSpacing: '.04em'
    }
  }, c.value)), /*#__PURE__*/React.createElement("td", {
    className: "nv-num nv-serif",
    style: {
      padding: '13px 18px',
      textAlign: 'right',
      fontSize: 19,
      color: `var(--${c.flag})`
    }
  }, c.drift), /*#__PURE__*/React.createElement("td", {
    style: {
      padding: '13px 18px',
      textAlign: 'right'
    }
  }, /*#__PURE__*/React.createElement("span", {
    className: `nv-pill nv-pill-${c.flag}`
  }, c.risk, " risk")))))));
}
const WIDGETS = {
  portfolio_overview: WPortfolioOverview,
  rebalance_plan: WRebalancePlan,
  tax_harvest: WTaxHarvest,
  fund_comparison: WFundComparison,
  stock_screener: WStockScreener,
  sector_rotation: WSectorRotation,
  overlap_reveal: WOverlapReveal,
  goal_tracker: WGoalTracker,
  stress_test: WStressTest,
  sip_plan: WSipPlan,
  client_book: WClientBook
};
function NVWidget({
  type,
  data,
  onPick
}) {
  const C = WIDGETS[type];
  if (!C || type === 'none') return null;
  return /*#__PURE__*/React.createElement(C, {
    data: data,
    onPick: onPick
  });
}

// skeleton shown while widget_data streams in
function NVWidgetSkeleton() {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      ...wcard,
      padding: 18
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      height: 12,
      width: 140,
      borderRadius: 6,
      background: 'var(--bg-3)',
      marginBottom: 16,
      animation: 'nvshimmer 1.4s infinite'
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 12
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      width: 124,
      height: 124,
      borderRadius: '50%',
      background: 'var(--bg-3)',
      flex: 'none',
      animation: 'nvshimmer 1.4s .1s infinite'
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      display: 'grid',
      gridTemplateColumns: 'repeat(3,1fr)',
      gap: 12
    }
  }, Array.from({
    length: 6
  }).map((_, i) => /*#__PURE__*/React.createElement("div", {
    key: i,
    style: {
      height: 64,
      borderRadius: 10,
      background: 'var(--bg-3)',
      animation: `nvshimmer 1.4s ${i * 0.05}s infinite`
    }
  })))));
}
Object.assign(window, {
  NVWidget,
  NVWidgetSkeleton
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "app/widgets.jsx", error: String((e && e.message) || e) }); }

// ui_kits/copilot/screens-chat.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
// ─── Nivesh · Chat copilot (insight landing) — desktop + mobile ───
// Ported faithfully from frontend-v5/design/screens-chat.jsx (dev branch).
// Shared atoms (NVScoreRing, NVChatRow) + interactive thread state.
const {
  useState
} = React;
function NVScoreRing({
  size = 132,
  score = 86
}) {
  const r = (size - 18) / 2;
  const c = 2 * Math.PI * r;
  const dash = c * (score / 100);
  const cx = size / 2;
  return /*#__PURE__*/React.createElement("svg", {
    width: size,
    height: size,
    viewBox: `0 0 ${size} ${size}`
  }, /*#__PURE__*/React.createElement("defs", null, /*#__PURE__*/React.createElement("linearGradient", {
    id: `ring-${size}`,
    x1: "0",
    y1: "0",
    x2: "1",
    y2: "1"
  }, /*#__PURE__*/React.createElement("stop", {
    offset: "0",
    stopColor: "var(--mint)"
  }), /*#__PURE__*/React.createElement("stop", {
    offset: "1",
    stopColor: "var(--mint-2)"
  }))), /*#__PURE__*/React.createElement("circle", {
    cx: cx,
    cy: cx,
    r: r,
    fill: "none",
    stroke: "var(--bg-3)",
    strokeWidth: "10"
  }), /*#__PURE__*/React.createElement("circle", {
    cx: cx,
    cy: cx,
    r: r,
    fill: "none",
    stroke: `url(#ring-${size})`,
    strokeWidth: "10",
    strokeDasharray: `${dash} ${c - dash}`,
    strokeLinecap: "round",
    transform: `rotate(-90 ${cx} ${cx})`
  }), /*#__PURE__*/React.createElement("text", {
    x: cx,
    y: cx - 2,
    textAnchor: "middle",
    dominantBaseline: "middle",
    fill: "var(--ink)",
    fontFamily: "var(--display)",
    fontSize: size * 0.34,
    letterSpacing: "-0.04em"
  }, score), /*#__PURE__*/React.createElement("text", {
    x: cx,
    y: cx + size * 0.2,
    textAnchor: "middle",
    fill: "var(--ink-3)",
    fontFamily: "var(--mono)",
    fontSize: "10",
    letterSpacing: "2"
  }, "/ 100"));
}
function NVChatRow({
  severity,
  num,
  title,
  sub,
  value,
  delta
}) {
  const c = severity;
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 16,
      padding: '14px 18px',
      borderRadius: 12,
      background: 'var(--bg-1)',
      border: '1px solid var(--line)',
      cursor: 'pointer'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      width: 36,
      height: 36,
      borderRadius: 10,
      background: `var(--${c}-soft)`,
      border: `1px solid var(--${c}-line)`,
      display: 'grid',
      placeItems: 'center',
      color: `var(--${c})`,
      fontFamily: 'var(--mono)',
      fontSize: 11,
      fontWeight: 600,
      letterSpacing: '.04em',
      flex: 'none'
    }
  }, num), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      minWidth: 0
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 14.5,
      fontWeight: 500,
      letterSpacing: '-0.005em'
    }
  }, title), /*#__PURE__*/React.createElement("div", {
    className: "nv-mono",
    style: {
      fontSize: 11,
      color: 'var(--ink-3)',
      marginTop: 2,
      letterSpacing: '.04em',
      textTransform: 'uppercase'
    }
  }, sub)), value && /*#__PURE__*/React.createElement("div", {
    className: "nv-num",
    style: {
      fontSize: 18,
      color: `var(--${c})`,
      fontWeight: 500
    }
  }, value), delta && /*#__PURE__*/React.createElement("div", {
    className: "nv-mono nv-num",
    style: {
      fontSize: 11,
      color: 'var(--ink-3)',
      letterSpacing: '.04em'
    }
  }, delta), /*#__PURE__*/React.createElement("span", {
    style: {
      color: 'var(--ink-3)',
      fontSize: 20
    }
  }, "\u203A"));
}
const SIGNALS = [{
  l: 'Concentration',
  v: '58',
  d: 'down 4 wow',
  c: 'amber'
}, {
  l: 'Diversification',
  v: '78',
  d: 'flat',
  c: 'mint'
}, {
  l: 'Risk',
  v: '92',
  d: 'up 2',
  c: 'mint'
}, {
  l: 'Performance',
  v: '81',
  d: 'up 1.4%',
  c: 'mint'
}, {
  l: 'Goals',
  v: '74',
  d: '2 of 3 on track',
  c: 'indigo'
}, {
  l: 'Tax',
  v: '88',
  d: '₹38k available',
  c: 'mint'
}];
const ACTIONS = [{
  severity: 'amber',
  num: '01',
  title: 'Trim financials from 32% → 24%',
  sub: 'Sell HDFC Bank · ₹1.8L',
  value: '-2.3 pt risk',
  delta: '+₹0.4L/yr exp.'
}, {
  severity: 'indigo',
  num: '02',
  title: 'Consolidate 3 large-cap funds with 71% overlap',
  sub: 'Move Axis BC → Parag P Flexi',
  value: '₹14k fees/yr',
  delta: 'cleaner book'
}, {
  severity: 'mint',
  num: '03',
  title: 'Harvest losses · ₹38,400 before Mar 31',
  sub: '3 lots flagged · auto-rebuy after 31 days',
  value: '₹11,520 saved',
  delta: 'tax · LTCG'
}];
const HISTORY_TODAY = [['Portfolio health · Nov 26', true], ['Should I rebalance financials?', false], ['Tax loss before March', false]];
const HISTORY_WEEK = ['Mid-cap exposure', 'Reading my CAS', 'Goals · Retirement gap'];
function NVChatDesktop() {
  const [chips] = useState(['Concentration', 'Tax', 'Goals']);
  return /*#__PURE__*/React.createElement("div", {
    className: "nv-frame",
    style: {
      width: '100%',
      minHeight: 920,
      display: 'flex'
    }
  }, /*#__PURE__*/React.createElement("aside", {
    style: {
      width: 240,
      borderRight: '1px solid var(--line)',
      padding: '22px 16px',
      display: 'flex',
      flexDirection: 'column',
      gap: 4,
      background: 'var(--bg-0)'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 10,
      padding: '4px 8px 22px'
    }
  }, /*#__PURE__*/React.createElement("span", {
    className: "nv-mark"
  }, "\u0928"), /*#__PURE__*/React.createElement("span", {
    className: "nv-serif",
    style: {
      fontSize: 18
    }
  }, "Nivesh")), /*#__PURE__*/React.createElement("div", {
    className: "nv-mono",
    style: {
      fontSize: 9.5,
      letterSpacing: '.16em',
      color: 'var(--ink-4)',
      padding: '6px 10px',
      textTransform: 'uppercase'
    }
  }, "Today"), HISTORY_TODAY.map(([t, on]) => /*#__PURE__*/React.createElement("div", {
    key: t,
    style: {
      padding: '9px 12px',
      fontSize: 13,
      borderRadius: 8,
      background: on ? 'var(--bg-2)' : 'transparent',
      color: on ? 'var(--ink)' : 'var(--ink-2)',
      border: on ? '1px solid var(--line)' : '1px solid transparent',
      cursor: 'pointer'
    }
  }, t)), /*#__PURE__*/React.createElement("div", {
    className: "nv-mono",
    style: {
      fontSize: 9.5,
      letterSpacing: '.16em',
      color: 'var(--ink-4)',
      padding: '18px 10px 6px',
      textTransform: 'uppercase'
    }
  }, "This week"), HISTORY_WEEK.map(t => /*#__PURE__*/React.createElement("div", {
    key: t,
    style: {
      padding: '9px 12px',
      fontSize: 13,
      color: 'var(--ink-2)',
      borderRadius: 8,
      cursor: 'pointer'
    }
  }, t)), /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 'auto',
      padding: '12px 10px',
      borderTop: '1px solid var(--line)',
      display: 'flex',
      alignItems: 'center',
      gap: 10
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      width: 30,
      height: 30,
      borderRadius: 8,
      background: 'var(--bg-3)',
      display: 'grid',
      placeItems: 'center',
      fontFamily: 'var(--mono)',
      fontSize: 11,
      color: 'var(--ink-2)'
    }
  }, "AK"), /*#__PURE__*/React.createElement("div", {
    style: {
      minWidth: 0
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 12.5,
      fontWeight: 500
    }
  }, "Aarav Kumar"), /*#__PURE__*/React.createElement("div", {
    className: "nv-mono",
    style: {
      fontSize: 9.5,
      color: 'var(--ink-3)'
    }
  }, "\u20B9 24.8 L \xB7 Verified")))), /*#__PURE__*/React.createElement("main", {
    style: {
      flex: 1,
      padding: '36px 56px 24px',
      maxWidth: 980,
      margin: '0 auto',
      display: 'flex',
      flexDirection: 'column'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 10,
      marginBottom: 22
    }
  }, /*#__PURE__*/React.createElement("span", {
    className: "nv-pill nv-pill-mint"
  }, /*#__PURE__*/React.createElement("span", {
    className: "nv-dot",
    style: {
      background: 'var(--mint)'
    }
  }), "NIDP CONNECTED"), /*#__PURE__*/React.createElement("span", {
    className: "nv-mono",
    style: {
      fontSize: 11,
      color: 'var(--ink-3)',
      letterSpacing: '.04em'
    }
  }, "last sync \xB7 2m ago \xB7 47 holdings"), /*#__PURE__*/React.createElement("span", {
    style: {
      marginLeft: 'auto',
      display: 'flex',
      gap: 6
    }
  }, /*#__PURE__*/React.createElement("button", {
    className: "nv-btn",
    style: {
      padding: '6px 11px',
      fontSize: 12
    }
  }, "Re-sync"), /*#__PURE__*/React.createElement("button", {
    className: "nv-btn",
    style: {
      padding: '6px 11px',
      fontSize: 12
    }
  }, "Share"))), /*#__PURE__*/React.createElement("div", {
    style: {
      alignSelf: 'flex-end',
      maxWidth: 540,
      padding: '12px 18px',
      background: 'var(--bg-2)',
      border: '1px solid var(--line)',
      borderRadius: '18px 18px 4px 18px',
      marginBottom: 28
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 14.5
    }
  }, "Read my portfolio. What's the one thing I should fix first?")), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 14,
      marginBottom: 14
    }
  }, /*#__PURE__*/React.createElement("span", {
    className: "nv-mark",
    style: {
      flex: 'none',
      marginTop: 4
    }
  }, "\u0928"), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "nv-serif",
    style: {
      fontSize: 32,
      lineHeight: 1.15,
      letterSpacing: '-0.02em',
      color: 'var(--ink)',
      maxWidth: 720
    }
  }, "Your portfolio is ", /*#__PURE__*/React.createElement("span", {
    style: {
      color: 'var(--mint)'
    }
  }, "healthy"), " \u2014 but financials are eating a third of every rupee you've invested."), /*#__PURE__*/React.createElement("p", {
    style: {
      fontSize: 15,
      color: 'var(--ink-2)',
      lineHeight: 1.6,
      marginTop: 14,
      maxWidth: 680
    }
  }, "You score 86. Three issues account for almost all of that 14-point gap \u2014 concentration first, then a hidden overlap between funds, then a tax window that closes in March. I've ordered them by \u20B9 impact."))), /*#__PURE__*/React.createElement("div", {
    className: "nv-card",
    style: {
      display: 'grid',
      gridTemplateColumns: '180px 1fr',
      gap: 0,
      marginBottom: 22,
      overflow: 'hidden'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      padding: '22px 18px',
      borderRight: '1px solid var(--line)',
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      background: 'var(--bg-0)'
    }
  }, /*#__PURE__*/React.createElement(NVScoreRing, {
    size: 130
  }), /*#__PURE__*/React.createElement("span", {
    className: "nv-pill nv-pill-mint",
    style: {
      marginTop: 14
    }
  }, "GRADE A")), /*#__PURE__*/React.createElement("div", {
    style: {
      padding: 18,
      display: 'grid',
      gridTemplateColumns: 'repeat(3, 1fr)',
      gap: 14
    }
  }, SIGNALS.map(m => /*#__PURE__*/React.createElement("div", {
    key: m.l,
    style: {
      padding: '10px 12px',
      borderRadius: 10,
      background: 'var(--bg-1)',
      border: '1px solid var(--line)'
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "nv-mono",
    style: {
      fontSize: 10,
      letterSpacing: '.1em',
      color: 'var(--ink-3)',
      textTransform: 'uppercase'
    }
  }, m.l), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'baseline',
      gap: 6,
      marginTop: 4
    }
  }, /*#__PURE__*/React.createElement("span", {
    className: "nv-serif nv-num",
    style: {
      fontSize: 32,
      letterSpacing: '-0.03em'
    }
  }, m.v), /*#__PURE__*/React.createElement("span", {
    className: "nv-mono",
    style: {
      fontSize: 10,
      color: `var(--${m.c})`
    }
  }, "/100")), /*#__PURE__*/React.createElement("div", {
    className: "nv-mono",
    style: {
      fontSize: 10,
      color: 'var(--ink-3)',
      letterSpacing: '.02em',
      marginTop: 2
    }
  }, m.d))))), /*#__PURE__*/React.createElement("div", {
    className: "nv-mono",
    style: {
      fontSize: 10.5,
      letterSpacing: '.16em',
      color: 'var(--ink-3)',
      textTransform: 'uppercase',
      marginBottom: 10
    }
  }, "Top 3 actions \xB7 ranked by \u20B9 impact"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 8,
      marginBottom: 22
    }
  }, ACTIONS.map(a => /*#__PURE__*/React.createElement(NVChatRow, _extends({
    key: a.num
  }, a)))), /*#__PURE__*/React.createElement("div", {
    className: "nv-glass",
    style: {
      marginTop: 'auto',
      padding: '14px 18px',
      display: 'flex',
      alignItems: 'center',
      gap: 12,
      borderRadius: 16
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      color: 'var(--ink-3)',
      fontSize: 18
    }
  }, "\uFF0B"), /*#__PURE__*/React.createElement("span", {
    style: {
      flex: 1,
      fontSize: 14,
      color: 'var(--ink-3)'
    }
  }, "Ask anything \xB7 \"what if I sell HDFC Bank?\""), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 6
    }
  }, chips.map(c => /*#__PURE__*/React.createElement("span", {
    key: c,
    style: {
      fontSize: 11,
      padding: '4px 9px',
      borderRadius: 999,
      border: '1px solid var(--line-2)',
      color: 'var(--ink-2)',
      cursor: 'pointer'
    }
  }, c))), /*#__PURE__*/React.createElement("button", {
    className: "nv-btn nv-btn-primary",
    style: {
      padding: '8px 12px',
      fontSize: 12
    }
  }, "\u2197 Send"))));
}
function NVChatMobile() {
  const MOBILE_ACTIONS = [{
    c: 'amber',
    n: '01',
    t: 'Trim financials 32 → 24%',
    s: 'HDFC Bank · ₹1.8L',
    v: '+₹0.4L/yr'
  }, {
    c: 'indigo',
    n: '02',
    t: '3 funds, 71% overlap',
    s: 'Axis BC → Parag P',
    v: '₹14k fees'
  }, {
    c: 'mint',
    n: '03',
    t: 'Harvest ₹38k loss',
    s: 'Before Mar 31',
    v: '₹11.5k saved'
  }];
  return /*#__PURE__*/React.createElement("div", {
    className: "nv-frame",
    style: {
      width: '100%',
      height: '100%',
      overflow: 'hidden',
      display: 'flex',
      flexDirection: 'column'
    }
  }, /*#__PURE__*/React.createElement("span", {
    className: "nv-notch"
  }), /*#__PURE__*/React.createElement("div", {
    className: "nv-statusbar"
  }, /*#__PURE__*/React.createElement("span", null, "9:41"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 12
    }
  }, "\u25CF \u25CF \u25CF")), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      padding: '8px 18px 14px',
      gap: 10
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      color: 'var(--ink-2)',
      fontSize: 20
    }
  }, "\u2261"), /*#__PURE__*/React.createElement("span", {
    className: "nv-serif",
    style: {
      fontSize: 17
    }
  }, "Portfolio health"), /*#__PURE__*/React.createElement("span", {
    className: "nv-pill nv-pill-mint",
    style: {
      marginLeft: 'auto',
      fontSize: 9
    }
  }, /*#__PURE__*/React.createElement("span", {
    className: "nv-dot",
    style: {
      background: 'var(--mint)'
    }
  }), "LIVE")), /*#__PURE__*/React.createElement("div", {
    style: {
      padding: '4px 18px 12px',
      flex: 1,
      overflow: 'hidden',
      display: 'flex',
      flexDirection: 'column'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      alignSelf: 'flex-end',
      maxWidth: 260,
      padding: '10px 14px',
      background: 'var(--bg-2)',
      border: '1px solid var(--line)',
      borderRadius: '14px 14px 3px 14px',
      marginBottom: 18
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 13
    }
  }, "What should I fix first?")), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 10,
      marginBottom: 14
    }
  }, /*#__PURE__*/React.createElement("span", {
    className: "nv-mark",
    style: {
      width: 26,
      height: 26,
      fontSize: 15,
      flex: 'none'
    }
  }, "\u0928"), /*#__PURE__*/React.createElement("div", {
    className: "nv-serif",
    style: {
      fontSize: 22,
      lineHeight: 1.18,
      letterSpacing: '-0.02em'
    }
  }, "Healthy \u2014 but financials are ", /*#__PURE__*/React.createElement("span", {
    style: {
      color: 'var(--mint)'
    }
  }, "32%"), ".")), /*#__PURE__*/React.createElement("div", {
    className: "nv-card",
    style: {
      padding: '14px 14px 12px',
      marginBottom: 14,
      display: 'flex',
      alignItems: 'center',
      gap: 14
    }
  }, /*#__PURE__*/React.createElement(NVScoreRing, {
    size: 84
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "nv-mono",
    style: {
      fontSize: 9,
      letterSpacing: '.14em',
      color: 'var(--ink-3)',
      textTransform: 'uppercase'
    }
  }, "Overall"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'baseline',
      gap: 6,
      marginTop: 2
    }
  }, /*#__PURE__*/React.createElement("span", {
    className: "nv-pill nv-pill-mint",
    style: {
      fontSize: 9
    }
  }, "GRADE A")), /*#__PURE__*/React.createElement("div", {
    className: "nv-mono",
    style: {
      fontSize: 10,
      color: 'var(--ink-3)',
      marginTop: 6,
      letterSpacing: '.04em'
    }
  }, "3 ACTIONS \xB7 14 PT GAP"))), /*#__PURE__*/React.createElement("div", {
    className: "nv-mono",
    style: {
      fontSize: 9.5,
      letterSpacing: '.14em',
      color: 'var(--ink-3)',
      textTransform: 'uppercase',
      marginBottom: 8
    }
  }, "Ranked by \u20B9 impact"), MOBILE_ACTIONS.map(r => /*#__PURE__*/React.createElement("div", {
    key: r.n,
    className: "nv-card-2",
    style: {
      display: 'flex',
      gap: 12,
      alignItems: 'center',
      padding: '12px 13px',
      marginBottom: 8
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      width: 30,
      height: 30,
      borderRadius: 9,
      background: `var(--${r.c}-soft)`,
      border: `1px solid var(--${r.c}-line)`,
      display: 'grid',
      placeItems: 'center',
      color: `var(--${r.c})`,
      fontFamily: 'var(--mono)',
      fontSize: 10,
      flex: 'none'
    }
  }, r.n), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      minWidth: 0
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 13,
      fontWeight: 500
    }
  }, r.t), /*#__PURE__*/React.createElement("div", {
    className: "nv-mono",
    style: {
      fontSize: 9.5,
      color: 'var(--ink-3)',
      marginTop: 2,
      letterSpacing: '.04em',
      textTransform: 'uppercase'
    }
  }, r.s)), /*#__PURE__*/React.createElement("div", {
    className: "nv-mono nv-num",
    style: {
      fontSize: 10,
      color: `var(--${r.c})`,
      letterSpacing: '.02em'
    }
  }, r.v))), /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 'auto'
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "nv-glass",
    style: {
      padding: '11px 14px',
      display: 'flex',
      alignItems: 'center',
      gap: 10,
      borderRadius: 999
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      color: 'var(--ink-3)'
    }
  }, "\uFF0B"), /*#__PURE__*/React.createElement("span", {
    style: {
      flex: 1,
      fontSize: 12.5,
      color: 'var(--ink-3)'
    }
  }, "Ask anything\u2026"), /*#__PURE__*/React.createElement("button", {
    className: "nv-btn nv-btn-primary",
    style: {
      padding: '6px 10px',
      fontSize: 11,
      borderRadius: 999
    }
  }, "\u2197")))), /*#__PURE__*/React.createElement("div", {
    className: "nv-homebar"
  }));
}
Object.assign(window, {
  NVChatDesktop,
  NVChatMobile,
  NVScoreRing,
  NVChatRow
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/copilot/screens-chat.jsx", error: String((e && e.message) || e) }); }

})();
