#!/usr/bin/env python3
"""
MongoDB Data Research Agent - Production-Ready Asynchronous Slack Bot

This bot integrates:
- Slack (async_app via Socket Mode)
- AWS Bedrock (Claude Sonnet 4.6 via Cross-Region Inference Profile)
- MongoDB MCP Server (via official mcp-python-sdk)
- LangGraph (create_react_agent for ReAct reasoning loop)

Author: Calixto Diaz
Version: 2.0 (Production-Hardened)
"""

import os
import sys
import asyncio
import boto3
import traceback
import warnings
import logging
from datetime import datetime
from typing import Optional
from pathlib import Path

# Load environment variables from .env file if it exists
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).parent / '.env'
    if env_path.exists():
        load_dotenv(dotenv_path=env_path)
        logging.info(f"✅ Loaded environment variables from {env_path}")
    else:
        logging.info("ℹ️  No .env file found, using system environment variables")
except ImportError:
    logging.warning("⚠️  python-dotenv not installed, skipping .env file loading")

# Slack SDK
from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.aiohttp import AsyncSocketModeHandler

# LangChain & AWS Bedrock
from langchain_aws import ChatBedrock
from langchain_core.messages import SystemMessage, HumanMessage

# LangGraph Agent Framework
from langgraph.prebuilt import create_react_agent

# MCP (Model Context Protocol) Integration
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from langchain_mcp_adapters.tools import load_mcp_tools

# ============================================================================
# CONFIGURATION & LOGGING SETUP
# ============================================================================

# Suppress deprecation warnings (create_react_agent is stable in LangGraph 0.2.x+)
warnings.filterwarnings('ignore', category=DeprecationWarning)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Configurable timeouts (can be overridden via environment variables)
TOOL_LOAD_TIMEOUT = int(os.environ.get("TOOL_LOAD_TIMEOUT", "60"))  # seconds
AGENT_EXECUTION_TIMEOUT = int(os.environ.get("AGENT_TIMEOUT", "300"))  # seconds
MCP_SESSION_INIT_TIMEOUT = int(os.environ.get("MCP_INIT_TIMEOUT", "30"))  # seconds

# ============================================================================
# ENVIRONMENT VARIABLE VALIDATION
# ============================================================================

def validate_environment() -> bool:
    """
    Validates that all required environment variables are set.
    Returns True if all required vars are present, False otherwise.
    """
    required_vars = {
        "SLACK_BOT_TOKEN": "Slack Bot User OAuth Token",
        "SLACK_APP_TOKEN": "Slack App-Level Token (for Socket Mode)",
        "MDB_MCP_CONNECTION_STRING": "MongoDB Atlas Connection String",
    }
    
    optional_vars = {
        "MDB_MCP_API_CLIENT_ID": "Atlas API Public Key (for Admin API tools)",
        "MDB_MCP_API_CLIENT_SECRET": "Atlas API Private Key (for Admin API tools)",
        "AWS_REGION": "AWS Region (default: us-east-1)",
    }
    
    missing = []
    for var, description in required_vars.items():
        if not os.environ.get(var):
            missing.append(f"  ❌ {var} - {description}")
            logger.error(f"Missing required environment variable: {var}")
        else:
            logger.info(f"✓ {var} is set")
    
    for var, description in optional_vars.items():
        if os.environ.get(var):
            logger.info(f"✓ {var} is set")
        else:
            logger.warning(f"⚠ {var} is NOT set - {description}")
    
    if missing:
        logger.error("❌ Missing required environment variables:")
        for item in missing:
            logger.error(item)
        return False
    
    logger.info("✅ All required environment variables are set")
    return True

# ============================================================================
# SLACK APP INITIALIZATION
# ============================================================================

app = AsyncApp(token=os.environ.get("SLACK_BOT_TOKEN"))
logger.info("Slack AsyncApp initialized")

# ============================================================================
# AWS BEDROCK LLM INITIALIZATION
# ============================================================================

