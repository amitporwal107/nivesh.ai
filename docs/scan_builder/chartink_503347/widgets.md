# Chartink dashboard 503347 ("Copy day trade") — widget definitions

Fetched 3 Nov 2026 ~19:50 IST from https://chartink.com/dashboard/503347 (public; the owner's copy of his private
dashboard 225969, which serves no definitions). **Definitions only** — no Chartink data is used; every number on the
Day trade tab is computed on our data (services/scan_builder/market_dashboard.py, build_daytrade_widgets).
Order = Chartink's layout, row by row. Segment {33489} = F&O stocks; {57960} is not published (run on F&O stocks,
owner 3 Nov 2026). Titles renamed on our tab for the owner's wording rule are noted.

## 1. RSI VWAP INTRADAY BUY (widget 5518231) — shown as "RSI VWAP intraday"

```
select latest Close - 1 day ago Close / 1 day ago Close * 100 as '% Change', latest Close as 'Price', latest Volume as 'Volume', latest VWAP as 'vwap', latest Rsi( 14 ) as 'rsi', latest StochRsi( 14 ) as 'stcohrsi' WHERE( {33489} ( latest close > 1 day ago high and [0] 30 minute rsi( 14 ) > 60 and latest vwap < [0] 5 minute close ) ) GROUP BY symbol ORDER BY 1 desc
```

## 2. Explosive movement (widget 5518232)

```
select latest Close - 1 day ago Close / 1 day ago Close * 100 as '% Change', latest Close as 'Price', latest Volume as 'Volume' WHERE( {cash} ( latest max( 5 , latest close ) > latest min( 5 , latest close ) * 1.15 and latest close > 20 and latest sma( volume,100 ) > 100000 and latest max( 5 , latest volume ) > latest sma( volume,40 ) * 2 and market cap > 10000 ) ) GROUP BY symbol ORDER BY 1 desc
```

## 3. Copy - Strong stocks (widget 5518234) — shown as "Strong stocks"
Description on Chartink: Stocks closing higher than their previous trading day continuously for the past 5 days

```
select latest Close - 1 day ago Close / 1 day ago Close * 100 as '% Change', latest Close as 'Price', latest Volume as 'Volume' WHERE( {cash} ( latest close > 1 day ago close and 1 day ago close > 2 days ago close and 2 days ago close > 3 days ago close and 3 days ago close > 4 days ago close and 4 days ago close > 5 days ago close ) ) GROUP BY symbol ORDER BY 1 desc
```

## 4. HIGH GROWTH STOCKS (widget 5518233)
Description on Chartink: HIGH GROWTH STOCKS

```
select latest Close - 1 day ago Close / 1 day ago Close * 100 as '% Change', latest Close as 'Price', latest Volume as 'Volume', latest Rsi( 14 ) as 'rsi', latest "sum( close  *  volume, 20 ) / sum( volume ,20 )" as 'VWMA', latest "ema( latest Close, 40 )" as 'rma' WHERE( {cash} ( 1 week ago close >= 12 months ago close * 1.75 and market cap >= 1000 and latest close > 50 and earning per share[eps] > 5 and latest volume > 100000 ) ) GROUP BY symbol ORDER BY 1 desc
```

## 5. Short term breakouts (widget 5518236)
Description on Chartink: Stocks trading near their high in the past 4 months with rising volumes and closing strong, indicating a possible breakout

```
select latest Close - 1 day ago Close / 1 day ago Close * 100 as '% Change', latest Close as 'Price', latest Volume as 'Volume', Market Cap as 'Column4' WHERE( {cash} ( latest max( 5 , latest close ) > 6 days ago max( 120 , latest close ) * 1.05 and latest volume > latest sma( volume,5 ) and latest close > 1 day ago close and market cap > 20 ) ) GROUP BY symbol ORDER BY 1 desc
```

## 6. Multiyear breakout (widget 5518237)
Description on Chartink: 52 week high breakouts

