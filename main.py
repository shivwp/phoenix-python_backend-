import json
import os
import re
import sys
import uuid
from contextlib import asynccontextmanager
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security.api_key import APIKeyHeader
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_google_genai import ChatGoogleGenerativeAI

# LangGraph & LangChain Imports
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import tools_condition
from pydantic import BaseModel, Field

from agents import Assistant, State, validate_session_and_get_config
from config import settings

# Custom Imports (Phoenix App)
from prompts import (
    ADMIN_DASHBOARD_PROMPT,  # Admin ke liye analytics/control prompt
    USER_LIFESTYLE_PROMPT,  # User ke liye guidance prompt
)
from tools import (
    # Ye list use karna aasaan rahega
    check_period_cycle,
    create_tool_node_with_fallback,
    get_nutrition_logs,
    get_wellness_context,
    post_lifestyle_nudge,
)


# ------------------------------------------------------------------
# Roles & Enums
# ------------------------------------------------------------------
class UserRole(str, Enum):
    USER = "user"
    ADMIN = "admin"


# ------------------------------------------------------------------
# Request/Response Models
# ------------------------------------------------------------------


class ChatRequest(BaseModel):
    role: UserRole
    message: str
    token: str  # Isse hi hum access_token ki tarah use karenge
    session_id: Optional[str] = None
    user_logs: Dict[str, Any] = Field(
        default_factory=dict
    )  # Mandatory for Smart Hashing


class ChatResponseItem(BaseModel):
    message: str
    type: Optional[str] = "text"
    data: Optional[Dict[str, Any]] = None


class ChatResponse(BaseModel):
    response: List[ChatResponseItem]
    session_id: str


# ------------------------------------------------------------------
# Helper Function: Process Data Into Items
# ------------------------------------------------------------------
def process_data_into_items(data: Any) -> List[ChatResponseItem]:
    """AI ke response (JSON) ko frontend ke standard format mein convert karta hai."""
    items = []
    if isinstance(data, list):
        for item in data:
            items.append(
                ChatResponseItem(
                    message=item.get("message", ""),
                    type=item.get("type", "text"),
                    data={
                        "phase": item.get("phase"),
                        "focus_habit": item.get("focus_habit"),
                        "action": item.get("action"),
                    },
                )
            )
    elif isinstance(data, dict):
        items.append(
            ChatResponseItem(
                message=data.get("message", ""),
                type=data.get("type", "text"),
                data=data.get("data"),
            )
        )
    return items


# ------------------------------------------------------------------
# Agent Factory (Logic for User & Admin)
# ------------------------------------------------------------------
def get_phoenix_agent(role: UserRole, tools: List):
    # Prompt logic
    system_prompt = (
        USER_LIFESTYLE_PROMPT if role == UserRole.USER else ADMIN_DASHBOARD_PROMPT
    )

    prompt_template = ChatPromptTemplate.from_messages(
        [
            ("system", system_prompt),
            # Context inject karne ke liye ek extra system message
            ("system", "Here is the user's current data: {lifestyle_context}"),
            MessagesPlaceholder(variable_name="messages"),
        ]
    )

    llm = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        google_api_key=settings.GEMINI_API_KEY,
        temperature=0.1
        if role == UserRole.ADMIN
        else 0.4,  # Admin strict, User conversational
    )

    runnable_chain = prompt_template | llm.bind_tools(tools)

    builder = StateGraph(State)
    builder.add_node("assistant", Assistant(runnable_chain))
    builder.add_node("tools", create_tool_node_with_fallback(tools))

    builder.add_edge(START, "assistant")
    builder.add_conditional_edges("assistant", tools_condition)
    builder.add_edge("tools", "assistant")

    memory = MemorySaver()
    return builder.compile(checkpointer=memory)


