# SpendGuard Policy RAG Pipeline

This directory contains the LangFlow-based RAG (Retrieval-Augmented Generation) pipeline that enables SpendGuard's Policy Analyst to dynamically retrieve policy information from documents.

## Current Implementation Status

✅ **Completed:**
- LangFlow v1.7.3 installed and running at http://127.0.0.1:7860
- All required components added to flow:
  - Read File (for loading procurement-policy.pdf)
  - Recursive Character Text Splitter (1000 chunk size, 200 overlap)
  - OpenAI Embeddings (text-embedding-3-small)
  - Chroma DB (vector store)
  - Language Model (OpenAI gpt-4o-mini)
  - Chat Input/Output
- OpenAI API key configured in components
- Flow exported as `SpendGuard-Policy-RAG.json`

⏳ **Manual Steps Required:**
1. **Arrange Components**: Drag components apart on the canvas (they overlap)
2. **Connect Components** (drag from output port to input port):
   - Read File → Recursive Text Splitter (Input)
   - Recursive Text Splitter → Chroma DB (Ingest Data)
   - OpenAI Embeddings → Chroma DB (Embedding)
   - Chat Input → Chroma DB (Search Query)
   - Chat Input → Language Model (Input)
   - Chroma DB (Search Results) → Language Model (System Message as context)
   - Language Model (Model Response) → Chat Output
3. **Upload Policy Document**: Click "Select files" in Read File component
4. **Test**: Open Playground and ask a policy question

## Architecture Overview

```
procurement-policy.pdf
        │
        ▼
┌─────────────────────────┐
│  LangFlow: Docling      │  ← Parses PDF, preserves tables
│  Document Parser        │
└───────────┬─────────────┘
            │
            ▼
┌─────────────────────────┐
│  Hierarchical Chunker   │  ← Preserves section structure
│  (Section-aware)        │
└───────────┬─────────────┘
            │
            ▼
┌─────────────────────────┐
│  Embeddings             │  ← watsonx.ai or OpenAI
│  (text-embedding-3-small)│
└───────────┬─────────────┘
            │
            ▼
┌─────────────────────────┐
│  Chroma Vector Store    │  ← Local for demo
│  (policy_chunks)        │
└───────────┬─────────────┘
            │
            ▼
┌─────────────────────────┐
│  Semantic Retriever     │  ← Returns top-k relevant chunks
│  (k=3, similarity)      │
└───────────┬─────────────┘
            │
            ▼
┌─────────────────────────┐
│  ADK Tool Wrapper       │  ← Exposes as watsonx tool
│  (policy_rag_lookup)    │
└─────────────────────────┘
```

## Prerequisites

- Python 3.10+
- LangFlow 1.0+
- watsonx Orchestrate ADK

## Installation

```bash
# Install LangFlow
pip install langflow

# Install Docling for document parsing
pip install docling

# Install watsonx Orchestrate ADK
pip install wxo-adk
```

## Quick Start

### 1. Start LangFlow

```bash
langflow run
# Opens at http://127.0.0.1:7860
```

### 2. Import the Flow

1. Open LangFlow UI
2. Click "Import"
3. Select `policy-rag-flow.json`

### 3. Test the Pipeline

In LangFlow playground:
```
Query: "What is the equipment limit for interns?"
Response: "According to Section 3.2 (Equipment Tiers by Role),
          the equipment cap for Interns is $2,000."
```

## LangFlow Components

### Docling Document Parser
- **Purpose**: Parses procurement-policy.pdf with table preservation
- **Output**: Structured DoclingDocument with metadata
- **Key Feature**: Maintains section hierarchy (3.1, 3.2, etc.)

### Hierarchical Chunker
- **Strategy**: Section-based chunking
- **Chunk Size**: 500 tokens with 50 token overlap
- **Preserves**: Section numbers, table structure, headers

### Embeddings
- **Model**: `text-embedding-3-small` (OpenAI) or watsonx.ai equivalent
- **Dimension**: 1536
- **Batch Size**: 100 documents

### Chroma Vector Store
- **Collection**: `policy_chunks`
- **Persistence**: `./chroma_db/`
- **Metadata**: section_number, page_number, chunk_type

