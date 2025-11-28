import asyncio
import os
import sys
from app.services.zamunda import ZamundaClient
import logging

# Add current dir to path
sys.path.append(".")

logging.basicConfig(level=logging.INFO)

async def main():
    user = os.getenv("ZAMUNDA_USER")
    password = os.getenv("ZAMUNDA_PASS")
    
    if not user or not password:
        print("Please set ZAMUNDA_USER and ZAMUNDA_PASS env vars")
        return

    client = ZamundaClient(user, password)
    print(f"Logging in as {user}...")
    success = await client.login()
    
    if success:
        print("✅ Login successful!")
        print("Searching for 'Matrix'...")
        results = await client.search("Matrix")
        print(f"Found {len(results)} results.")
        for r in results[:5]:
            print(f"- {r.title} ({r.size})")
    else:
        print("❌ Login failed.")
    
    await client.close()

if __name__ == "__main__":
    asyncio.run(main())