try:
    bedrock_client = boto3.client(
        "bedrock-runtime", 
        region_name=os.environ.get("AWS_REGION", "us-east-1")
    )
    
    llm = ChatBedrock(
        client=bedrock_client,
        model_id="us.anthropic.claude-sonnet-4-6",  # Cross-Region Inference Profile
        model_kwargs={
            "temperature": 0,  # Deterministic responses for infrastructure queries
            "max_tokens": 4096  # Ensure sufficient space for detailed reports
        }
    )
    logger.info("✅ AWS Bedrock LLM initialized (Claude Sonnet 4.6)")
except Exception as e:
    logger.error(f"❌ Failed to initialize Bedrock LLM: {e}")
    sys.exit(1)

# ============================================================================
# SYSTEM PROMPT FOR AGENT PERSONA
# ============================================================================

SYSTEM_PROMPT_TEXT = """
You are the **MongoDB Data Research Agent**, an expert AI assistant specializing in MongoDB Atlas 
infrastructure analysis and database operations. Your mission is to help engineers understand their 
clusters, identify issues, and optimize performance and costs.

**OUTPUT FORMAT (MANDATORY):**
When providing executive summaries, health checks, or infrastructure reports, you MUST use this format:

*📊 Executive Summary:*
[Provide a 2-3 sentence high-level overview of the current state]

*🚨 Reliability & Health:*
[Highlight any degrading trends, critical issues, or anomalies. Also mention what IS working well.]

*💰 Cost Categories:*
[Identify the top infrastructure costs based on billing data or cluster configurations]

*💡 Recommended Actions:*
• [Actionable step 1]
• [Actionable step 2]
• [Actionable step 3 if applicable]

**TOOL USAGE STRATEGY:**
- Use Atlas Admin API tools for: billing, performance advisor, alerts, cluster configurations
- Use Database tools for: querying collections, checking indexes, data analysis
- ALWAYS query BOTH infrastructure (admin) and data layers when providing comprehensive reports
- If a tool fails, explain the issue clearly and continue with available information

**RESPONSE STYLE:**
- Be concise but thorough
- Use specific numbers and metrics when available
- Prioritize actionable insights over generic advice
- Format all responses for easy reading in Slack (use bold, bullets, emojis appropriately)
"""

# ============================================================================
# CORE AGENT EXECUTION LOGIC
# ============================================================================

