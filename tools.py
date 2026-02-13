import logging

import httpx
from langchain_core.tools import tool
from langgraph.prebuilt import ToolNode

logger = logging.getLogger(__name__)

# Base URL from your config
BASE_URL = "https://phonode.webdemozone.com/api"


async def fetch_from_api(endpoint: str, token: str):
    """Generic helper to fetch data from Phoenix Backend"""
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            url = f"{BASE_URL}/{endpoint}"
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"API Error at {endpoint}: {str(e)}")
            return None


# --- TOOLS FOR AI AGENT ---


@tool
async def get_user_home_context(token: str):
    """
    Fetches user's current health status, mood, sleep, and period tracking 
    from the Phoenix 'Home' API.
    """
    result = await fetch_from_api("user/home", token)
    
    if not result or not result.get("success"):
        return {"status": "error", "message": "Could not fetch home data."}

    home_data = result.get("data", {})
    recent = home_data.get("recentActivity", {})

    # Sirf kaam ka data AI ko pass karo taaki tokens bachein
    context = {
        "mood": recent.get("mood"),
        "sleep": recent.get("sleep"),
        "is_menstruating": recent.get("isCurrentlyMenstruating"),
        "period_flow": recent.get("periodFlow"),
        "articles_available": [a.get("title") for a in home_data.get("topArticles", [])]
    }
    
    return context
    

@tool
async def post_lifestyle_nudge(
    token: str, message: str, nudge_type: str = "lifestyle_update"
):
    """
    Sends a personalized nudge or actionable recommendation back to the backend
    to be displayed in the user's mobile app.
    """
    headers = {"Authorization": f"Bearer {token}"}
    payload = {"message": message, "type": nudge_type}

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                f"{BASE_URL}/notifications/nudge", json=payload, headers=headers
            )
            return {"status": "success" if response.status_code == 200 else "failed"}
        except Exception as e:
            return {"status": "error", "message": str(e)}


# --- TOOL NODE CONFIGURATION ---
def create_tool_node_with_fallback(tools: list):
    return ToolNode(tools)


# List of tools to be exported to main.py
# Ab list choti aur effective hai
ALL_LIFESTYLE_TOOLS = [get_user_home_context, post_lifestyle_nudge]

# import json
# import logging

# from langchain_core.tools import tool
# from langgraph.prebuilt import ToolNode

# logger = logging.getLogger(__name__)


# # --- MOCK DATA GENERATOR ---
# # Isse hum testing ke liye different scenarios simulate kar sakte hain
# def get_mock_response(endpoint: str):
#     mock_db = {
#         "user/wellness-summary": {
#             "mood": "Low",
#             "sleep_hours": 5.5,
#             "steps": 2300,
#             "energy_level": "Drained",
#             "last_7_days_trend": "Declining",
#         },
#         "user/nutrition/today": {
#             "calories": 1200,
#             "protein": "40g",
#             "water_intake": "1L",
#             "logged_items": ["Coffee", "Toast"],
#         },
#         "user/period-tracking/status": {
#             "current_day": 2,
#             "phase": "Menstrual",
#             "symptoms": ["Cramps", "Fatigue"],
#             "recommendation_engine_hint": "Low intensity movement only",
#         },
#     }
#     return mock_db.get(endpoint, {"status": "error", "message": "Endpoint not found"})


# # --- TOOLS WITH MOCK LOGIC ---


# @tool
# async def get_wellness_context(token: str):
#     """
#     Get comprehensive user data including mood trends and activity.
#     Currently returns Mock Data for testing.
#     """
#     logger.info("Fetching Mock Wellness Data...")
#     # Asli API call ki jagah mock data bhej rahe hain
#     return get_mock_response("user/wellness-summary")


# @tool
# async def get_nutrition_logs(token: str):
#     """
#     Fetches today's nutrition logs.
#     Manual Section 2.7: If empty, AI won't give nutrition tips.
#     """
#     # Isko 'None' karke test karna ki AI nutrition tips dena band karta hai ya nahi
#     return get_mock_response("user/nutrition/today")


# @tool
# async def check_period_cycle(token: str):
#     """
#     Checks the current day of the menstrual cycle (Section 2.9).
#     """
#     return get_mock_response("user/period-tracking/status")


# @tool
# async def post_lifestyle_nudge(token: str, message: str, nudge_type: str):
#     """
#     Simulates sending a nudge to the mobile app.
#     """
#     print(f"🚀 MOCK NUDGE SENT: [{nudge_type.upper()}] - {message}")
#     return {"status": "success", "sent_message": message}


# # --- TOOL NODE ---
# def create_tool_node_with_fallback(tools: list):
#     return ToolNode(tools)


# ALL_LIFESTYLE_TOOLS = [
#     get_wellness_context,
#     get_nutrition_logs,
#     check_period_cycle,
#     post_lifestyle_nudge,
# ]
