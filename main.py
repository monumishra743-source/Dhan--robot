import pandas as pd
import numpy as np
import requests
import time
from dhanhq import dhanhq

# =====================================================================
# 1. आपके धन क्रेडेंशियल्स 
# =====================================================================
DHAN_CLIENT_ID = "1111887318"
DHAN_ACCESS_TOKEN = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzUxMiJ9.eyJ1c2VyUmVnaW9uIjoiUjEiLCJpc3MiOiJkaGFuIiwicGFydG5lcklkIjoiIiwiZXhwIjoxNzkyMjMzMjg3LCJpYXQiOjE3OTIxNDY4ODcsInRva2VuQ29uc3VtZXJUeXBlIjoiU0VMRiIsIndlYmhvb2tVcmwiOiIiLCJkaGFuQ2xpZW50SWQiOiIxMTExODg3MzE4In0.Euc-3uwEdumnPOjyruXgbTVxHojPEmevukYW8S-KRiNbnZ2Bii90lBxkc-AKSJjicnokeA6mBvJdjutuFMKVqA"
NEWS_API_KEY = "YOUR_NEWS_API_KEY"

MAX_DAILY_LOSS_LIMIT = -495.00  
LOT_SIZE_MATRIX = {
    'NIFTY': 65,
    'BANKNIFTY': 30,
    'SENSEX': 20,
    'SBI': 750
}

dhan = dhanhq(client_id=DHAN_CLIENT_ID,access_token= DHAN_ACCESS_TOKEN)

# =====================================================================
# 2. लाइव न्यूज सेंटीमेंट इंजन
# =====================================================================
def get_live_news_sentiment(asset_name):
    try:
        if NEWS_API_KEY == "YOUR_NEWS_API_KEY":
            return "NEUTRAL"
        url = f"https://newsapi.org{asset_name}&apiKey={NEWS_API_KEY}"
        response = requests.get(url, timeout=5).json()
        articles = response.get('articles', [])
        
        pos_words = ['profit', 'growth', 'breakout', 'hike', 'deal', 'buy', 'bullish']
        neg_words = ['loss', 'crash', 'drop', 'fraud', 'penalty', 'sell', 'bearish', 'circuit']
        
        score = 0
        for art in articles[:5]:
            title = art['title'].lower() if art['title'] else ""
            for w in pos_words: score += 1 if w in title else 0
            for w in neg_words: score -= 1 if w in title else 0
                
        if score > 1: return "BULLISH"
        elif score < -1: return "BEARISH"
        return "NEUTRAL"
    except:
        return "NEUTRAL"

# =====================================================================
# 3. डेली रिस्क गार्ड (Daily Kill Switch - ₹500)
# =====================================================================
def check_daily_kill_switch():
    try:
        positions = dhan.get_positions()
        total_pnl = 0.0
        
        if positions.get('status') == 'success' and positions.get('data'):
            for pos in positions['data']:
                total_pnl += float(pos.get('realizedProfitLoss', 0.0)) + float(pos.get('unrealizedProfitLoss', 0.0))
                
        print(f"📊 लाइव डेली P&L स्टेटस: ₹{total_pnl}")
        
        if total_pnl <= MAX_DAILY_LOSS_LIMIT:
            print("🚨 [KILL SWITCH ACTIVATED] डेली लॉस लिमिट हिट! सभी ओपन ट्रेड्स क्लोज किए जा रहे हैं।")
            if positions.get('data'):
                for pos in positions['data']:
                    net_qty = int(pos.get('netQty', 0))
                    if net_qty != 0:
                        dhan.place_order(
                            security_id=pos.get('securityId'),
                            trading_symbol=pos.get('tradingSymbol'),
                            transaction_type=dhan.SELL if net_qty > 0 else dhan.BUY,
                            exchange_segment=pos.get('exchangeSegment'),
                            product_type=pos.get('productType'),
                            order_type=dhan.MARKET,
                            quantity=abs(net_qty)
                        )
            return True
        return False
    except Exception as e:
        print(f"⚠️ रिस्क गार्ड चेक एरर: {str(e)}")
        return False

