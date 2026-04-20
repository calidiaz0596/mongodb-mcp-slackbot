# MongoDB Data Research Agent

**Production-ready asynchronous Slack bot** that integrates LangGraph, AWS Bedrock (Claude Sonnet 4.6), and the MongoDB MCP server to answer infrastructure and database queries.

---

## 🏗️ Architecture

<img width="1536" height="1024" alt="image" src="https://github.com/user-attachments/assets/c001262b-a84f-4784-8a01-3e5beb344a79" />


---

## 📦 Dependencies

### Python Packages
- **slack_bolt** (1.28.0+) - Async Slack SDK
- **langchain** (0.3.0+) - LLM orchestration
- **langchain_aws** (0.2.0+) - AWS Bedrock integration
- **langgraph** (0.2.0+) - Agent framework with `create_react_agent`
- **mcp** (1.0.0+) - Model Context Protocol SDK
- **langchain_mcp_adapters** (0.1.0+) - MCP-to-LangChain tool adapter
- **boto3** (1.42.0+) - AWS SDK

### External Dependencies
- **Node.js** (v18+ recommended) - Required for `npx mongodb-mcp-server`
- **MongoDB Atlas Account** - For cluster access and API keys

---

## 🔧 Setup Instructions

### 1. Install Python Dependencies

```bash
cd ~/Query_Mongo_With_Slack
pip install -r requirements.txt
```

### 2. Configure Environment Variables

Create a `.env` file or export these variables in your shell:

#### **Required Variables**

```bash
# Slack Credentials (from https://api.slack.com/apps)
export SLACK_BOT_TOKEN="xoxb-your-bot-token"
export SLACK_APP_TOKEN="xapp-your-app-token"

# MongoDB Atlas Connection - Use MCP user database credentials - readAnyDatabase & clusterMonitor access only 
export MDB_MCP_CONNECTION_STRING="mongodb+srv://username:password@cluster.mongodb.net/?retryWrites=true&w=majority"

# AWS Region (optional, defaults to us-east-1)
export AWS_REGION="us-east-1"
```

#### **Optional Variables (for Atlas Admin API tools)**

```bash
# Atlas Service Account For MCP  API Credentials - Organization Billing Viewer and roject Read Only roles required
export MDB_MCP_API_CLIENT_ID="your-public-api-key"
export MDB_MCP_API_CLIENT_SECRET="your-private-api-key"
```

#### **Timeout Configuration (optional)**

```bash
export MCP_INIT_TIMEOUT="30"        # MCP session initialization (default: 30s)
export TOOL_LOAD_TIMEOUT="60"       # Tool loading timeout (default: 60s)
export AGENT_TIMEOUT="300"          # Agent execution timeout (default: 300s)
```

### 3. Configure AWS Credentials

The bot uses AWS Bedrock for Claude Sonnet 4.6. Ensure you have:

#### **Option A: EC2 Instance with IAM Role**
```bash
# No configuration needed - boto3 automatically uses the instance role
```

#### **Option B: AWS Credentials File**
```bash
# ~/.aws/credentials
[default]
aws_access_key_id = YOUR_ACCESS_KEY
aws_secret_access_key = YOUR_SECRET_KEY
```

#### **Option C: Environment Variables**
```bash
export AWS_ACCESS_KEY_ID="your-access-key"
export AWS_SECRET_ACCESS_KEY="your-secret-key"
```

### 4. Set Up Slack App

