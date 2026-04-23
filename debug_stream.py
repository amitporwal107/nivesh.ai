"""Debug streaming endpoint response."""
import asyncio
import httpx

async def debug_stream():
    BASE_URL = "https://portfolio-pro-985.preview.emergentagent.com/api"
    TEST_USER_SESSION = "5770bebb-8a9a-41f7-a7b9-e8152ac25daa"
    
    headers = {
        "Cookie": f"session_token={TEST_USER_SESSION}",
        "Content-Type": "application/json"
    }
    
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{BASE_URL}/chat/stream",
            headers=headers,
            json={"message": "Hello"},
            timeout=30.0
        )
        
        print(f"Status: {response.status_code}")
        print(f"Headers: {dict(response.headers)}")
        print(f"Content preview: {response.text[:500]}")

if __name__ == "__main__":
    asyncio.run(debug_stream())