async def run_agent(user_prompt: str, say) -> None:
    """
    Orchestrates the full agent execution flow:
    1. Spin up MongoDB MCP server via npx
    2. Load MCP tools into LangChain-compatible format
    3. Create LangGraph ReAct agent with system prompt
    4. Execute the reasoning loop
    5. Return the final response to Slack
    
    Args:
        user_prompt: The user's question or command
        say: Slack's async message sender function
    """
    start_time = datetime.now()
    logger.info(f"🚀 Starting agent execution for prompt: '{user_prompt[:80]}...'")
    
   # Configure the MongoDB MCP Server to run directly
    server_params = StdioServerParameters(
        command="mongodb-mcp-server",
        args=["--readOnly"], 
        env=os.environ.copy() 
    )
    
    try:
        # ====================================================================
        # STEP 1: Establish StdIO connection to MCP server
        # ====================================================================
        logger.info("🔌 Connecting to MongoDB MCP server via stdio...")
        async with stdio_client(server_params) as (read, write):
            logger.info("✅ MCP stdio connection established")
            
            # ================================================================
            # STEP 2: Create MCP client session
            # ================================================================
            async with ClientSession(read, write) as session:
                logger.info("📡 MCP session created, initializing...")
                
                # Initialize with timeout to prevent hanging
                try:
                    await asyncio.wait_for(
                        session.initialize(),
                        timeout=MCP_SESSION_INIT_TIMEOUT
                    )
                    logger.info("✅ MCP session initialized successfully")
                except asyncio.TimeoutError:
                    error_msg = f"MCP session initialization timed out after {MCP_SESSION_INIT_TIMEOUT}s"
                    logger.error(f"❌ {error_msg}")
                    await say(f"⚠️ Agent startup failed: {error_msg}\nPlease check MCP server configuration.")
                    return
                
                # ============================================================
                # STEP 3: Load MCP tools (with timeout to prevent schema freeze)
                # ============================================================
                logger.info("🔧 Loading MCP tools from server...")
                try:
                    tools = await asyncio.wait_for(
                        load_mcp_tools(session),
                        timeout=TOOL_LOAD_TIMEOUT
                    )
                    logger.info(f"✅ Successfully loaded {len(tools)} MCP tools")
                    
                    # Log available tools for debugging
                    tool_names = [tool.name for tool in tools]
                    logger.info(f"Available tools: {', '.join(tool_names)}")
                    
                except asyncio.TimeoutError:
                    error_msg = f"Tool loading timed out after {TOOL_LOAD_TIMEOUT}s (schema may be too complex)"
                    logger.error(f"❌ {error_msg}")
                    await say(
                        f"⚠️ Agent initialization failed: {error_msg}\n"
                        "This may indicate complex MongoDB schemas. Try increasing TOOL_LOAD_TIMEOUT."
                    )
                    return
                except Exception as e:
                    logger.error(f"❌ Error loading tools: {type(e).__name__}: {e}")
                    logger.error(traceback.format_exc())
                    await say(f"⚠️ Failed to load MongoDB tools: {type(e).__name__}: {str(e)}")
                    return
                
                # ============================================================
                # STEP 4: Create LangGraph ReAct agent
                # ============================================================
                logger.info("🧠 Creating LangGraph ReAct agent...")
                try:
                    agent = create_react_agent(llm, tools)
                    logger.info("✅ Agent created successfully")
                except Exception as e:
                    logger.error(f"❌ Agent creation failed: {type(e).__name__}: {e}")
                    logger.error(traceback.format_exc())
                    await say(f"⚠️ Failed to create agent: {type(e).__name__}: {str(e)}")
                    return
                
                # ============================================================
                # STEP 5: Execute the reasoning loop with system prompt
                # ============================================================
                logger.info(f"🤖 Executing agent reasoning loop (timeout: {AGENT_EXECUTION_TIMEOUT}s)...")
                try:
                    # Inject system prompt as the first message in the conversation
                    messages = [
                        SystemMessage(content=SYSTEM_PROMPT_TEXT),
                        HumanMessage(content=user_prompt)
                    ]
                    
                    result = await asyncio.wait_for(
                        agent.ainvoke({"messages": messages}),
                        timeout=AGENT_EXECUTION_TIMEOUT
                    )
                    logger.info("✅ Agent execution completed successfully")
                    
                    # Extract the final response from the agent
                    final_message = result["messages"][-1].content
                    
                    # Send response to Slack
                    await say(final_message)
                    
                    # Log execution metrics
                    elapsed = (datetime.now() - start_time).total_seconds()
                    logger.info(f"✅ Response delivered to Slack (total time: {elapsed:.2f}s)")
                    
                except asyncio.TimeoutError:
                    error_msg = f"Agent execution timed out after {AGENT_EXECUTION_TIMEOUT}s"
                    logger.error(f"❌ {error_msg}")
                    await say(
                        f"⚠️ Query timed out after {AGENT_EXECUTION_TIMEOUT}s. "
                        "The query may be too complex or the database may be slow to respond."
                    )
                except Exception as e:
                    error_details = traceback.format_exc()
                    
                    # Safely ignore the noisy shutdown error caused by the MCP server closing the pipe
                    if "anyio.BrokenResourceError" in error_details or "TaskGroup" in error_details:
                        logger.debug("✓ MCP server connection closed (ignoring expected broken pipe warning).")
                    else:
                        # Only alert Slack if it is a real error that stopped the bot from working
                        logger.error(f"❌ Agent execution failed: {type(e).__name__}: {e}")
                        logger.error(error_details)
                        await say(f"⚠️ Agent execution failed: {type(e).__name__}: {str(e)}\n\nCheck server logs for full details.")
    
    except BaseExceptionGroup as eg:
        # Python 3.11+ groups multiple async errors together. Let's inspect them.
        # We only want to ignore the specific AnyIO teardown race condition.
        has_broken_pipe = any("BrokenResourceError" in str(type(exc)) for exc in eg.exceptions)
        has_real_errors = any("BrokenResourceError" not in str(type(exc)) for exc in eg.exceptions)
        
        if has_broken_pipe and not has_real_errors:
            # It was ONLY the expected Node.js teardown bug. Safe to ignore.
            print("✓ MCP server connection closed (expected pipe drop).")
        else:
            # A REAL error is hiding in the group! Sound the alarm.
            error_details = traceback.format_exc()
            print(f"❌ Real Error inside TaskGroup: {error_details}")
            await say("Agent execution failed: Multiple background errors occurred. Check EC2 terminal logs.")

    except Exception as e:
        # This catches all normal, non-grouped errors (API failures, bad prompts, etc.)
        error_details = traceback.format_exc()
        print(f"❌ Error in run_agent: {error_details}")
        await say(f"Agent execution failed: {type(e).__name__}: {str(e)}")

