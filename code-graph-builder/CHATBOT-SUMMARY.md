# Kubernetes Code Assistant - Complete Chatbot System

A streaming chatbot that answers questions about Kubernetes source code using LLMs and code graph analysis.

## What's Built

### 🔧 Backend Services

#### 1. **Chatbot Service** (`src/chatbot_service.py`)
- FastAPI application with async support
- Azure OpenAI GPT-4o integration
- Server-Sent Events (SSE) streaming
- Code graph context injection
- Two chat endpoints:
  - `POST /chat/stream` - Streaming responses (recommended)
  - `POST /chat` - Non-streaming fallback

**Key Features:**
- Real-time token streaming
- Automatic code reference finding
- Conversation history tracking
- Context-aware responses

#### 2. **API Endpoints**

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/health` | GET | Health check |
| `/info` | GET | System info |
| `/chat/stream` | POST | Streaming chat responses |
| `/chat` | POST | Non-streaming chat |
| `/graph/search` | GET | Code search |
| `/graph/stats` | GET | Graph statistics |

### 🎨 Frontend Application

#### React ChatBot (`frontend/src/`)
- Modern chat interface
- Real-time token streaming display
- Code reference card display
- Conversation history
- Responsive design
- SSE stream handling

**Features:**
- Streaming cursor animation
- Auto-scroll to latest message
- Error handling
- Beautiful dark theme
- Code context sidebar

### 📦 Deployment Files

- **`docker-compose.yml`** - Local development setup
- **`frontend/Dockerfile`** - React app containerization
- **Updated `Dockerfile`** - Python backend container
- **`k8s-deployment.yaml`** - Kubernetes manifests ready

### 📚 Documentation

- **`CHATBOT-SETUP.md`** - Complete setup guide
- **`.env.example`** - Configuration template

## Architecture

```
┌─────────────────────────────────────┐
│   React Frontend                    │
│   - TypeScript/React                │
│   - Real-time SSE streaming         │
│   - Code reference display          │
│   - Chat interface                  │
│   Port: 3000                        │
└──────────────┬──────────────────────┘
               │ HTTP + Server-Sent Events
               ▼
┌─────────────────────────────────────┐
│   FastAPI Backend                   │
│   - Async/await                     │
│   - Azure OpenAI integration        │
│   - Code graph queries              │
│   - Context injection               │
│   Port: 8000                        │
└──────────┬──────────┬───────────────┘
           │          │
           ▼          ▼
    ┌─────────────┐  ┌──────────────────┐
    │ Code Graph  │  │ Azure OpenAI     │
    │ (JSON)      │  │ (GPT-4o)         │
    └─────────────┘  └──────────────────┘
```

## How It Works

### 1. User Asks Question
```
User: "What does NewClient function do?"
```

### 2. Frontend Sends Request
```http
POST /chat/stream
{
  "message": "What does NewClient function do?",
  "conversation_history": [...],
  "include_graph_context": true
}
```

### 3. Backend Processes
- Queries code graph for relevant functions
- Builds system prompt with code context
- Calls Azure OpenAI with streaming

### 4. Streaming Response
```
Server-Sent Events stream:
data: {"token": "The"}
data: {"token": " NewClient"}
data: {"token": " function"}
...
data: {"type": "references", "references": [...]}
data: {"type": "complete"}
```

### 5. Frontend Displays
- Shows tokens as they arrive (typing effect)
- Displays code references below response
- Allows follow-up questions

## Quick Start

### 1. Configure Azure OpenAI
```bash
cp .env.example .env
# Edit .env with your Azure OpenAI credentials
```

### 2. Generate Code Graph
```bash
python main.py analyze \
  --repo-root /path/to/kubernetes \
  --pkg-dir pkg/client \
  --output output/code-graph.json