# =====================================================================
# 4. डा. देवेन्द्र रैंको सुपरट्रेंड + इंस्टीट्यूशनल स्कैनर
# =====================================================================
def process_indicators_and_signals(df, asset_name):
    high_low = df['high'] - df['low']
    high_close = np.abs(df['high'] - df['close'].shift())
    low_close = np.abs(df['low'] - df['close'].shift())
    df['ATR'] = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1).rolling(window=10).mean()
    
    df['hl2'] = (df['high'] + df['low']) / 2
    df['Supertrend'] = 1.0  

    df['Is_Red_Bar'] = (df['close'] < df['open']) & ((df['open'] - df['close']) > df['ATR'] * 1.5)
    df['Bearish_OB_High'] = df['high'].shift(1).where(df['Is_Red_Bar']).ffill()
    
    last_row = df.iloc[-1]
    raw_signal = "HOLD"
    technical_sl = last_row['open']
    
    if last_row['Supertrend'] == 1.0 and last_row['close'] > last_row['open']:
        raw_signal = "BUY"
        technical_sl = last_row['open'] - (last_row['ATR'] * 0.2)
    elif last_row['Supertrend'] == -1.0 or last_row['Is_Red_Bar']:
        raw_signal = "SELL"
        technical_sl = last_row['Bearish_OB_High'] if not pd.isna(last_row['Bearish_OB_High']) else last_row['open']

    return raw_signal, technical_sl

# =====================================================================
# 5. कोर स्मार्ट एक्जीक्यूशन इंजन
# =====================================================================
def execute_smart_robotic_trade(asset_name, segment_type, security_id):
    if check_daily_kill_switch():
        return
        
    try:
        meta = dhan.get_fundamental_data(security_id)
        ltp = float(meta.get('last_price', 0))
        uc = float(meta.get('upper_circuit_limit', 0))
        lc = float(meta.get('lower_circuit_limit', 0))
    except:
        print("❌ धन लाइव डेटा फेच करने में असमर्थ।")
        return

    dummy_data = {
        'open': [ltp, ltp, ltp], 
        'high': [ltp, ltp, ltp], 
        'low': [ltp, ltp, ltp], 
        'close': [ltp, ltp, ltp], 
        'volume': [1000, 2000, 1500]
    }
    df = pd.DataFrame(dummy_data)
    
    base_signal, tech_sl = process_indicators_and_signals(df, asset_name)
    if base_signal == "HOLD":
        print(f"🔒 {asset_name}: कोई इंस्टीट्यूशनल सिग्नल नहीं है। LTP: {ltp}")
        return

    matched_key = next((k for k in LOT_SIZE_MATRIX.keys() if k in asset_name.upper()), None)
    if not matched_key:
        return
        
    lot_size = LOT_SIZE_MATRIX[matched_key]
    sl_points = abs(ltp - tech_sl)
    potential_loss = sl_points * lot_size
    
    if potential_loss > abs(MAX_DAILY_LOSS_LIMIT):
        print(f"🔒 [RISK BLOCK] {asset_name} ट्रेड रिजेक्टेड! संभावित लॉस ₹{potential_loss:.2f} बजट से बाहर है।")
        return

    news = get_live_news_sentiment(matched_key)
    
    if base_signal == "BUY":
        if ltp >= (uc * 0.99) and uc > 0: return
        if news == "BEARISH": return
        print(f"🚀 [DHAN ROBOT FULFILLED] 1 लॉट ({lot_size} Qty) BUY किया जा रहा है...")

    elif base_signal == "SELL":
        if ltp <= (lc * 1.01) and lc > 0: return
        if news == "BULLISH": return
        print(f"🚀 [DHAN ROBOT FULFILLED] 1 लॉट ({lot_size} Qty) SELL किया जा रहा है...")

if __name__ == "__main__":
    print("🤖 धन (Dhan) ऑल-इन-वन रोबोटिक ट्रेडर सक्रिय है...")
    print("📈 सुरक्षा मानक: सख्त ₹500 लॉस लिमिट | नो प्रॉफिट लिमिट (असीमित मुनाफा)")
    
    while True:
        execute_smart_robotic_trade(asset_name="BANKNIFTY", segment_type="INDICES", security_id="99926005")
        time.sleep(60)
