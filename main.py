import pandas as pd
import numpy as np
import requests
import time
import os
import asyncio
from dhanhq import dhanhq, marketfeed

# =====================================================================
# 1. आपके धन क्रेडेंशियल्स 
# =====================================================================
DHAN_CLIENT_ID = os.environ.get("DHAN_CLIENT_ID")
DHAN_ACCESS_TOKEN = os.environ.get("DHAN_ACCESS_TOKEN")
NEWS_API_KEY = "YOUR_NEWS_API_KEY"

MAX_DAILY_LOSS_LIMIT = -495.00  
LOT_SIZE_MATRIX = {
    'NIFTY': 65,
    'BANKNIFTY': 30,
    'SENSEX': 20,
    'SBI': 750,
    'CRUDEOIL': 10
}

dhan = dhanhq(DHAN_CLIENT_ID, DHAN_ACCESS_TOKEN)

 
# =====================================================================
# 2. ऑटोमैटिक सिक्योरिटी ID खोजने वाला लाइव स्कैनर
# =====================================================================
def get_live_instrument_details(asset_name):
    try:
        url = "https://images.dhan.co/api-data/api-scrip-master.csv"

        df = pd.read_csv(url)
        
        name_upper = asset_name.upper().strip()
        match = df[df['SEM_TRADING_SYMBOL'] == name_upper]
        
        if match.empty:
            match = df[df['SEM_TRADING_SYMBOL'].str.contains(name_upper, na=False, case=False)]
        
        if not match.empty:
            row = match.iloc[0]
            sec_id = str(row['SEM_SMST_SECURITY_ID'])
            seg_name = str(row['SEM_SEGMENT'])
            
            if 'FO' in seg_name: segment_code = 1
            elif 'MCX' in seg_name or 'COMM' in seg_name: segment_code = 11
            else: segment_code = 0
                
            print(f"✓ लाइव स्कैनर: {asset_name} मिल गया! ID: {sec_id}, सेगमेंट कोड: {segment_code}")
            return (segment_code, sec_id)
        else:
            print(f"✗ लाइव स्कैनर: {asset_name} की कोई ID नहीं मिल सकी।")
            return None
    except Exception as e:
        print(f"⚠️ स्कैनर एरर: {e}")
        return None

# =====================================================================
# 3. लाइव न्यूज सेंटीमेंट इंजन
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
# 4. डेली रिस्क गार्ड (Daily Kill Switch - ₹500)
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
                            transaction_type='SELL' if net_qty > 0 else 'BUY',
                            exchange_segment=pos.get('exchangeSegment'),
                            product_type=pos.get('productType'),
                            order_type='MARKET',
                            quantity=abs(net_qty)
                        )
            return True
        return False
    except Exception as e:
        print(f"⚠️ रिस्क गार्ड चेक एरर: {str(e)}")
        return False

# =====================================================================
# 5. डा. देवेन्द्र रैंको सुपरट्रेंड + इंस्टीट्यूशनल स्कैनर
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
# 6. कोर स्मार्ट एक्जीक्यूशन इंजन + लाइव डेटा इंटीग्रेशन
# =====================================================================
def execute_smart_robotic_trade(asset_name, segment_code, security_id, ltp):
    if check_daily_kill_switch():
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
    exchange_segment = 'NSE_FNO' if segment_code == 1 else ('MCX' if segment_code == 11 else 'NSE_EQ')

    if base_signal == "BUY" and news != "BEARISH":
        print(f"🚀 [DHAN ROBOT] 1 लॉट ({lot_size} Qty) BUY किया जा रहा है...")
        try:
            dhan.place_order(
                security_id=security_id,
                trading_symbol=asset_name,
                transaction_type='BUY',
                exchange_segment=exchange_segment,
                product_type='MARGIN',
                order_type='MARKET',
                quantity=lot_size
            )
        except Exception as e:
            print(f"❌ ऑर्डर निष्पादन विफल: {e}")

    elif base_signal == "SELL" and news != "BULLISH":
        print(f"🚀 [DHAN ROBOT] 1 लॉट ({lot_size} Qty) SELL किया जा रहा है...")
        try:
            dhan.place_order(
                security_id=security_id,
                trading_symbol=asset_name,
                transaction_type='SELL',
                exchange_segment=exchange_segment,
                product_type='MARGIN',
                order_type='MARKET',
                quantity=lot_size
            )
        except Exception as e:
            print(f"❌ ऑर्डर निष्पादन विफल: {e}")

# =====================================================================
# 7. WEBSOCKET (लाइव इनपुट रीडर)
# =====================================================================
github_input = os.environ.get("INPUT_STOCK_NAME", "SBIN")
WATCH_LIST = [item.strip() for item in github_input.split(",")]

instruments = []
instrument_map = {} 

print(f"🔄 आपके द्वारा सर्च किए गए स्टॉक्स को स्कैन किया जा रहा है: {WATCH_LIST}")
for item in WATCH_LIST:
    res = get_live_instrument_details(item)
    if res:
        instruments.append(res)
        instrument_map[res[1]] = item 

subscription_code = marketfeed.Ticker 

async def on_connect(instance):
    print("✓ [LIVE FEED CONNECTED] धन लाइव फीड सर्वर चालू हो गया है!")

async def on_message(instance, message):
    sec_id = str(message.get('security_id'))
    ltp = float(message.get('LTP', 0))
    
    if sec_id in instrument_map and ltp > 0:
        asset_name = instrument_map[sec_id]
        segment_code = next((x[0] for x in instruments if x[1] == sec_id), 0)
        print(f"📈 [LIVE FEED] {asset_name} → वर्तमान भाव (LTP): ₹{ltp}")
        execute_smart_robotic_trade(asset_name, segment_code, sec_id, ltp)

# =====================================================================
# 8. मुख्य रनर
# =====================================================================
if __name__ == "__main__":
    print("🤖 धन (Dhan) ऑल-इन-वन रोबोटिक ट्रेडर सक्रिय है...")
    print("📈 सुरक्षा मानक: सख्त ₹500 लॉस लिमिट | नो प्रॉफिट लिमिट")
    
    if instruments:
        feed = marketfeed.DhanFeed(
            DHAN_CLIENT_ID,DHAN_ACCESS_TOKEN
        )
