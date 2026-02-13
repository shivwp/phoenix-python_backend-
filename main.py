import json
import re
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Dict, List, Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security.api_key import APIKeyHeader
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import START, StateGraph
from langgraph.prebuilt import tools_condition
from pydantic import BaseModel, Field

# Custom Imports
from agents import Assistant, State, validate_session_and_get_config
from config import settings
from prompts import USER_LIFESTYLE_PROMPT
from tools import (
    create_tool_node_with_fallback,
    get_user_home_context,  # Updated Tool
    post_lifestyle_nudge,  # Updated Tool
)


# ------------------------------------------------------------------
# Request/Response Models
# ------------------------------------------------------------------
class ChatRequest(BaseModel):
    message: str
    token: str
    session_id: Optional[str] = None
    user_logs: Optional[Dict[str, Any]] = Field(default_factory=dict)


class ChatResponseItem(BaseModel):
    message: str
    type: Optional[str] = "text"
    data: Optional[Dict[str, Any]] = None


class ChatResponse(BaseModel):
    response: List[ChatResponseItem]
    session_id: str


# ------------------------------------------------------------------
# Helper: Process JSON into ChatResponseItems
# ------------------------------------------------------------------
def process_data_into_items(data: Any) -> List[ChatResponseItem]:
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
                    }
                    if "phase" in item or "focus_habit" in item
                    else item.get("data"),
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
# Phoenix Agent Factory (User Only)
# ------------------------------------------------------------------
def get_phoenix_agent(tools: List):
    prompt_template = ChatPromptTemplate.from_messages(
        [
            ("system", USER_LIFESTYLE_PROMPT),
            ("system", "Current User Data Context: {lifestyle_context}"),
            MessagesPlaceholder(variable_name="messages"),
        ]
    )

    llm = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        google_api_key=settings.GEMINI_API_KEY,
        temperature=0.4,
    )

    runnable_chain = prompt_template | llm.bind_tools(tools)

    builder = StateGraph(State)
    builder.add_node("assistant", Assistant(runnable_chain))
    builder.add_node("tools", create_tool_node_with_fallback(tools))

    builder.add_edge(START, "assistant")
    builder.add_conditional_edges("assistant", tools_condition)
    builder.add_edge("tools", "assistant")

    return builder.compile(checkpointer=MemorySaver())


# ------------------------------------------------------------------
# FastAPI App Setup
# ------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Only User Tools - Updated to use the Master API Tool
    user_tools = [get_user_home_context, post_lifestyle_nudge]
    app.state.agent = get_phoenix_agent(user_tools)
    yield


app = FastAPI(title="PHOENIX AI - User Coach", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)
api_key_header = APIKeyHeader(name="x-api-key", auto_error=True)


@app.post("/v1/chat", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest, api_key: str = Security(api_key_header)):
    try:
        # Auth Check
        if api_key != settings.X_API_KEY:
            raise HTTPException(status_code=403, detail="Invalid API Key")

        # Session & Smart Hashing
        validated_thread_id = await validate_session_and_get_config(
            thread_id=request.session_id or str(uuid.uuid4()),
            current_lifestyle_data=request.user_logs,
        )
        now = datetime.now()
        current_context = f"Today is {now.strftime('%A')}, {now.strftime('%d %B %Y')}. Time: {now.strftime('%H:%M')}"
        # current_day = datetime.now().strftime("%A")
        # Prepare Graph Input
        input_state = {
            "messages": [("user", request.message)],
            "lifestyle_context": {
                    **request.user_logs, 
                    "current_time_info": current_context # AI ko pata chal gaya aaj Friday hai
                }
        }

        config = {
            "configurable": {
                "thread_id": validated_thread_id,
                "access_token": request.token,
            }
        }

        # Invoke Agent
        result = await app.state.agent.ainvoke(input_state, config=config)

        # Parse Response
        last_msg = result.get("messages", [])[-1] if result.get("messages") else None
        if not last_msg or not last_msg.content:
            return ChatResponse(
                response=[
                    ChatResponseItem(message="No response from coach", type="error")
                ],
                session_id=validated_thread_id,
            )

        content = last_msg.content
        # Handle Gemini List Content
        if isinstance(content, list):
            content = " ".join(
                [
                    str(b.get("text", b)) if isinstance(b, dict) else str(b)
                    for b in content
                ]
            )

        # Cleanup & JSON Load
        cleaned = re.sub(r"^```json\s*|\s*```$", "", content.strip()).strip()
        try:
            data = json.loads(cleaned)
            return ChatResponse(
                response=process_data_into_items(data), session_id=validated_thread_id
            )
        except json.JSONDecodeError:
            return ChatResponse(
                response=[ChatResponseItem(message=content, type="text")],
                session_id=validated_thread_id,
            )

    except Exception as e:
        print(f"🔥 ERROR: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
