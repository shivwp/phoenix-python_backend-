# import logging

# import httpx
# from dotenv import load_dotenv
# from langchain_core.tools import tool
# from langgraph.prebuilt import ToolNode

# from config import settings

# load_dotenv
# # Logging setup for debugging API calls
# logger = logging.getLogger(__name__)

# # Base URL from your shared link
# BASE_URL = settings.BASE_URL


# async def fetch_from_api(endpoint: str, token: str):
#     """Generic helper to fetch data from Phoenix Backend"""
#     headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
#     async with httpx.AsyncClient(timeout=10.0) as client:
#         try:
#             response = await client.get(f"{BASE_URL}/{endpoint}", headers=headers)
#             response.raise_for_status()
#             return response.json()
#         except Exception as e:
#             logger.error(f"API Error at {endpoint}: {str(e)}")
#             return None


# # --- TOOLS FOR AI AGENT ---


# @tool
# async def get_wellness_context(token: str):
#     """
#     Get comprehensive user data including mood trends, sleep logs,
#     activity metrics, and menstrual cycle phase for the last 7 days.
#     Use this to identify if it's a 'Low-Energy' or 'Good' week.
#     """
#     # Note: Backend team se ye endpoints confirm karne honge
#     # Agar alag alag endpoints hain toh hum multiple calls bhi kar sakte hain
#     data = await fetch_from_api("user/wellness-summary", token)
#     return (
#         data
#         if data
#         else {"status": "no_data", "message": "User has not logged data recently."}
#     )


# @tool
# async def get_nutrition_logs(token: str):
#     """
#     Fetches today's nutrition logs. If empty, the AI should NOT
#     provide nutrition tips as per manual section 2.7.
#     """
#     return await fetch_from_api("user/nutrition/today", token)


# @tool
# async def check_period_cycle(token: str):
#     """
#     Checks the current day of the menstrual cycle to adjust
#     lifestyle and energy recommendations (Section 2.9).
#     """
#     return await fetch_from_api("user/period-tracking/status", token)


# @tool
# async def post_lifestyle_nudge(token: str, message: str, nudge_type: str):
#     """
#     Sends a personalized nudge or recommendation back to the backend
#     to be displayed in the user's mobile app notifications (Section 2.10).
#     """
#     headers = {"Authorization": f"Bearer {token}"}
#     payload = {"message": message, "type": nudge_type}

#     async with httpx.AsyncClient() as client:
#         response = await client.post(
#             f"{BASE_URL}/notifications/nudge", json=payload, headers=headers
#         )
#         return response.status_code == 200


# # --- TOOL NODE CONFIGURATION ---
# def create_tool_node_with_fallback(tools: list):

#     return ToolNode(tools)


# # List of tools to be exported to app.py
# ALL_LIFESTYLE_TOOLS = [
#     get_wellness_context,
#     get_nutrition_logs,
#     check_period_cycle,
#     post_lifestyle_nudge,
# ]


import json
import logging

from langchain_core.tools import tool
from langgraph.prebuilt import ToolNode

logger = logging.getLogger(__name__)


# --- MOCK DATA GENERATOR ---
# Isse hum testing ke liye different scenarios simulate kar sakte hain
def get_mock_response(endpoint: str):
    mock_db = {
        "user/wellness-summary": {
            "mood": "Low",
            "sleep_hours": 5.5,
            "steps": 2300,
            "energy_level": "Drained",
            "last_7_days_trend": "Declining",
        },
        "user/nutrition/today": {
            "calories": 1200,
            "protein": "40g",
            "water_intake": "1L",
            "logged_items": ["Coffee", "Toast"],
        },
        "user/period-tracking/status": {
            "current_day": 2,
            "phase": "Menstrual",
            "symptoms": ["Cramps", "Fatigue"],
            "recommendation_engine_hint": "Low intensity movement only",
        },
    }
    return mock_db.get(endpoint, {"status": "error", "message": "Endpoint not found"})


# --- TOOLS WITH MOCK LOGIC ---


@tool
async def get_wellness_context(token: str):
    """
    Get comprehensive user data including mood trends and activity.
    Currently returns Mock Data for testing.
    """
    logger.info("Fetching Mock Wellness Data...")
    # Asli API call ki jagah mock data bhej rahe hain
    return get_mock_response("user/wellness-summary")


@tool
async def get_nutrition_logs(token: str):
    """
    Fetches today's nutrition logs.
    Manual Section 2.7: If empty, AI won't give nutrition tips.
    """
    # Isko 'None' karke test karna ki AI nutrition tips dena band karta hai ya nahi
    return get_mock_response("user/nutrition/today")


@tool
async def check_period_cycle(token: str):
    """
    Checks the current day of the menstrual cycle (Section 2.9).
    """
    return get_mock_response("user/period-tracking/status")


@tool
async def post_lifestyle_nudge(token: str, message: str, nudge_type: str):
    """
    Simulates sending a nudge to the mobile app.
    """
    print(f"🚀 MOCK NUDGE SENT: [{nudge_type.upper()}] - {message}")
    return {"status": "success", "sent_message": message}


# --- TOOL NODE ---
def create_tool_node_with_fallback(tools: list):
    return ToolNode(tools)


ALL_LIFESTYLE_TOOLS = [
    get_wellness_context,
    get_nutrition_logs,
    check_period_cycle,
    post_lifestyle_nudge,
]
