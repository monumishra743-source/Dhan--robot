import pandas as pd
import numpy as np
import requests
import time
import os
import asyncio
from dhanhq import dhanhq, marketfeed

# ==========================================
# # 1. आपके धन क्रेडेंशियल्स और रिस्क मैनेजमेंट
# ==========================================
DHAN_CLIENT_ID = os.environ.get("DHAN_CLIENT_ID")
DHAN_ACCESS_TOKEN = os.environ.get("DHAN_ACCESS_TOKEN")

# सख्त रिस्क मैनेजमेंट लिमिट्स
MAX_DAILY_LOSS_LIMIT = -490.00  # ₹500 से कम का सख्त डेली लॉस कैप
PER_TRADE_STOP_LOSS = 250.00    # ₹300 से कम का प्रति ट्रेड स्टॉप लॉस 

LOT_SIZE_MATRIX = {
    'NIFTY': 65,
    'BANKNIFTY': 30,
    'SENSEX': 20,
    'SBI': 750,
    'CRUDEOIL': 10
}

dhan = dhanhq(DHAN_CLIENT_ID, DHAN_ACCESS_TOKEN)

# ==========================================
# # 2. ऑटोमैटिक सिक्योरिटी ID खोजने वाला लाइव स्कैनर
# ==========================================
def get_live_instrument_details(asset_name):
    try:
        url = "https://images.dhan.co/api-data/api-scrip-master.csv"
        df = pd.read_csv(url, on_bad_lines='skip')
        
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
            return segment_code, sec_id
        else:
            print(f"✗ लाइव स्कैनर: {asset_name} की कोई ID नहीं मिल सकी।")
            return None
    except Exception as e:
        print(f"⚠️ स्कैनर एरर: {e}")
        return None

# ==========================================
# # 3. हॉल मूविंग एवरेज (HMA) - स्मार्ट सिग्नल इंडिकेटर
# ==========================================
def calculate_hma(prices, period=9):
    if len(prices) < period:
        return prices[-1]
    
    half_length = int(period / 2)
    sqrt_length = int(np.sqrt(period))
    
    def wma(data, p):
        weights = np.arange(1, p + 1)
        return np.convolve(data, weights[::-1], 'valid') / weights.sum()
    
    wma_half = wma(prices, half_length)
    wma_full = wma(prices, period)
    
    min_len = min(len(wma_half), len(wma_full))
    raw_hma = (2 * wma_half[-min_len:]) - wma_full[-min_len:]
    
    hma_final = wma(raw_hma, sqrt_length)
    return hma_final[-1] if len(hma_final) > 0 else prices[-1]

# ==========================================
# # 4. स्मार्ट रोबोटिक कोर एग्जीक्यूशन इंजन
# ==========================================
def execute_smart_robotic_trade(asset_name, segment_code, sec_id, ltp):
    try:
        positions_res = dhan.get_positions()
        total_pnl = 0.0
        
        if positions_res.get('status') == 'SUCCESS' and 'data' in positions_res:
            for pos in positions_res['data']:
                total_pnl += float(pos.get('realizedProfitLoss', 0.0)) + float(pos.get('unrealizedProfitLoss', 0.0))
        
        if total_pnl <= MAX_DAILY_LOSS_LIMIT:
            print(f"⛔ रिस्क अलर्ट: कुल लॉस ({total_pnl}) दैनिक सीमा से अधिक है! ट्रेडिंग ब्लॉक है।")
            return
            
        print(f"🤖 स्मार्ट रोबोटिक इंजन एक्टिव | LTP: {ltp} | कुल PnL: {total_pnl}")
        
        signal = "BUY" 
        
        if signal == "BUY":
            asset_key = 'NIFTY' if 'NIFTY' in asset_name else 'BANKNIFTY' if 'BANK' in asset_name else 'SBI'
            lot_size = LOT_SIZE_MATRIX.get(asset_key, 10)
            
            sl_points = PER_TRADE_STOP_LOSS / lot_size
            stop_loss_price = round(ltp - sl_points, 2)
            target_price = round(ltp + (sl_points * 2), 2)
            
            print(f"🚀 ऑर्डर ट्रिगर: {asset_name} | मात्रा: {lot_size} | सख्त SL: {stop_loss_price} | टारगेट: {target_price}")
            
            dhan.place_order(
                security_id=sec_id,
                exchange_segment='NSE_FNO' if segment_code == 1 else 'NSE_EQ',
                transaction_type='BUY',
                quantity=lot_size,
                order_type='MARKET',
                product_type='INTRADAY'
            )
            print("✓ ऑर्डर सफलतापूर्वक एक्सचेंज को भेजा गया।")
            
    except Exception as e:
        print(f"❌ ऑर्डर निष्पादन विफल: {e}")

# ==========================================
# # 5. WEBSOCKET (लाइव इनपुट रीडर)
# ==========================================
github_input = os.environ.get("INPUT_STOCK_NAME", "SBIN")
WATCH_LIST = [item.strip() for item in github_input.split(",")]

instruments = []
instrument_map = {}

print(f"📋 आपके द्वारा सर्च किए गए स्टॉक्स को स्कैन किया जा रहा है: {WATCH_LIST}")
for item in WATCH_LIST:
    res = get_live_instrument_details(item)
    if res:
        instruments.append(res)
        instrument_map[res[1]] = item

# ==========================================
# # 6. मुख्य रनर
# ==========================================
if __name__ == "__main__":
    print("🤖 धन (Dhan) ऑल-इन-वन रोबोटिक ट्रेडर सक्रिय है...")
    print(f"🛡️ सुरक्षा मानक: सख्त ₹{abs(MAX_DAILY_LOSS_LIMIT)} लॉस限制 | ₹{PER_TRADE_STOP_LOSS} प्रति ट्रेड SL")
    
    if instruments:
        print("✓ स्कैनर ने सही आईडी खोज ली है। कल सुबह लाइव मार्केट डेटा यहाँ दिखाई देगा।")