### Semantic Retriever
- **Top-K**: 3 chunks
- **Similarity**: Cosine
- **Filter**: Optional section_number filter

## ADK Integration

The RAG pipeline is exposed to watsonx Orchestrate via the ADK tool wrapper.

### Tool Definition

```python
# adk_policy_tool.py
from wxo_adk import Tool, ToolParameter

class PolicyRAGTool(Tool):
    """
    Retrieves relevant policy sections based on a query.
    Used by Policy Analyst agent for compliance checks.
    """

    name = "policy_rag_lookup"
    description = "Search procurement policy for relevant rules and limits"

    parameters = [
        ToolParameter(
            name="query",
            type="string",
            description="The policy question or compliance check",
            required=True
        ),
        ToolParameter(
            name="section_filter",
            type="string",
            description="Optional: filter to specific section (e.g., '3.2')",
            required=False
        )
    ]

    def execute(self, query: str, section_filter: str = None) -> dict:
        # Call LangFlow RAG endpoint
        response = self._call_langflow_rag(query, section_filter)

        return {
            "relevant_sections": response["chunks"],
            "citations": response["metadata"],
            "confidence": response["similarity_score"]
        }

    def _call_langflow_rag(self, query, section_filter):
        # LangFlow API integration
        import requests

        payload = {
            "input_value": query,
            "output_type": "chat",
            "input_type": "chat"
        }

        if section_filter:
            payload["tweaks"] = {
                "Retriever": {"filter": {"section_number": section_filter}}
            }

        response = requests.post(
            "http://127.0.0.1:7860/api/v1/run/policy-rag-flow",
            json=payload
        )

        return response.json()
```

### Registering the Tool

```bash
# Deploy to watsonx Orchestrate
wxo-adk deploy --tool adk_policy_tool.py --name "Policy RAG Lookup"
```

### Updating Policy Analyst Agent

After deploying the ADK tool, update the Policy Analyst's toolset in watsonx Orchestrate:

1. Navigate to Agent Builder > Policy Analyst
2. Click "Toolset" > "Add Tool"
3. Select "Policy RAG Lookup" from available tools
4. Update behavior instructions:

```
POLICY LOOKUP WORKFLOW:
1. Use the policy_rag_lookup tool to find relevant policy sections
2. Extract the specific rule from the retrieved content
3. Apply the rule to the user's request
4. Always cite the Section number from the retrieval

Example tool call:
- Query: "equipment limit for interns"
- Response: Section 3.2 states intern cap is $2,000
```

## Sample Queries

| Query | Expected Section | Expected Answer |
|-------|-----------------|-----------------|
| "What is the equipment limit for interns?" | 3.2 | $2,000 |
| "What approvals do I need for $15,000 software?" | 4.1 | C-level + Legal |
| "Can I buy gaming equipment?" | 3.4 | No - prohibited |
| "What vendors are preferred for hardware?" | 5.1 | Dell, Apple, Lenovo |

## Troubleshooting

### LangFlow won't start
```bash
# Check port availability
lsof -i :7860

# Try alternate port
langflow run --port 7861
```

### Embeddings fail
- Ensure OPENAI_API_KEY is set, or
- Configure watsonx.ai credentials in LangFlow settings

### ADK deployment fails
```bash
# Verify ADK installation
wxo-adk --version

# Check authentication
wxo-adk auth status
```

## Files

| File | Purpose |
|------|---------|
| `SpendGuard-Policy-RAG.json` | LangFlow flow definition (exported) - import this to continue |
| `adk_policy_tool.py` | ADK tool wrapper for watsonx integration |
| `README.md` | This documentation |

## Starting LangFlow

```bash
cd langflow
source .venv/bin/activate
langflow run
# Opens at http://127.0.0.1:7860
```

To import the exported flow:
1. Open LangFlow UI
2. Create new project or use existing
3. Click "Import" or drag the JSON file onto the canvas

## References

- [Docling Documentation](https://ds4sd.github.io/docling/)
- [LangFlow Documentation](https://docs.langflow.org/)
- [watsonx Orchestrate ADK](https://www.ibm.com/docs/en/watsonx/orchestrate)
