import asyncio
import os
import sys
from app.services.zelka import ZelkaClient
import logging

sys.path.append(".")
logging.basicConfig(level=logging.INFO)

async def main():
    user = os.getenv("ZELKA_USER")
    password = os.getenv("ZELKA_PASS")
    
    if not user or not password:
        print("Please set ZELKA_USER and ZELKA_PASS env vars")
        return

    client = ZelkaClient(user, password)
    print(f"Logging in as {user}...")
    success = await client.login()
    
    if success:
        print("✅ Login successful!")
        print("Searching for 'Matrix'...")
        results = await client.search("Matrix")
        print(f"Found {len(results)} results.")
        for r in results[:5]:
            print(f"- {r.title} ({r.url})")
    else:
        print("❌ Login failed.")
    
    await client.close()

if __name__ == "__main__":
    asyncio.run(main())