# ============================================================================
# SLACK EVENT HANDLERS
# ============================================================================

@app.event("app_mention")
async def handle_app_mention(event, say):
    """
    Triggered when the bot is @mentioned in a channel.
    Extracts the user's message and invokes the agent.
    """
    raw_text = event.get('text', '')
    
    # Strip the bot mention tag (e.g., "<@U12345>")
    user_prompt = raw_text.split(">", 1)[1].strip() if ">" in raw_text else raw_text
    
    logger.info(f"📩 Received app_mention: '{user_prompt[:80]}...'")
    
    # Send acknowledgment to user
    await say(f"_🔍 Researching your query with Claude Sonnet 4.6..._")
    
    # Execute the agent
    await run_agent(user_prompt, say)


@app.event("message")
async def handle_message_events(event, say):
    """
    Handles direct messages (DMs) sent to the bot.
    Only responds to DMs, ignoring channel messages unless @mentioned.
    """
    # Ignore bot's own messages to prevent loops
    if event.get('bot_id'):
        return
    
    # Only respond in direct message channels
    if event.get("channel_type") == "im":
        user_prompt = event.get('text', '')
        
        # Strip any accidental mentions in DMs
        if ">" in user_prompt:
            user_prompt = user_prompt.split(">", 1)[1].strip()
        
        logger.info(f"📨 Received DM: '{user_prompt[:80]}...'")
        
        # Send acknowledgment
        await say(f"_🔍 Researching your query with Claude Sonnet 4.6..._")
        
        # Execute the agent
        await run_agent(user_prompt, say)

# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

async def main():
    """
    Main async function that validates environment and starts the Slack bot.
    """
    logger.info("="*70)
    logger.info("🚀 Mon Data Research Agent - Starting Up")
    logger.info("="*70)
    
    # Validate environment variables before starting
    if not validate_environment():
        logger.error("❌ Environment validation failed. Exiting.")
        sys.exit(1)
    
    logger.info(f"⏱️  Configured Timeouts:")
    logger.info(f"   - MCP Session Init: {MCP_SESSION_INIT_TIMEOUT}s")
    logger.info(f"   - Tool Loading: {TOOL_LOAD_TIMEOUT}s")
    logger.info(f"   - Agent Execution: {AGENT_EXECUTION_TIMEOUT}s")
    
    logger.info("="*70)
    logger.info("⚡️ Mongodb Data Research Agent is now ONLINE")
    logger.info("="*70)
    
    # Start the Socket Mode handler
    handler = AsyncSocketModeHandler(app, os.environ.get("SLACK_APP_TOKEN"))
    await handler.start_async()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\n👋 Shutting down gracefully...")
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")
        logger.error(traceback.format_exc())
        sys.exit(1)