# ------------------------------------------------------------------
# Chat Logic
# ------------------------------------------------------------------
async def run_chatbot(runnable_graph, user_message, token, thread_id):
    config = {"configurable": {"thread_id": thread_id or str(uuid.uuid4())}}

    # Context injection
    input_state = {"messages": [("user", user_message)]}

    result = await runnable_graph.ainvoke(input_state, config)

    # --- SAFETY CHECK FOR CONTENT ---
    last_message = result["messages"][-1]
    content = last_message.content

    # Agar content list hai (Gemini blocks), toh pehla block uthao ya join karo
    if isinstance(content, list):
        # Aksar Gemini list mein bhejta hai [ {'type': 'text', 'text': '...'} ]
        content = " ".join(
            [
                block.get("text", "") if isinstance(block, dict) else str(block)
                for block in content
            ]
        )

    # Ab Robust JSON Cleanup chalega
    if isinstance(content, str) and content.strip():
        # Remove markdown tags
        cleaned = re.sub(r"^```json\s*|\s*```$", "", content.strip()).strip()
        try:
            data = json.loads(cleaned)
            return data if isinstance(data, list) else [data]
        except json.JSONDecodeError:
            # Agar JSON nahi hai toh simple text format mein bhej do
            return [{"message": cleaned, "type": "text"}]

    # Agar content empty ya non-string hai
    return [{"message": str(content), "type": "text"}]


# ------------------------------------------------------------------
# FastAPI App
# ------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Setup Tools
    user_tools = [get_wellness_context, get_nutrition_logs, check_period_cycle]
    admin_tools = [post_lifestyle_nudge]  # Ya jo bhi admin tools hain

    # Initialize separate agents
    app.state.user_agent = get_phoenix_agent(UserRole.USER, user_tools)
    app.state.admin_agent = get_phoenix_agent(UserRole.ADMIN, admin_tools)
    yield


app = FastAPI(title="PHOENIX AI", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)

api_key_header = APIKeyHeader(name="x-api-key", auto_error=True)


@app.post("/v1/chat", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest, api_key: str = Security(api_key_header)):
    try:
        # 1. & 2. AUTH & ROLE (Theek hai)
        if api_key != settings.X_API_KEY:
            raise HTTPException(status_code=403, detail="Unauthorized access")

        agent = (
            app.state.user_agent
            if request.role == UserRole.USER
            else app.state.admin_agent
        )

        # 3. SMART REDIS VALIDATION
        validated_thread_id = await validate_session_and_get_config(
            thread_id=request.session_id or str(uuid.uuid4()),
            current_lifestyle_data=request.user_logs,
        )

        # 4. PREPARE INPUT (Key Check: Kya State class mein 'lifestyle_context' hai?)
        input_state = {
            "messages": [("user", request.message)],
            "lifestyle_context": request.user_logs,
        }

        config = {
            "configurable": {
                "thread_id": validated_thread_id,
                "access_token": request.token,
            }
        }

        # 5. RUN AGENT
        result = await agent.ainvoke(input_state, config=config)

        # 6. RESPONSE PROCESSING (Robust Handling)
        last_msg = result.get("messages", [])[-1] if result.get("messages") else None

        if not last_msg:
            return ChatResponse(
                response=[ChatResponseItem(message="No response", type="error")],
                session_id=validated_thread_id,
            )

        # --- YAHAN FIX HAI ---
        response_content = last_msg.content

        # Agar content list hai (Gemini Multi-part), toh string banao
        if isinstance(response_content, list):
            response_content = " ".join(
                [
                    str(b.get("text", b)) if isinstance(b, dict) else str(b)
                    for b in response_content
                ]
            )

        if not response_content:
            return ChatResponse(
                response=[ChatResponseItem(message="Empty response", type="error")],
                session_id=validated_thread_id,
            )

        # Ab .strip() safely chalega
        cleaned_content = re.sub(
            r"^```json\s*|\s*```$", "", response_content.strip()
        ).strip()

        try:
            data = json.loads(cleaned_content)
            # Ensure data is processed into list of ChatResponseItem
            response_items = process_data_into_items(data)
            return ChatResponse(response=response_items, session_id=validated_thread_id)

        except json.JSONDecodeError:
            return ChatResponse(
                response=[ChatResponseItem(message=response_content, type="text")],
                session_id=validated_thread_id,
            )

    except HTTPException as e:
        raise e
    except Exception as e:
        print(f"🔥 CRITICAL ERROR: {str(e)}")  # Terminal mein error dekho
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
