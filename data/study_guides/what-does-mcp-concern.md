**MCP Study Guide**
=====================

**Overview**
-------------

The Model Context Protocol (MCP) is an open protocol for integrating Large Language Models (LLMs) with external data sources and tools.

### What does MCP concern?

* **Context exchange**: MCP focuses on exchanging contextual information between AI applications and external data sources.
* **Protocol requirements**: MCP defines the standard for client-server communication, including lifecycle management and core primitives.

**Key Concepts**
-----------------

### Participants

* **MCP Host**: The AI application that coordinates and manages one or multiple MCP clients
* **MCP Client**: A component that maintains a connection to an MCP server and obtains context from an MCP server for the MCP host to use
* **MCP Server**: A program that provides context to MCP clients

**Primitives**
-------------

* **Tools**: Represent arbitrary code execution, must be treated with caution.
* **LLM Sampling Controls**: Users must explicitly approve LLM sampling requests.

### Data Layer Protocol

* **JSON-RPC 2.0**: The underlying RPC protocol used by MCP.
* **Lifecycle management**: Negotiates the capabilities that both client and server support.

**Transport Layer**
-------------------

* **Abstracts communication details**: Enables the same JSON-RPC 2.0 message format across all transport mechanisms.

### Implementation Guidelines

* **Tool Safety**: Hosts must obtain explicit user consent before invoking any tool.
* **LLM Sampling Controls**: Users should control whether sampling occurs, what prompts are sent, and what results the server can see.

**Exercises**

1. Explain the difference between a MCP host and an MCP client.
2. What is the purpose of lifecycle management in MCP?
3. Describe the three core primitives that servers can expose.
4. How does MCP handle tool safety?
5. What are LLM sampling controls, and how do they work?

**Checkpoints**

1. Familiarize yourself with the JSON-RPC 2.0 protocol.
2. Understand the concept of tools and their limitations in MCP.
3. Learn about LLM sampling controls and their importance in MCP.

Remember to visit [modelcontextprotocol.io](https://modelcontextprotocol.io) for implementation guides and examples.