"""Debug: dump iframe include HTML."""
import asyncio
import httpx

URL = "https://www.unistrapg.it/profilo_lingua_italiana/site/include/inc_funz_interag_asserire.html"

async def main():
    async with httpx.AsyncClient(follow_redirects=True) as client:
        r = await client.get(URL)
        print(r.text)

if __name__ == "__main__":
    asyncio.run(main())