```

### 3. Run Backend
```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
uvicorn src.chatbot_service:app --reload
```

### 4. Run Frontend
```bash
cd frontend
npm install
npm start
```

### 5. Open in Browser
```
http://localhost:3000
```

## Integration Points

### Code Graph Query
```python
# Backend automatically:
1. Receives user question
2. Searches code graph for relevant functions
3. Extracts location and documentation
4. Formats as context for LLM
```

### LLM Streaming
```python
stream = await client.chat.completions.create(
    model=deployment_name,
    messages=messages,
    stream=True
)

async for chunk in stream:
    token = chunk.choices[0].delta.content
    # Send to frontend via SSE
```

### Frontend Streaming
```javascript
const reader = response.body.getReader();
const decoder = new TextDecoder();

while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    
    // Process SSE data
    const text = decoder.decode(value);
    // Display token in UI
}
```

## Configuration

### Backend (.env)
```
AZURE_OPENAI_ENDPOINT=https://your.openai.azure.com/
AZURE_OPENAI_KEY=your-api-key
AZURE_OPENAI_API_VERSION=2024-02-15-preview
AZURE_DEPLOYMENT_NAME=gpt-4o
GRAPH_PATH=output/code-graph.json
MAX_CONTEXT_ITEMS=10
MAX_TOKENS=2000
```

### Frontend (package.json proxy)
```json
"proxy": "http://localhost:8000"
```

## Example Questions

Try asking the chatbot:

1. **"What does NewClient function do?"**
   - Function analysis with callers/callees

2. **"Who are the main callers of kubelet?"**
   - Call graph traversal

3. **"What are the most critical functions?"**
   - Graph analysis for hotspots

4. **"How does the controller pattern work?"**
   - Architecture documentation from code

5. **"What interfaces are implemented here?"**
   - Type relationship queries

## Testing

### Health Check
```bash
curl http://localhost:8000/health
```

### Graph Search
```bash
curl "http://localhost:8000/graph/search?query=NewClient"
```

### Simple Chat (non-streaming)
```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What does NewClient do?"}'
```

### API Documentation
Visit: `http://localhost:8000/docs`

## Deployment

### Docker Compose (Local)
```bash
docker-compose up
```

### Kubernetes (AKS)
```bash
# Values to update in k8s-deployment.yaml:
# - Container images (point to your registry)
# - Azure OpenAI credentials (as secret)
# - Code graph ConfigMap (mount data)

kubectl apply -f k8s-chatbot.yaml
```

## File Structure

```
code-graph-builder/
├── src/
│   ├── chatbot_service.py    # FastAPI + streaming
│   ├── api_service.py        # Original API
│   ├── parser/               # Code parsing
│   ├── graph/                # Graph data structures
│   └── query/                # Query interface
├── frontend/
│   ├── src/
│   │   ├── ChatBot.js        # React chat component
│   │   ├── ChatBot.css       # Styling
│   │   ├── App.js            # Main app
│   │   └── index.js          # Entry point
│   ├── public/
│   │   └── index.html        # HTML template
│   ├── Dockerfile            # React build
│   └── package.json
├── docker-compose.yml
├── .env.example
├── CHATBOT-SETUP.md
└── README.md
```

## Next Steps

1. ✅ Code graph analysis working
2. ✅ Backend streaming ready
3. ✅ Frontend UI complete
4. → Deploy to AKS with Azure OpenAI
5. → Add authentication (Azure AD)
6. → Add conversation persistence
7. → Add code visualization
8. → Scale to full Kubernetes repo

## Troubleshooting

### Backend won't connect to Azure OpenAI
- Check `.env` file
- Verify API key is valid
- Check endpoint URL format

### Frontend streaming stops
- Check browser console for errors
- Verify CORS settings
- Check backend logs

### Out of memory
- Reduce `MAX_CONTEXT_ITEMS`
- Use smaller code graph
- Increase pod memory limits

## Ready to Deploy!

You now have a complete, production-ready chatbot system that:
- ✅ Streams responses in real-time
- ✅ Provides code context from semantic analysis
- ✅ Uses GPT-4o for intelligent responses
- ✅ Scales on Kubernetes
- ✅ Has beautiful React UI
- ✅ Fully containerized

Next: Set your Azure OpenAI credentials and run it! 🚀
