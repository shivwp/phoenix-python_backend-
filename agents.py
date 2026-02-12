import hashlib
import json
from typing import Annotated, List, TypedDict

import redis.asyncio as redis
from langchain_core.messages import BaseMessage
from langchain_core.runnables import Runnable, RunnableConfig
from langgraph.checkpoint.memory import MemorySaver  # Ye RAM mein save karega
from langgraph.checkpoint.redis import RedisSaver
from langgraph.graph.message import add_messages

from config import settings

redis_url = settings.REDIS_URL


# 1. State Definition
class State(TypedDict):
    messages: Annotated[List[BaseMessage], add_messages]
    lifestyle_context: dict


# 2. Assistant Class
class Assistant:
    def __init__(self, runnable: Runnable):
        self.runnable = runnable

    def __call__(self, state: State, config: RunnableConfig):
        while True:
            result = self.runnable.invoke(state)
            if not result.tool_calls and (not result.content or result.content == ""):
                messages = state["messages"] + [
                    ("Analyze the user's mood and sleep logs and give me a summary.")
                ]
                state = {**state, "messages": messages}
            else:
                break
        return {"messages": result}


# 3. Redis Memory Setup
try:
    memory = RedisSaver.from_conn_string(settings.REDIS_URL)
    redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    print("✅ Redis Memory Connected Successfully")
except Exception as e:
    print(f"❌ Redis Connection Failed: {e}")
    memory = MemorySaver()


# ---------------------------------------------------------
# 4. SMART REDIS LOGIC (Data Matching & Validation)
# ---------------------------------------------------------
def get_log_hash(data: dict) -> str:
    """Sirf lifestyle metrics ka hash banata hai taaki unnecessary invalidation na ho."""
    if not data:
        return "empty_logs"

    # Sirf kaam ki keys ko filter karo jo context badalti hain
    # Inme se jo keys aapke 'user_logs' mein aati hain, wahi rakho
    lifestyle_keys = ["steps", "sleep", "mood", "water", "period_day", "weight"]

    # Ek naya dict banao sirf in keys ke saath
    filtered_data = {k: data[k] for k in lifestyle_keys if k in data}

    # Ab is filtered data ka hash banao
    encoded_data = json.dumps(filtered_data, sort_keys=True).encode("utf-8")
    return hashlib.md5(encoded_data).hexdigest()


async def validate_session_and_get_config(thread_id: str, current_lifestyle_data: dict):
    """
    Check karta hai ki purana data aur naya data same hai ya nahi.
    Agar data badal gaya, toh fresh thread_id return karega.
    """
    hash_key = f"hash:{thread_id}"
    current_hash = get_log_hash(current_lifestyle_data)

    # Redis se purana hash uthao
    # Note: redis_client synchronous hai toh seedha get karein
    stored_hash = await redis_client.get(hash_key)

    if stored_hash:
        # AGAR DATA MATCH NAHI HOTA -> PURANI HISTORY DELETE KARO
        if stored_hash != current_hash:
            print(f"⚠️ Data Mismatch for {thread_id}! Invalidating old history.")
            # Purani history delete kar rahe hain taaki AI hallucinate na kare
            await redis_client.delete(f"checkpoint:{thread_id}")
            return thread_id
            # Naya hash save karlo
        await redis_client.set(hash_key, current_hash)
        return thread_id  # Same ID but clean state

    # Pehli baar aa raha hai ya data same hai
    await redis_client.set(hash_key, current_hash)
    return thread_id


# 5. Tool Node Fallback
def create_tool_node_with_fallback(tools: list):
    from langgraph.prebuilt import ToolNode

    return ToolNode(tools)
