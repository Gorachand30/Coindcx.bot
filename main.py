import subprocess
import sys
import time

# Dono bots ko background me ek sath start karein
p1 = subprocess.Popen([sys.executable, "macro_4h_bot.py"])
p2 = subprocess.Popen([sys.executable, "coindcx_bot.py"])

print("Dono bots (1H Trend + 4H Macro) start ho chuke hain...")

try:
    while True:
        time.sleep(10)
except KeyboardInterrupt:
    p1.terminate()
    p2.terminate()
  