1. Go to [https://api.slack.com/apps](https://api.slack.com/apps)
2. Create a new app (or use existing) - ie: @MongoBot
3. Enable **Socket Mode** and generate an App-Level Token
4. Add OAuth scopes:
   - `app_mentions:read`
   - `chat:write`
   - `im:history`
   - `im:read`
   - `im:write`
5. Install the app to your workspace
6. Copy the **Bot User OAuth Token** and **App Token**

### 5. Run the Bot

```bash
python bot.py
```

You should see:

```
======================================================================
🚀 MongoDB  Data Research Agent - Starting Up
======================================================================
✓ SLACK_BOT_TOKEN is set
✓ SLACK_APP_TOKEN is set
✓ MDB_MCP_CONNECTION_STRING is set
✅ All required environment variables are set
⏱️  Configured Timeouts:
   - MCP Session Init: 30s
   - Tool Loading: 60s
   - Agent Execution: 300s
======================================================================
⚡️ MongoDB  Data Research Agent is now ONLINE
======================================================================
```

---

## 🚀 Usage

### In Slack Channels
Mention the bot with your question:
```
@MongoBot What collections do we have in the production database?
```

### In Direct Messages
Just send your question directly:
```
Give me an executive summary of our Atlas cluster health
```

---

## 📊 Expected Output Format

The agent is configured to respond with structured reports:

```
*📊 Executive Summary:*
Your Atlas cluster is running 3 production databases with 15 collections 
total. Overall health is good with 99.9% uptime.

*🚨 Reliability & Health:*
• Cluster CPU usage is stable at 45%
• No active alerts or performance degradation
• Backup snapshots are current (last: 2 hours ago)

*💰 Cost Categories:*
• Compute: $450/month (M30 cluster tier)
• Storage: $120/month (500GB encrypted data)
• Backups: $80/month (7-day retention)

*💡 Recommended Actions:*
• Consider enabling Performance Advisor alerts
• Review index usage on the `orders` collection
• Upgrade to M40 if CPU consistently exceeds 70%
```

---

## 🛠️ Troubleshooting

### Issue: "Tool loading timed out after 60s"

**Cause:** MongoDB schemas are too complex for the MCP server to translate quickly.

**Solution:**
```bash
export TOOL_LOAD_TIMEOUT="120"  # Increase timeout to 2 minutes
```

### Issue: "MCP session initialization timed out"

**Cause:** Network connectivity issues or `npx` is slow to download the package.

**Solution:**
1. Pre-install the MCP server globally:
   ```bash
   npm install -g mongodb-mcp-server
   ```
2. Increase timeout:
   ```bash
   export MCP_INIT_TIMEOUT="60"
   ```

### Issue: "Missing required environment variable: MDB_MCP_CONNECTION_STRING"

**Cause:** Environment variables not exported.

**Solution:**
```bash
source Environment_variables.sh  # If using the provided script
# OR
export MDB_MCP_CONNECTION_STRING="your-connection-string"
```

### Issue: Agent freezes during tool loading

**Cause:** Known issue with `load_mcp_tools` when parsing complex JSON schemas.

**Solution:**
The new bot.py includes `asyncio.wait_for()` timeouts that will catch this and return a helpful error message. Increase `TOOL_LOAD_TIMEOUT` as needed.

---

## 🔒 Security Notes

1. **Read-Only Mode**: The MCP server is launched with `--readOnly` flag to prevent accidental writes
2. **Environment Variables**: Never commit `.env` files or hardcode credentials
3. **IAM Roles**: Use EC2 instance roles instead of access keys when possible
4. **Network Security**: Run on private subnets with appropriate security groups

---

## 📝 Development Notes

### Key Production Improvements

1. **Timeout Mechanisms**: All async operations wrapped with `asyncio.wait_for()`
2. **Comprehensive Logging**: Detailed logs at every stage for debugging
3. **Error Handling**: Try/except blocks with full tracebacks
4. **Environment Validation**: Startup checks for required variables
5. **Graceful Shutdown**: Handles KeyboardInterrupt and cleanup

### File Structure

```
my_scripts/Query_Mongo_With_Slack/
├── bot.py                      # Production-ready script (v2.0)
├── requirements.txt            # Python dependencies
├── Environment_variables.sh    # Example env var script
├── README.md                   # This file
└── ec2-vm-create.sh           # AWS EC2 deployment script
```

---

## 🧪 Testing

### Test 1: Simple Query
```
@MongoBot List all databases
```

### Test 2: Complex Analysis
```
@MongoBot Give me an executive summary with cost breakdown
```

### Test 3: Collection Query
```
@MongoBot How many documents are in the users collection?
```

---

## 📞 Support

For issues or questions:
1. Check the terminal logs for detailed error messages
2. Verify all environment variables are set correctly
3. Ensure Node.js and npx are installed: `npx --version`
4. Test AWS Bedrock access: `aws bedrock-runtime invoke-model help`

--
