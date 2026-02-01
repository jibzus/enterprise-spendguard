"""
SpendGuard Policy RAG Tool - ADK Integration

This tool wraps the LangFlow RAG pipeline and exposes it to watsonx Orchestrate
via the Agent Development Kit (ADK). The Policy Analyst agent uses this tool
to dynamically retrieve policy information from the procurement policy document.

Usage:
    wxo-adk deploy --tool adk_policy_tool.py --name "Policy RAG Lookup"
"""

import os
import requests
from typing import Optional, Dict, Any, List

# ADK imports (install with: pip install wxo-adk)
try:
    from wxo_adk import Tool, ToolParameter, ToolResult
except ImportError:
    # Fallback for local development/testing
    class Tool:
        name = ""
        description = ""
        parameters = []
        def execute(self, **kwargs): pass

    class ToolParameter:
        def __init__(self, **kwargs): pass

    class ToolResult:
        def __init__(self, **kwargs): pass


class PolicyRAGTool(Tool):
    """
    Retrieves relevant policy sections based on a natural language query.

    This tool connects to a LangFlow RAG pipeline that:
    1. Uses Docling to parse the procurement policy PDF
    2. Chunks the document hierarchically by section
    3. Embeds chunks using text-embedding-3-small
    4. Stores in Chroma vector database
    5. Retrieves top-k relevant chunks via semantic search

    The Policy Analyst agent uses this tool to:
    - Look up equipment tier limits by role
    - Find approval thresholds for software purchases
    - Check vendor requirements
    - Identify prohibited items
    """

    name = "policy_rag_lookup"
    description = (
        "Search the procurement policy document to find relevant rules, "
        "limits, and requirements. Returns policy sections with citations."
    )

    parameters = [
        ToolParameter(
            name="query",
            type="string",
            description=(
                "The policy question or compliance check to perform. "
                "Examples: 'equipment limit for interns', "
                "'software approval thresholds', 'prohibited hardware'"
            ),
            required=True
        ),
        ToolParameter(
            name="section_filter",
            type="string",
            description=(
                "Optional: filter results to a specific policy section. "
                "Examples: '3.2' for Equipment Tiers, '4.1' for Software Approvals"
            ),
            required=False
        ),
        ToolParameter(
            name="top_k",
            type="integer",
            description="Number of relevant chunks to retrieve (default: 3)",
            required=False
        )
    ]

    # Configuration
    LANGFLOW_URL = os.getenv("LANGFLOW_URL", "http://127.0.0.1:7860")
    FLOW_ID = os.getenv("LANGFLOW_FLOW_ID", "policy-rag-flow")

    def execute(
        self,
        query: str,
        section_filter: Optional[str] = None,
        top_k: int = 3
    ) -> Dict[str, Any]:
        """
        Execute the policy lookup.

        Args:
            query: Natural language query about policy
            section_filter: Optional section number to filter results
            top_k: Number of chunks to retrieve

        Returns:
            Dictionary containing:
            - relevant_sections: List of matching policy excerpts
            - citations: Section numbers and page references
            - confidence: Similarity scores for matches
            - summary: Synthesized answer to the query
        """
        try:
            response = self._call_langflow_rag(query, section_filter, top_k)
            return self._format_response(response, query)
        except Exception as e:
            return self._handle_error(e, query)

    def _call_langflow_rag(
        self,
        query: str,
        section_filter: Optional[str],
        top_k: int
    ) -> Dict[str, Any]:
        """Call the LangFlow RAG endpoint."""

        payload = {
            "input_value": query,
            "output_type": "chat",
            "input_type": "chat",
            "tweaks": {
                "Retriever": {
                    "top_k": top_k
                }
            }
        }

        # Add section filter if provided
        if section_filter:
            payload["tweaks"]["Retriever"]["filter"] = {
                "section_number": {"$eq": section_filter}
            }

        endpoint = f"{self.LANGFLOW_URL}/api/v1/run/{self.FLOW_ID}"

        response = requests.post(
            endpoint,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=30
        )
        response.raise_for_status()

        return response.json()

    def _format_response(
        self,
        raw_response: Dict[str, Any],
        original_query: str
    ) -> Dict[str, Any]:
        """Format the LangFlow response for the Policy Analyst."""

        # Extract chunks and metadata from LangFlow response
        outputs = raw_response.get("outputs", [{}])
        result = outputs[0].get("outputs", [{}])[0] if outputs else {}

        chunks = result.get("chunks", [])
        metadata = result.get("metadata", [])

        # Build structured response
        relevant_sections = []
        citations = []
        confidence_scores = []

        for i, chunk in enumerate(chunks):
            section_info = {
                "content": chunk.get("text", ""),
                "section_number": metadata[i].get("section_number", "Unknown"),
                "section_title": metadata[i].get("section_title", ""),
                "page_number": metadata[i].get("page_number", 0)
            }
            relevant_sections.append(section_info)

            citation = f"Section {section_info['section_number']}"
            if section_info["section_title"]:
                citation += f" ({section_info['section_title']})"
            citations.append(citation)

            confidence_scores.append(chunk.get("similarity_score", 0.0))

        # Generate summary from retrieved content
        summary = self._generate_summary(relevant_sections, original_query)

        return {
            "query": original_query,
            "relevant_sections": relevant_sections,
            "citations": citations,
            "confidence": {
                "scores": confidence_scores,
                "average": sum(confidence_scores) / len(confidence_scores) if confidence_scores else 0
            },
            "summary": summary,
            "source": "ACME Corp Procurement Policy v2.1"
        }

    def _generate_summary(
        self,
        sections: List[Dict[str, Any]],
        query: str
    ) -> str:
        """Generate a brief summary from retrieved sections."""

        if not sections:
            return "No relevant policy sections found for this query."

        # For now, return the most relevant section's content
        # In production, this would use an LLM to synthesize
        top_section = sections[0]
        return (
            f"Based on {top_section['section_number']}: "
            f"{top_section['content'][:500]}..."
            if len(top_section['content']) > 500
            else f"Based on Section {top_section['section_number']}: {top_section['content']}"
        )

    def _handle_error(self, error: Exception, query: str) -> Dict[str, Any]:
        """Handle errors gracefully."""

        return {
            "query": query,
            "error": True,
            "error_message": str(error),
            "fallback": (
                "Unable to retrieve policy information dynamically. "
                "Please consult the policy document directly or contact "
                "procurement@acme.corp for assistance."
            ),
            "relevant_sections": [],
            "citations": []
        }


# For local testing
if __name__ == "__main__":
    tool = PolicyRAGTool()

    # Test queries
    test_queries = [
        "What is the equipment limit for interns?",
        "What approvals do I need for $15,000 software?",
        "Can I buy gaming equipment?",
    ]

    for query in test_queries:
        print(f"\n{'='*60}")
        print(f"Query: {query}")
        print(f"{'='*60}")

        # Note: This will fail without LangFlow running
        # result = tool.execute(query=query)
        # print(f"Result: {result}")

        print("(Run with LangFlow active to test)")
