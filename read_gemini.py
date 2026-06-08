import json
import re
import html

with open(r"C:\Users\ksh84\.gemini\antigravity\brain\171d5cf8-6e25-49da-9cad-edf705e09c9b\.system_generated\steps\2501\content.md", "r", encoding="utf-8") as f:
    text = f.read()

# Extract WIZ_global_data block
match = re.search(r'window\.WIZ_global_data\s*=\s*({.*?});', text, re.DOTALL)
if match:
    data_str = match.group(1)
    # The actual chat data is usually inside a stringified JSON in the "SVs1zb" or another key.
    # We will just search the entire data_str for unicode or Korean strings.
    # Decode unicode escapes manually
    decoded = data_str.encode('utf-8').decode('unicode_escape', 'ignore')
    decoded = html.unescape(decoded)
    
    korean_blocks = re.findall(r'[가-힣0-9a-zA-Z\s.,!?:()]{15,}', decoded)
    
    result = set()
    for block in korean_blocks:
        block = block.strip()
        if len(block) > 20 and re.search(r'[가-힣]', block):
            result.add(block)
            
    for i, b in enumerate(sorted(result, key=len, reverse=True)[:30]):
        print(f"--- Block {i} ---")
        print(b[:500]) # limit output length
else:
    print("WIZ_global_data not found.")