```
select latest Close - 1 day ago Close / 1 day ago Close * 100 as '% Change', latest Close as 'Price', latest Volume as 'Volume', latest Rsi( 14 ) as 'RSI', latest Macd Line( 26 , 12 , 9 ) as 'MACD', latest VWAP as 'VWAP', Market Cap as 'Market Cap' WHERE( {cash} ( latest high = latest max( 520 , latest high ) or latest high = latest max( 780 , latest high ) or latest high = latest max( 1040 , latest high ) or latest high = latest max( 1300 , latest high ) or latest high = latest max( 1560 , latest high ) or latest high = latest max( 1820 , latest high ) or latest high = latest max( 2080 , latest high ) or latest high = latest max( 2340 , latest high ) or latest high = latest max( 2600 , latest high ) or market cap > 10000 or latest volume > 1000000 ) ) GROUP BY symbol ORDER BY 1 desc
```

## 7. Uptrend - 52 Week High (widget 5518240)
Description on Chartink: 52 week high stocks in uptrend

```
select latest Close - 1 day ago Close / 1 day ago Close * 100 as '% Change', latest Close as 'Price', latest Volume as 'Volume' WHERE( {cash} ( weekly close >= weekly max( 52 , weekly close ) and weekly sma( weekly close,10 ) >= weekly sma( weekly close,30 ) and weekly sma( weekly close,30 ) >= weekly sma( weekly close,40 ) and market cap > 10000 ) ) GROUP BY symbol ORDER BY 1 desc
```

## 8. Stocks BELOW 50 DMA & 200 DMA (widget 5518241)
Description on Chartink: stocks below 50 DMA & 200 DMA

```
select latest Close - 1 day ago Close / 1 day ago Close * 100 as '% Change', latest Close as 'Price', latest Volume as 'Volume' WHERE( {cash} ( latest close > 5 and latest close < latest sma( close,50 ) and latest sma( close,50 ) < latest sma( close,200 ) and latest volume > 100000 and market cap > 10000 and earning per share[eps] > 20 and yearly pe ratio > 5 and yearly pe ratio < 25 ) ) GROUP BY symbol ORDER BY 1 desc
```

## 9. 12 Year High Breakout (widget 5518230)
Description on Chartink: 12 Year High Breakout

```
select latest Close - 1 day ago Close / 1 day ago Close * 100 as '% Change', latest Close as 'Price', latest Volume as 'Volume' WHERE( {cash} ( latest high >= latest max( 3000 , latest high ) ) ) GROUP BY symbol ORDER BY 1 desc
```

## 10. 52 week high breakout (widget 5518228)
Description on Chartink: 52 week  high breakout

```
select latest Close - 1 day ago Close / 1 day ago Close * 100 as '% Change', latest Close as 'Price', latest Volume as 'Volume' WHERE( {cash} ( latest close > 1 day ago max( 240 , latest high ) ) ) GROUP BY symbol ORDER BY 1 desc
```

## 11. high volume and price breakout stocks (widget 5518242)

```
select latest Close - 1 day ago Close / 1 day ago Close * 100 as '% Change', latest Close as 'Price', latest Volume as 'Volume' WHERE( {cash} ( latest volume > ( latest sma( volume,20 ) * 3 ) and latest volume > ( latest sma( volume,5 ) * 3 ) and( ( latest close - 1 day ago close ) / 1 day ago close ) > .01 ) ) GROUP BY symbol ORDER BY 1 desc
```

## 12. Stocks Under 300 (widget 5518245)
Description on Chartink: 200SMA>200SMA(52Weeks Ago)

```
select latest Close - 1 day ago Close / 1 day ago Close * 100 as '% Change', latest Close as 'Price', latest Volume as 'Volume', Market Cap as 'market cap' WHERE( {cash} ( latest close < 300 and latest close > 30 and weekly sma( close,200 ) > 52 weeks ago sma( close,200 ) and latest sma( close,50 ) > latest sma( close,200 ) and earning per share[eps] > prev year eps and earning per share[eps] > 50 and yearly return on capital employed percentage > 20 and market cap > 1000 ) ) GROUP BY symbol ORDER BY 1 desc
```

## 13. 10% DOWN STOCK (widget 5518238)
Description on Chartink: Futures stock down by more than 10% in last 3 days

