import urllib.parse, os
from dotenv import load_dotenv

load_dotenv()
espn_s2 = os.getenv("ESPN_S2", "")
decoded = urllib.parse.unquote(espn_s2)
print("Decoded ESPN_S2:")
print(decoded)
