import subprocess
import sys
import time
import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

# Keep-Alive Server Render ke liye
class SimpleServer(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"All Trading Engines Live!")

def keep_alive():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), SimpleServer)
    server.serve_forever()

threading.Thread(target=keep_alive, daemon=True).start()

# Dono bots ko background me start karein
p1 = subprocess.Popen([sys.executable, "macro_4h_bot.py"])
p2 = subprocess.Popen([sys.executable, "coindcx_bot.py"])

print("Dono bots (1H Trend + 4H Macro) start ho chuke hain...")

try:
    while True:
        time.sleep(10)
except KeyboardInterrupt:
    p1.terminate()
    p2.terminate()
    