```
select latest Close - 1 day ago Close / 1 day ago Close * 100 as '% Change', latest Close as 'Price', latest Volume as 'Volume' WHERE( {33489} ( latest close < 1 month ago close * 0.9 and market cap > 10000 and latest volume > 100000 ) ) GROUP BY symbol ORDER BY 1 desc
```

## 14. 52 WEEK HIGH STOCKS (widget 5518239)
Description on Chartink: 52 week high breakouts

```
select latest Close - 1 day ago Close / 1 day ago Close * 100 as '% Change', latest Close as 'Price', latest Volume as 'Volume' WHERE( {cash} ( latest high = latest max( 260 , latest high ) ) ) GROUP BY symbol ORDER BY 1 desc
```

## 15. Delivery % + Volume (widget 5518243)

```
select latest Close - 1 day ago Close / 1 day ago Close * 100 as '% Change', latest Close as 'Price', latest Volume as 'Volume' WHERE( {cash} ( latest volume > 1 day ago volume + 50000 and weekly rsi( 14 ) >= 69 ) ) GROUP BY symbol ORDER BY 1 desc
```

## 16. High Momentum Stocks (widget 5518229)

```
select latest Close - 1 day ago Close / 1 day ago Close * 100 as '% Change', latest Close as 'Price', latest Volume as 'Volume' WHERE( {cash} ( latest rsi( 14 ) > 50 and latest macd line( 26,12,9 ) > latest macd signal( 26,12,9 ) and latest cci( 20 ) > 0 and latest close > latest sma( close,200 ) and latest close > latest ema( close,200 ) and latest rsi( 14 ) > latest max( 3 , latest rsi( 14 ) ) and latest mfi( 14 ) > 60 and dividend > 0 and market cap > 1000 ) ) GROUP BY symbol ORDER BY 1 desc
```

## 17. 10% DOWN STOCK (widget 5518235)
Description on Chartink: Futures stock down by more than 10% in last 3 days

```
select latest Close - 1 day ago Close / 1 day ago Close * 100 as '% Change', latest Close as 'Price', latest Volume as 'Volume' WHERE( {33489} ( latest close < 1 month ago close * 0.9 ) ) GROUP BY symbol ORDER BY 1 desc
```

## 18. Swing trade breakout strategy 10-20% gains (widget 5518244) — shown as "Swing trade breakout"
Description on Chartink: Swing trade breakout strategy 10-20 gains & 7-10 days holding.

```
select latest Close - 1 day ago Close / 1 day ago Close * 100 as '% Change', latest Close as 'Price', latest Volume as 'Volume', latest Rsi( 14 ) as 'rsi', latest StochRsi( 14 ) as 'stoch rsi' WHERE( {cash} ( latest close >= latest sma( close,30 ) and latest close >= latest sma( close,50 ) and latest close >= latest sma( close,100 ) and latest close >= latest sma( close,200 ) and earning per share[eps] > prev year eps and net profit[quarter] >= net profit[yearly] and market cap > 10000 ) ) GROUP BY symbol ORDER BY 1 desc
```

## 19. 10x volume first 5 min (widget 5518247)
Description on Chartink: 10x volume first 5 min

```
select latest Close - 1 day ago Close / 1 day ago Close * 100 as '% Change', latest Close as 'Price', latest Volume as 'Volume' WHERE( {cash} ( [=1] 5 minute volume > [-1] 5 minute sma( volume,1000 ) * 10 and( {cash} ( latest volume > 1000000 and latest open >= 50 and latest "buyer initiated trades / seller initiated trades" > 1 ) ) ) ) GROUP BY symbol ORDER BY 1 desc
```

## 20. 15 minute Stock Breakouts (widget 5518246)
Description on Chartink: Intraday - identify strong support/resistance levels for Market hour trading

```
select latest Close - 1 day ago Close / 1 day ago Close * 100 as '% Change', latest Close as 'Price', latest Volume as 'Volume' WHERE( {57960} ( [0] 15 minute close > [-1] 15 minute max( 20 , [0] 15 minute close ) and [0] 15 minute volume > [0] 15 minute sma( volume,20 ) ) ) GROUP BY symbol ORDER BY 1 desc
```
